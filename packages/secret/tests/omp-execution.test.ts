import { describe, expect, it } from "bun:test";
import type { ExtensionAPI, ExtensionContext, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { mkdtempSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runSecretCommand, injectBashCommand, registerSecureBash, redactCredentialOutput } from "../src/tools/bash.ts";
import { setEnabled } from "../src/state.ts";
import { Vault } from "../src/vault.ts";

const cwd = process.cwd();

describe("OMP credential child processes", () => {
  it("isolates concurrent credentials without mutating the parent environment", async () => {
    const parentA = process.env.SEC_PORT_A;
    const parentB = process.env.SEC_PORT_B;
    const [a, b] = await Promise.all([
      runSecretCommand('sleep 0.05; printf "%s|%s" "$SEC_PORT_A" "${SEC_PORT_B-absent}"', cwd, { SEC_PORT_A: "synthetic-alpha" }, 5),
      runSecretCommand('sleep 0.05; printf "%s|%s" "$SEC_PORT_B" "${SEC_PORT_A-absent}"', cwd, { SEC_PORT_B: "synthetic-bravo" }, 5),
    ]);
    expect(a.output).toBe(`synthetic-alpha|${parentB ?? "absent"}`);
    expect(b.output).toBe(`synthetic-bravo|${parentA ?? "absent"}`);
    expect(process.env.SEC_PORT_A).toBe(parentA);
    expect(process.env.SEC_PORT_B).toBe(parentB);
  });

  it("treats punctuation and shell syntax in a credential as data", async () => {
    const v = new Vault("quote-test");
    const value = "fake-'\"$HOME;$(printf injected) space";
    v.add("canary", value, "prompt");
    const expanded = injectBashCommand('printf "%s" "{{sec:canary}}"', v);
    expect(expanded.block).toBeUndefined();
    expect(expanded.command).not.toContain(value);
    const result = await runSecretCommand(expanded.command, cwd, expanded.env, 5);
    expect(result.output).toBe(value);
    expect(result.exitCode).toBe(0);
  });

  // A real child and its descendants use the OS clock; JS fake timers cannot advance them.
  it("cancellation terminates descendants before a delayed side effect", async () => {
    const dir = mkdtempSync(join(tmpdir(), "omp-secret-cancel-"));
    const controller = new AbortController();
    try {
      const running = runSecretCommand('(sleep 0.4; touch should-not-exist) & wait', dir, {}, 5, controller.signal);
      setTimeout(() => controller.abort(), 40);
      const result = await running;
      expect(result.stopped).toBe("cancelled");
      await Bun.sleep(500);
      expect(existsSync(join(dir, "should-not-exist"))).toBe(false);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("timeout terminates descendants before a delayed side effect", async () => {
    const dir = mkdtempSync(join(tmpdir(), "omp-secret-timeout-"));
    try {
      const result = await runSecretCommand('(sleep 0.4; touch should-not-exist) & wait', dir, {}, 0.04);
      expect(result.stopped).toBe("timed out");
      await Bun.sleep(500);
      expect(existsSync(join(dir, "should-not-exist"))).toBe(false);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("an already cancelled call never starts its command", async () => {
    const result = await runSecretCommand('printf should-not-run', cwd, {}, 5, AbortSignal.abort());
    expect(result.output).toBe("");
    expect(result.stopped).toBe("cancelled");
  });

  it("withholds oversized output rather than leaking a truncated credential prefix", async () => {
    const result = await runSecretCommand('yes fake-output', cwd, {}, 5);
    expect(result.output).toBe("");
    expect(result.stopped).toBe("output exceeded 8 MiB; output withheld");
  });
});

function credentialTool(vault: Vault) {
  let tool: ToolDefinition | undefined;
  // The fixture provides only the registration surface exercised by the real tool.
  const host = {
    getAllTools: () => [{ name: "bash", sourceInfo: { source: "builtin" }, parameters: {}, description: "Bash" }],
    registerTool: (value: ToolDefinition) => { tool = value; },
  } as unknown as ExtensionAPI;
  registerSecureBash(host, { vault: () => vault });
  setEnabled(true);
  if (!tool) throw new Error("Credential tool was not registered");
  return tool;
}

// No UI or persistence is needed for this foreground child-process fixture.
const executionContext = { cwd, agent: { kind: "main" } } as unknown as ExtensionContext;

describe("explicit credential boundary", () => {
  it("redacts exact values only, without interpreting token shapes or encoded forms", () => {
    const value = "synthetic.p[a]ss+$";
    const ordinary = "confirm_password_ref=css:input[name=confirm] sk-proj-NotAStoredCredential123456789";
    const encoded = Buffer.from(value).toString("base64");
    expect(redactCredentialOutput(`${ordinary}\n${value}\n${encoded}`, [value]))
      .toBe(`${ordinary}\n[credential redacted]\n${encoded}`);
  });

  it("redacts overlapping values in one pass without altering surrounding bytes", () => {
    expect(redactCredentialOutput("left abcdefgh-more / abcdefgh right", ["abcdefgh", "abcdefgh-more"]))
      .toBe("left [credential redacted] / [credential redacted] right");
  });

  it("passes a credential to the child but returns only exact-value redaction", async () => {
    const vault = new Vault("explicit-output");
    vault.add("password", "synthetic password!", "prompt");
    const tool = credentialTool(vault);
    const result = await tool.execute("id", {
      command: `printf '%s\\n' '{{sec:password}}' 'confirm_password_ref=css:input[name=confirm]' 'password=ordinary-text'`,
    }, undefined, undefined, executionContext);
    expect(result.content).toEqual([{ type: "text", text: "[credential redacted]\nconfirm_password_ref=css:input[name=confirm]\npassword=ordinary-text\n\nExit code: 0" }]);
    expect(vault.names()).toEqual(["password"]);
  });

  it("keeps running-command output protected after the vault is cleared", async () => {
    const vault = new Vault("clear-during-command");
    vault.add("password", "synthetic-credential", "prompt");
    const tool = credentialTool(vault);
    const running = tool.execute("id", { command: `sleep 0.05; printf '%s' '{{sec:password}}'` }, undefined, undefined, executionContext);
    vault.clear();
    const result = await running;
    expect(result.content).toEqual([{ type: "text", text: "[credential redacted]\nExit code: 0" }]);
  });

  it("refuses unresolved and undeliverable references instead of executing placeholders", () => {
    const vault = new Vault("invalid-context");
    vault.add("password", "synthetic-credential", "prompt");
    expect(injectBashCommand("printf '%s' '{{sec:unknown}}'", vault).block).toBeDefined();
    expect(injectBashCommand("cat <<'EOF'\n{{sec:password}}\nEOF", vault).block).toBeDefined();
  });
});
