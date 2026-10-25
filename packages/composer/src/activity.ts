import type { AgentEndEvent, ExtensionContext, InputEvent, MessageUpdateEvent, ToolExecutionStartEvent } from "@oh-my-pi/pi-coding-agent";

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = String(seconds % 60).padStart(2, "0");
  if (minutes < 60) return `${minutes}m ${remainder}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m ${remainder}s`;
}

export function createActivity() {
  let startedAt: number | undefined;
  let continuing = false;
  let workingResumeAt = 0;
  let workingIntent: string | undefined;
  let cancelWorking: (() => void) | undefined;

  // Match native Working-row intent normalization and deduplication.
  const noteWorkingIntent = (intent: unknown, ctx: ExtensionContext): boolean => {
    if (typeof intent !== "string") return false;
    const text = intent.trim().replace(/\s*\.+$/, "").trim();
    if (!text) return false;
    if (startedAt !== undefined && text !== workingIntent) {
      workingIntent = text;
      workingResumeAt = performance.now() + 30000;
      // Native intent deduplication may leave our last timer label on screen.
      ctx.ui.setWorkingMessage(text);
    }
    return true;
  };

  return {
    start(ctx: ExtensionContext) {
      cancelWorking?.();
      if (!continuing) startedAt = performance.now();
      continuing = false;
      workingResumeAt = 0;
      workingIntent = undefined;
      ctx.ui.setWidget("turn-time", undefined);
      ctx.ui.setWorkingMessage(undefined);
      const update = () => {
        if (startedAt === undefined) return;
        const now = performance.now();
        const seconds = Math.max(0, Math.floor((now - startedAt) / 1000));
        if (seconds < 60 || now < workingResumeAt) return;
        ctx.ui.setWorkingMessage(`Working · ${formatDuration(seconds)}`);
      };
      const timer = ctx.setInterval(update, 1000);
      cancelWorking = () => ctx.clearTimer(timer);
    },
    input(event: InputEvent, ctx: ExtensionContext) {
      if (event.source !== "extension" && ctx.isIdle() && !event.text.trimStart().startsWith("/")) {
        continuing = false;
      }
    },
    messageUpdate({ message, assistantMessageEvent }: MessageUpdateEvent, ctx: ExtensionContext) {
      if (message.role !== "assistant" || !assistantMessageEvent.type.startsWith("toolcall_")) return;
      for (let index = message.content.length - 1; index >= 0; index--) {
        const block = message.content[index];
        if (block.type !== "toolCall") continue;
        const args = block.arguments;
        if (args && typeof args === "object" && noteWorkingIntent(args.i, ctx)) break;
      }
    },
    toolExecutionStart({ intent }: ToolExecutionStartEvent, ctx: ExtensionContext) {
      noteWorkingIntent(intent, ctx);
    },
    end(event: AgentEndEvent, ctx: ExtensionContext) {
      continuing = event.willContinue === true;
      if (continuing) return;
      cancelWorking?.();
      cancelWorking = undefined;
      ctx.ui.setWorkingMessage(undefined);
      if (startedAt === undefined) return;
      const seconds = Math.max(1, Math.round((performance.now() - startedAt) / 1000));
      startedAt = undefined;
      const duration = formatDuration(seconds);
      const completedAt = new Date().toTimeString().slice(0, 5);
      ctx.ui.setWidget("turn-time", [ctx.ui.theme.fg("dim", `Worked for ${duration} • ${completedAt}`)]);
    },
    sessionSwitch(ctx: ExtensionContext) {
      cancelWorking?.();
      cancelWorking = undefined;
      ctx.ui.setWorkingMessage(undefined);
      startedAt = undefined;
      continuing = false;
      ctx.ui.setWidget("turn-time", undefined);
    },
  };
}
