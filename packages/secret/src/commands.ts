import type { ExtensionAPI, ExtensionCommandContext } from "@oh-my-pi/pi-coding-agent";
import { activeScopeGeneration, activeScopeKey, activeVault, type PublicEntry, type Vault } from "./vault.ts";
import { isValidName } from "./refs.ts";
import { promptMaskedSecret } from "./masked-input.ts";
import { enabledGeneration, isEnabled, setEnabled } from "./state.ts";

const SEC_USAGE = "usage: /sec [add <name> | list | remove <name> | rename <old> <new> | clear | off | on]";
const VERBS = ["add ", "list", "remove ", "rename ", "clear", "off", "on"];

export function registerCommands(pi: ExtensionAPI): void {
  pi.registerCommand("sec", {
    description: "Manage explicit masked session secrets: add | list | remove | rename | clear | off | on",
    getArgumentCompletions: (prefix: string) => {
      const items = VERBS.filter(verb => verb.startsWith(prefix.trim()))
        .map(value => ({ value, label: `/sec ${value.trim()}` }));
      return items.length ? items : null;
    },
    handler: async (args, ctx) => {
      await runSecCommand(args ?? "", activeVault(), ctx);
    },
  });
}

export async function runSecCommand(input: string, vault: Vault, ctx: ExtensionCommandContext): Promise<void> {
  const [verb = "", ...args] = input.trim().split(/\s+/);
  const names = args.map(arg => arg.replace(/^sec:/, ""));
  const name = names[0] ?? "";
  const expected = verb === "add" || verb === "remove" ? 1 : verb === "rename" ? 2 : 0;
  if (args.length !== expected) {
    ctx.ui.notify(SEC_USAGE, "warning");
    return;
  }
  switch (verb) {
    case "":
      ctx.ui.notify(`secret is ${isEnabled() ? "ON" : "OFF"} for this session\n${formatSecretList(vault.entries())}\n${SEC_USAGE}`, "info");
      return;
    case "help":
      ctx.ui.notify(SEC_USAGE, "info");
      return;
    case "list":
      ctx.ui.notify(formatSecretList(vault.entries()), "info");
      return;
    case "add": {
      if (!isValidName(name)) {
        ctx.ui.notify("invalid name (want /^[a-z][a-z0-9_-]{0,63}$/)", "warning");
        return;
      }
      if (!isEnabled()) {
        ctx.ui.notify("secret is off — use /sec on before adding a value", "warning");
        return;
      }
      if (!ctx.hasUI || ctx.mode !== "tui") {
        ctx.ui.notify("Masked input requires an interactive OMP terminal; never supply the value in chat or arguments", "warning");
        return;
      }
      const scope = activeScopeGeneration();
      const enabled = enabledGeneration();
      const generation = vault.generation();
      let value: string | undefined;
      try {
        value = await promptMaskedSecret(ctx, `Value for sec:${name} — paste is fine, it is never echoed`);
      } catch {
        ctx.ui.notify("Masked input unavailable — nothing was stored", "warning");
        return;
      }
      if (value === undefined || !isEnabled() || enabledGeneration() !== enabled ||
          activeScopeGeneration() !== scope || vault.generation() !== generation ||
          (activeScopeKey() !== undefined && activeVault() !== vault)) {
        ctx.ui.notify("cancelled — nothing was stored", "info");
        return;
      }
      try {
        vault.add(name, value, "prompt");
        ctx.ui.notify(`stored {{sec:${name}}} · this session only`, "info");
      } catch {
        ctx.ui.notify("Secret not stored: input requires at least 8 characters, no NUL, at most 1 MiB, and a distinct shell-variable name", "error");
      }
      return;
    }
    case "remove": {
      if (!isValidName(name)) {
        ctx.ui.notify("invalid secret name", "warning");
        return;
      }
      const removed = vault.remove(name);
      ctx.ui.notify(removed ? `forgot sec:${name}` : `sec:${name} was not in the vault`, removed ? "info" : "warning");
      return;
    }
    case "rename": {
      const target = names[1]!;
      if (!isValidName(name) || !isValidName(target)) {
        ctx.ui.notify("invalid secret name", "warning");
        return;
      }
      try {
        const renamed = vault.rename(name, target);
        ctx.ui.notify(renamed ? `sec:${name} is now sec:${target}` : "could not rename: name is unknown or already taken", renamed ? "info" : "warning");
      } catch {
        ctx.ui.notify("could not rename: shell-variable name collision", "warning");
      }
      return;
    }
    case "clear":
      ctx.ui.notify(`cleared ${vault.clear()} secret(s) from this session`, "info");
      return;
    case "off":
      setEnabled(false);
      vault.clear();
      ctx.ui.notify("secret disabled for this session — values cleared; use /sec on and add them again when needed", "info");
      return;
    case "on":
      setEnabled(true);
      ctx.ui.notify("secret enabled for this session", "info");
      return;
    default:
      ctx.ui.notify(SEC_USAGE, "warning");
  }
}

export function formatSecretList(entries: readonly PublicEntry[]): string {
  return entries.length ? entries.map(entry => `{{sec:${entry.name}}}`).join("\n") : "no secrets in this session";
}
