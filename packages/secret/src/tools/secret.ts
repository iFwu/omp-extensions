import type { ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { promptMaskedSecret } from "../masked-input.ts";
import { isValidName } from "../refs.ts";
import { enabledGeneration, isEnabled } from "../state.ts";
import { activeScopeGeneration, type Vault } from "../vault.ts";

interface SecretReply {
  status: "listed" | "available" | "stored" | "cancelled" | "disabled" | "unavailable" | "busy" | "invalid";
  ref?: string;
  refs?: string[];
  error?: string;
}

function reply(data: SecretReply) {
  return { content: [{ type: "text" as const, text: JSON.stringify(data) }], details: data };
}

export function createSecretTool(getVault: () => Vault): ToolDefinition {
  let requesting = false;
  return {
    name: "secret",
    label: "secret",
    description: "Request masked session-local credential input or list references; never returns values. Use {{sec:NAME}} in foreground bash only. Do not retry a cancelled request without user approval.",
    loadMode: "discoverable",
    approval: "read",
    parameters: Type.Object({
      action: Type.Union([Type.Literal("request"), Type.Literal("list")]),
      name: Type.Optional(Type.String({ pattern: "^[A-Za-z_][A-Za-z0-9_-]{0,63}$" })),
      reason: Type.Optional(Type.String({ minLength: 1, maxLength: 240 })),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      const { action, name, reason } = params as { action: string; name?: string; reason?: string };
      if (ctx.agent?.kind === "sub") return reply({ status: "unavailable", error: "Session credentials are available only to the main agent." });
      if (!isEnabled()) return reply({ status: "disabled" });
      let vault: Vault;
      try {
        vault = getVault();
      } catch {
        return reply({ status: "unavailable", error: "No active session is available." });
      }
      if (action === "list") return reply({ status: "listed", refs: vault.names().map(key => `{{sec:${key}}}`) });
      if (action !== "request" || !name || !isValidName(name) || !reason?.trim() || reason.length > 240 || /[\x00-\x1f\x7f]/.test(reason)) {
        return reply({ status: "invalid", error: "Request requires a valid name and a short, single-line reason." });
      }
      const ref = `{{sec:${name}}}`;
      if (vault.has(name)) return reply({ status: "available", ref });
      if (signal?.aborted) return reply({ status: "cancelled" });
      if (!ctx.hasUI || ctx.mode !== "tui") return reply({ status: "unavailable", error: "An interactive OMP terminal is required; never supply the value in chat or arguments." });
      if (requesting) return reply({ status: "busy" });
      requesting = true;
      const scope = activeScopeGeneration();
      const enabled = enabledGeneration();
      const generation = vault.generation();
      try {
        let value: string | undefined;
        try {
          value = await promptMaskedSecret(ctx, `Credential: ${name}\nPurpose: ${reason}`, signal);
        } catch {
          return reply({ status: signal?.aborted ? "cancelled" : "unavailable" });
        }
        if (value === undefined || signal?.aborted || !isEnabled() || enabledGeneration() !== enabled ||
            activeScopeGeneration() !== scope || vault.generation() !== generation) {
          return reply({ status: "cancelled" });
        }
        try {
          if (getVault() !== vault) return reply({ status: "cancelled" });
        } catch {
          return reply({ status: "cancelled" });
        }
        if (vault.has(name)) return reply({ status: "available", ref });
        try {
          vault.add(name, value, "prompt");
        } catch {
          return reply({ status: "invalid", error: "Credential not stored: use at least 8 characters, no NUL, and at most 1 MiB." });
        }
        return reply({ status: "stored", ref });
      } finally {
        requesting = false;
      }
    },
  };
}
