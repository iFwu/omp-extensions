import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { filterChildShellEnv } from "@oh-my-pi/pi-utils";
import type { Vault } from "../vault.ts";
import { injectBashCommand, scrubDeepFailClosed } from "../glue.ts";
import { findRefs } from "../substitute.ts";
import { scrubText } from "../scrub.ts";
import { isEnabled } from "../state.ts";

export interface SecureBashOptions {
  vault: () => Vault;
}

const MAX_OUTPUT = 8 * 1024 * 1024;

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
    child.once("error", () => { cleanup(); reject(new Error("pi-secret: unable to start credential command")); });
    child.once("close", code => {
      cleanup();
      // Do not expose a prefix cut through a credential at an output-limit boundary.
      resolveResult({ output: bytes > MAX_OUTPUT ? "" : Buffer.concat(chunks).toString("utf8"), exitCode: code, stopped });
    });
  return promise;
}

export function registerSecureBash(pi: ExtensionAPI, _cwd: string, options: SecureBashOptions): void {
  const native = pi.getAllTools().find(tool => tool.name === "bash");
  if (!native || native.sourceInfo.source !== "builtin") {
    throw new Error("pi-secret requires the native OMP bash tool; another override is not supported");
  }
  pi.registerTool({
    name: "bash", label: "Bash", parameters: native.parameters,
    description: native.description + "\nWith {{sec:NAME}} references: runs in an isolated, non-interactive Bash child; no persistent shell state, PTY, background jobs or services. Output is returned only after redaction.",
    approval: "exec", loadMode: "essential",
    async execute(_id, params, signal, onUpdate, ctx) {
      const input = params as Record<string, unknown>;
      const command = typeof input.command === "string" ? input.command : "";
      const v = options.vault();
      const refs = findRefs(command);
      if (!refs.length) {
        if (!ctx.invokeTool) throw new Error("pi-secret: native bash delegation unavailable");
        const result = await ctx.invokeTool(input, {
          signal,
          onUpdate: onUpdate ? partial => {
            // Suppress streaming while credentials exist: chunk boundaries can split a value.
            if (v.size() === 0) onUpdate(partial);
          } : undefined,
        });
        return scrubDeepFailClosed(result, v, { shapes: true }).value;
      }
      if (ctx.agent?.kind === "sub") throw new Error("Session credentials are available only to the main agent");
      if (!isEnabled()) throw new Error("pi-secret is disabled; run /sec on and add the credential again");
      if (input.pty || input.async || input.name || input.ready) {
        throw new Error("pi-secret: credential commands require foreground, non-PTY execution; omit pty/async/name/ready");
      }
      const expansion = injectBashCommand(command, v);
      if (expansion.block) throw new Error(expansion.block.reason);
      const cwd = typeof input.cwd === "string" ? resolve(ctx.cwd, input.cwd) : ctx.cwd;
      const timeout = typeof input.timeout === "number" ? input.timeout : 300;
      const result = await runSecretCommand(expansion.command, cwd, expansion.env, timeout, signal);
      const output = scrubText(result.output, v, { shapes: true }).text;
      const suffix = result.stopped ? `\nCredential command ${result.stopped}.` : `\nExit code: ${result.exitCode}`;
      return {
        content: [{ type: "text", text: output + suffix }],
        details: { exitCode: result.exitCode, stopped: result.stopped },
        isError: result.exitCode !== 0 || !!result.stopped,
      };
    },
  } satisfies ToolDefinition);
}

export function bashIsOwnedByPiSecret(pi: ExtensionAPI): boolean {
  const effective = pi.getAllTools().find(tool => tool.name === "bash");
  return effective?.sourceInfo.path === fileURLToPath(new URL("../index.ts", import.meta.url));
}
