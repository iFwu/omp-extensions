import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { createActivity } from "./activity";
import { registerComposer } from "./composer";
import { createQueueEnhancements } from "./queue";

export default async function (pi: ExtensionAPI) {
  let uiContext: ExtensionContext | undefined;
  function displayFailure(name: string, error: unknown, ctx = uiContext) {
    console.error(`[claude-context] ${name} disabled after an extension error`, error);
    queueMicrotask(() => {
      try { ctx?.ui.notify(`${name} disabled after an error; native input and queue remain active.`, "warning"); }
      catch (notificationError) { console.error("[claude-context] could not display failure notice", notificationError); }
    });
  }

  const queue = createQueueEnhancements(pi, displayFailure);
  for (const event of ["session_start", "session_switch", "agent_start"] as const) {
    pi.on(event as "session_start", (_event, ctx) => {
      uiContext = ctx;
      queue.session(event, ctx);
    });
  }
  pi.on("session_shutdown", () => { queue.shutdown(); });

  const activity = createActivity();
  pi.on("agent_start", (_event, ctx) => { activity.start(ctx); });
  pi.on("message_update", activity.messageUpdate);
  pi.on("tool_execution_start", activity.toolExecutionStart);
  pi.on("agent_end", (_event, ctx) => { activity.end(ctx); });
  pi.on("session_switch", (_event, ctx) => { activity.sessionSwitch(ctx); });

  registerComposer(pi, displayFailure);
}
