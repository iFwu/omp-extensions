import { describe, expect, it } from "bun:test";
import { mkdtempSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runSecretCommand } from "../src/tools/bash.ts";
import { injectBashCommand } from "../src/glue.ts";
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
