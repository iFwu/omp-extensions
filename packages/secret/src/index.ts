import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { getPluginSettings } from "@oh-my-pi/pi-coding-agent/extensibility/plugins";
import { activeVault, activeScopeKey, dropSessionVault, setActiveScopeKey } from "./vault.ts";
import { registerSecureBash } from "./tools/bash.ts";
import { createSecretTool } from "./tools/secret.ts";
import { createSecAutocompleteProvider } from "./autocomplete.ts";
import { isEnabled, setEnabled } from "./state.ts";
import { registerCommands } from "./commands.ts";
import { withSecretPrompt } from "./prompt.ts";

function sessionScope(ctx: ExtensionContext): string {
  return ctx.sessionManager.getSessionFile() ?? `ephemeral:${ctx.sessionManager.getSessionId()}`;
}

export default function secretExtension(pi: ExtensionAPI): void {
  pi.registerFlag("secret", { type: "boolean", description: "Enable session-local masked credential input" });
  let initialized = false;
  pi.on("session_start", async (_event, ctx) => {
    if (initialized || ctx.agent.kind !== "main") return;
    initialized = true;
    const [standalone, suite] = await Promise.all([
      getPluginSettings("@ifwu/omp-secret", ctx.cwd),
      getPluginSettings("@ifwu/omp-extensions", ctx.cwd),
    ]);
    if ((pi.getFlag("secret") ?? standalone.enabled ?? suite.secret) !== true) return;
    const bash = pi.getAllTools().find(tool => tool.name === "bash");
    if (!bash || bash.sourceInfo.path !== "<builtin:bash>" || !pi.getActiveTools().includes("bash")) {
      if (ctx.hasUI) ctx.ui.notify("Session credentials require the native Bash tool; credential support remains disabled.", "warning");
      return;
    }
    setActiveScopeKey(sessionScope(ctx));
    setEnabled(true);
    pi.registerTool(createSecretTool(activeVault));
    registerSecureBash(pi, { vault: activeVault });
    registerCommands(pi);
    if (ctx.hasUI) {
      ctx.ui.addAutocompleteProvider(current => createSecAutocompleteProvider(activeVault, current));
      ctx.ui.setStatus("secret", `sec: ${activeVault().size()} active`);
    }
  });

  const resetSession = (_event: unknown, ctx: ExtensionContext) => {
    if (ctx.agent.kind !== "main" || !activeScopeKey()) return;
    dropSessionVault(activeScopeKey()!);
    setActiveScopeKey(sessionScope(ctx));
    setEnabled(true);
    if (ctx.hasUI) ctx.ui.setStatus("secret", "sec: 0 active");
  };
  pi.on("session_switch", resetSession);
  pi.on("session_branch", resetSession);
  pi.on("session_shutdown", async (_event, ctx) => {
    if (ctx.agent.kind !== "main") return;
    const previous = activeScopeKey();
    if (previous) dropSessionVault(previous);
    setActiveScopeKey(undefined);
    setEnabled(false);
    if (ctx.hasUI) ctx.ui.setStatus("secret", undefined);
  });
  pi.on("before_agent_start", async (event, ctx) => {
    if (!activeScopeKey() || !isEnabled() || ctx.agent.kind !== "main") return;
    return { systemPrompt: withSecretPrompt(event.systemPrompt) };
  });
}
