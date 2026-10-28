import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { bashRefIssues } from "../substitute/guard.ts";
import { filterChildShellEnv } from "@oh-my-pi/pi-utils";
import type { Vault } from "../vault.ts";
import { expandBash } from "../substitute/bash.ts";
import { findRefs } from "../refs.ts";
import { isEnabled } from "../state.ts";

export interface SecureBashOptions {
  vault: () => Vault;
}

const MAX_OUTPUT = 8 * 1024 * 1024;

export function injectBashCommand(command: string, vault: Vault) {
  const issues = bashRefIssues(command, vault);
  if (issues.length) return { command, env: {}, block: { reason: issues[0]!.problem } };
  const out = expandBash(command, name => vault.resolve(name));
  if (out.missing.length) {
    return { command, env: {}, block: { reason: `Cannot expand sec:${out.missing.join(", ")} in this shell context.` } };
  }
  return { command: out.command, env: out.env };
}

export function redactCredentialOutput(output: string, values: readonly string[]): string {
  const literals = [...new Set(values)].filter(Boolean).sort((a, b) => b.length - a.length);
  if (!literals.length) return output;
  const parts: string[] = [];
  let cursor = 0;
  while (cursor < output.length) {
    let start = -1;
    let length = 0;
    for (const value of literals) {
      const next = output.indexOf(value, cursor);
      if (next !== -1 && (start === -1 || next < start)) {
        start = next;
        length = value.length;
      }
    }
    if (start === -1) break;
    parts.push(output.slice(cursor, start), "[credential redacted]");
    cursor = start + length;
  }
  if (!cursor) return output;
  parts.push(output.slice(cursor));
  return parts.join("");
}

export interface SecretCommandResult {
  output: string;
  exitCode: number | null;
  stopped?: string;
}

// Credentials never enter OMP's persistent shell, execution args, or output sink.
export async function runSecretCommand(
  command: string,
  cwd: string,
  env: Record<string, string>,
  timeout: number,
  signal?: AbortSignal,
): Promise<SecretCommandResult> {
  if (signal?.aborted) return { output: "", exitCode: null, stopped: "cancelled" };
  const { promise, resolve: resolveResult, reject } = Promise.withResolvers<SecretCommandResult>();
    const child = spawn("/bin/bash", ["--noprofile", "--norc", "-c", command], {
      cwd,
      env: { ...filterChildShellEnv(process.env), BASH_ENV: "/dev/null", ENV: "/dev/null", SHELLOPTS: "", BASHOPTS: "", ...env },
      detached: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const chunks: Buffer[] = [];
    let bytes = 0;
    let stopped: string | undefined;
    let killTimer: NodeJS.Timeout | undefined;
    const killGroup = (sig: NodeJS.Signals) => {
      if (!child.pid) return;
      try { process.kill(-child.pid, sig); }
      catch (error) { if ((error as NodeJS.ErrnoException).code !== "ESRCH") child.kill(sig); }
    };
    const stop = (reason: string) => {
      if (stopped) return;
      stopped = reason;
      killGroup("SIGTERM");
      killTimer = setTimeout(() => killGroup("SIGKILL"), 500);
    };
    const abort = () => stop("cancelled");
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
    const timer = timeout > 0 ? setTimeout(() => stop("timed out"), timeout * 1000) : undefined;
    const receive = (chunk: Buffer) => {
      bytes += chunk.length;
      if (bytes > MAX_OUTPUT) { stop("output exceeded 8 MiB; output withheld"); return; }
      chunks.push(chunk);
    };
    child.stdout.on("data", receive);
    child.stderr.on("data", receive);
    const cleanup = () => {
      clearTimeout(timer);
      clearTimeout(killTimer);
      if (stopped) killGroup("SIGKILL");
      signal?.removeEventListener("abort", abort);
    };
    child.once("error", () => { cleanup(); reject(new Error("secret: unable to start credential command")); });
    child.once("close", code => {
      cleanup();
      // Do not expose a prefix cut through a credential at an output-limit boundary.
      resolveResult({ output: bytes > MAX_OUTPUT ? "" : Buffer.concat(chunks).toString("utf8"), exitCode: code, stopped });
    });
  return promise;
}

export function registerSecureBash(pi: ExtensionAPI, options: SecureBashOptions): void {
  const native = pi.getAllTools().find(tool => tool.name === "bash");
  if (!native || native.sourceInfo.source !== "builtin") {
    throw new Error("secret requires the native OMP bash tool; another override is not supported");
  }
  pi.registerTool({
    name: "bash", label: "Bash", parameters: native.parameters,
    description: native.description + "\nWith {{sec:NAME}} references: runs in an isolated, non-interactive Bash child; no persistent shell state, PTY, background jobs or services. Output is returned only after redaction.",
    approval: "exec", loadMode: "essential",
    async execute(_id, params, signal, onUpdate, ctx) {
      const input = params as Record<string, unknown>;
      const command = typeof input.command === "string" ? input.command : "";
      const refs = findRefs(command);
      if (!refs.length) {
        if (!ctx.invokeTool) throw new Error("secret: native bash delegation unavailable");
        return ctx.invokeTool(input, { signal, onUpdate });
      }
      if (ctx.agent?.kind === "sub") throw new Error("Session credentials are available only to the main agent");
      if (!isEnabled()) throw new Error("secret is disabled; run /sec on and add the credential again");
      if (input.pty || input.async || input.name || input.ready) {
        throw new Error("secret: credential commands require foreground, non-PTY execution; omit pty/async/name/ready");
      }
      const v = options.vault();
      const expansion = injectBashCommand(command, v);
      if (expansion.block) throw new Error(expansion.block.reason);
      const cwd = typeof input.cwd === "string" ? resolve(ctx.cwd, input.cwd) : ctx.cwd;
      const timeout = typeof input.timeout === "number" ? input.timeout : 300;
      // Snapshot before execution: clearing the vault while the child runs must not expose its output.
      const values = v.values();
      const result = await runSecretCommand(expansion.command, cwd, expansion.env, timeout, signal);
      const output = redactCredentialOutput(result.output, values);
      const suffix = result.stopped ? `\nCredential command ${result.stopped}.` : `\nExit code: ${result.exitCode}`;
      return {
        content: [{ type: "text", text: output + suffix }],
        details: { exitCode: result.exitCode, stopped: result.stopped },
        isError: result.exitCode !== 0 || !!result.stopped,
      };
    },
  } satisfies ToolDefinition);
}
