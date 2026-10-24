import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { lookup } from "@oh-my-pi/pi-coding-agent/config/registry";
import { Container, fieldComposerStyle, theme, truncateToWidth, visibleWidth } from "@oh-my-pi/pi-tui";
import { QueuedMessagesBand } from "@oh-my-pi/pi-tui/prompt/queued-messages";

function sessionTitle(name: string | undefined): string {
  if (!name) return "";
  return name.replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, "").replace(/[\u0000-\u001f\u007f]/g, "").trim();
}

function renderSessionTitle(
  chrome: { width: number; paddingX: number; accentColor: (text: string) => string },
  name: string | undefined,
): string {
  const title = sessionTitle(name);
  if (!title || chrome.width <= 0) return "";
  const margin = Math.min(chrome.paddingX, chrome.width);
  const text = truncateToWidth(title, chrome.width - margin);
  const gap = chrome.width - margin - visibleWidth(text);
  return `${" ".repeat(Math.max(0, gap))}${chrome.accentColor(text)}`;
}

const TITLE_AND_BORDER = 2;

// shortcut: omp 18.11 editor max-height (`eve`); upgrade when that cap changes.
function editorMaxHeight(terminalRows: number): number {
  const rows = Number.isFinite(terminalRows) && terminalRows > 0 ? terminalRows : 24;
  const preferred = Math.max(6, Math.min(18, rows - 12));
  return Math.max(3, Math.min(preferred, rows - 4));
}

function shadedPadding(): number {
  return editorMaxHeight(process.stdout.rows || 24) >= TITLE_AND_BORDER + 3 ? 1 : 0;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = String(seconds % 60).padStart(2, "0");
  if (minutes < 60) return `${minutes}m ${remainder}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m ${remainder}s`;
}

function renderQueuedMessages(rows: readonly string[], width: number): readonly string[] {
  return rows.map(line => {
    const text = line.replace(/\u001b\[[0-9;:]*m/g, "");
    const heading = text.match(/^\s*(Steering|After yield)(.*)$/);
    if (heading) {
      const label = heading[1] === "Steering" ? "STEERING" : "FOLLOW-UP";
      return theme.bold(theme.fg("accent", truncateToWidth(` ▌ ${label}${heading[2]}`, width)));
    }
    return /^\s*\d+\./.test(text) ? theme.fg("text", text) : line;
  });
}

export default async function (pi: ExtensionAPI) {
  const hideToolActivity = lookup("display.hideToolActivity")!;
  let restoreQueueUI: (() => void) | undefined;
  let queueFailed = false;
  let uiContext: ExtensionContext | undefined;
  function displayFailure(name: string, error: unknown, ctx = uiContext) {
    console.error(`[claude-context] ${name} disabled after an extension error`, error);
    queueMicrotask(() => {
      try { ctx?.ui.notify(`${name} disabled after an error; native input and queue remain active.`, "warning"); }
      catch (notificationError) { console.error("[claude-context] could not display failure notice", notificationError); }
    });
  }
  function failQueue(error: unknown) {
    if (queueFailed) return;
    queueFailed = true;
    restoreQueueUI?.();
    displayFailure("Queue enhancements", error);
  }
  for (const event of ["session_start", "session_switch", "agent_start"] as const) {
    pi.on(event as "session_start", (_event, ctx) => {
      uiContext = ctx;
      if (queueFailed || !ctx.hasUI || (event === "agent_start" && restoreQueueUI)) return;
      restoreQueueUI?.();
      // The host exposes TUI through component factories; leave no second queue widget mounted.
      ctx.ui.setWidget("pending-messages", tui => {
        const restores: Array<() => void> = [];
        const visibilityRoots = new WeakSet<object>();
        let ownsVisibilityOverride = false;
        const adapt = () => {
          if (queueFailed) return;
          try {
            let changed = false;
            // shortcut: OMP 18.12 root queue container; replace when the host exposes a queue renderer.
            for (const root of tui.children) {
              // shortcut: OMP 18.12 hotkeys write below overlays; remove when visibility uses runtime settings.
              if ("setToolActivityVisible" in root && typeof root.setToolActivityVisible === "function"
                && !visibilityRoots.has(root)) {
                visibilityRoots.add(root);
                const owner = root as typeof root & { setToolActivityVisible(visible: boolean): void };
                const originalVisibility = owner.setToolActivityVisible;
                let pendingHidden = hideToolActivity.get(pi.pi.settings) as boolean;
                const setVisibility = (visible: boolean) => {
                  originalVisibility.call(owner, visible);
                  if (queueFailed) return;
                  try {
                    pendingHidden = !visible;
                    if (pendingHidden === hideToolActivity.get(pi.pi.settings)) return;
                    queueMicrotask(() => {
                      if (queueFailed) return;
                      try {
                        if (owner.setToolActivityVisible !== setVisibility
                          || pendingHidden === hideToolActivity.get(pi.pi.settings)) return;
                        ownsVisibilityOverride = true;
                        hideToolActivity.override(pi.pi.settings, pendingHidden);
                      } catch (error) { failQueue(error); }
                    });
                  } catch (error) { failQueue(error); }
                };
                restores.push(() => {
                  if (owner.setToolActivityVisible === setVisibility) owner.setToolActivityVisible = originalVisibility;
                });
                owner.setToolActivityVisible = setVisibility;
              }
              if (!(root instanceof Container) || root.render !== Container.prototype.render
                || !root.children.some(child => child instanceof QueuedMessagesBand)) continue;
              const original = root.render;
              const render = (width: number): readonly string[] => {
                const nativeRows = root.children.map(child => child.render(width));
                if (queueFailed) return nativeRows.flat();
                try {
                  return nativeRows.flatMap((rows, index) => root.children[index] instanceof QueuedMessagesBand
                    ? renderQueuedMessages(rows, width) : rows);
                } catch (error) {
                  failQueue(error);
                  return nativeRows.flat();
                }
              };
              restores.push(() => { if (root.render === render) root.render = original; });
              root.render = render;
              changed = true;
            }
            if (changed) tui.requestRender();
          } catch (error) { failQueue(error); }
        };
        let unsubscribe = () => {};
        let restored = false;
        restoreQueueUI = () => {
          if (restored) return;
          restored = true;
          for (const restore of [unsubscribe, ...restores.reverse()]) {
            try { restore(); }
            catch (error) { console.error("[claude-context] queue rollback failed", error); }
          }
          if (ownsVisibilityOverride) {
            try { hideToolActivity.clearOverride(pi.pi.settings); }
            catch (error) { console.error("[claude-context] visibility rollback failed", error); }
          }
        };
        try { unsubscribe = tui.addPaintListener(adapt); }
        catch (error) { failQueue(error); }
        adapt();
        return { render: () => [], invalidate() {} };
      });
      ctx.ui.setWidget("pending-messages", undefined);
    });
  }
  pi.on("session_shutdown", () => {
    restoreQueueUI?.();
    restoreQueueUI = undefined;
  });

  let inputRows = 0;
  let composerFailed = false;
  function failComposer(error: unknown) {
    if (composerFailed) return;
    composerFailed = true;
    displayFailure("Composer styling", error);
  }
  let startedAt: number | undefined;
  let workingResumeAt = 0;
  let workingIntent: string | undefined;
  let cancelWorking: (() => void) | undefined;
  pi.on("agent_start", (_event, ctx) => {
    cancelWorking?.();
    startedAt = performance.now();
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
  });

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
  pi.on("message_update", ({ message, assistantMessageEvent }, ctx) => {
    if (message.role !== "assistant" || !assistantMessageEvent.type.startsWith("toolcall_")) return;
    for (let index = message.content.length - 1; index >= 0; index--) {
      const block = message.content[index];
      if (block.type !== "toolCall") continue;
      const args = block.arguments;
      if (args && typeof args === "object" && noteWorkingIntent(args.i, ctx)) break;
    }
  });
  pi.on("tool_execution_start", ({ intent }, ctx) => { noteWorkingIntent(intent, ctx); });

  pi.on("agent_end", (_event, ctx) => {
    cancelWorking?.();
    cancelWorking = undefined;
    ctx.ui.setWorkingMessage(undefined);
    if (startedAt === undefined) return;
    const seconds = Math.max(1, Math.round((performance.now() - startedAt) / 1000));
    startedAt = undefined;
    const duration = formatDuration(seconds);
    const completedAt = new Date().toTimeString().slice(0, 5);
    ctx.ui.setWidget("turn-time", [ctx.ui.theme.fg("dim", `Worked for ${duration} • ${completedAt}`)]);
  });
  pi.on("session_switch", (_event, ctx) => {
    cancelWorking?.();
    cancelWorking = undefined;
    ctx.ui.setWorkingMessage(undefined);
    startedAt = undefined;
    ctx.ui.setWidget("turn-time", undefined);
  });

  pi.registerComposerShape({
    label: "Shaded Input + OMP Dock",
    description: "Shaded input with a blank row above and below the text, and the native OMP status below",
    style: {
      ...fieldComposerStyle,
      id: "dotfiles/claude-context",
      filledSurface: true,
      get verticalChrome() {
        // shortcut: OMP 18.12 budgets arbitrary rows; remove this cast when custom chrome counts are typed.
        return (TITLE_AND_BORDER + shadedPadding() * 2) as typeof fieldComposerStyle.verticalChrome;
      },
      statusAttachment: "top-border",
      bottomBar: "none",
      bottomBarGap: false,
      defaultPaddingX() {
        return 2;
      },
      sideChromeWidth(paddingX) {
        return paddingX;
      },
      renderTop(chrome) {
        inputRows = 0;
        if (composerFailed) return undefined;
        try { return renderSessionTitle(chrome, pi.getSessionName()); }
        catch (error) { failComposer(error); return undefined; }
      },
      renderRow(row) {
        const content = " ".repeat(row.paddingX) + row.gutter + row.text;
        const plain = row.imeSafeCursorTail ? content
          : content + row.pad + " ".repeat(Math.max(0, row.paddingX - row.cursorOverflow));
        if (composerFailed) return [plain];
        try {
          const line = theme.bgFill("statusLineBg", plain);
          const padding = shadedPadding();
          const empty = theme.bgFill("statusLineBg", " ".repeat(row.width));
          const lines = [];
          if (inputRows === 0 && padding > 0) lines.push(empty);
          lines.push(line);
          inputRows++;
          if (row.isLastRow) {
            if (padding > 0) {
              lines.push(empty);
            } else {
              const terminalRows = process.stdout.rows || 24;
              const minimumRows = Math.min(3, Math.max(1, terminalRows - 2));
              if (inputRows < minimumRows) {
                if (inputRows === 1 && minimumRows === 3) {
                  lines.unshift(empty);
                  inputRows++;
                }
                while (inputRows < minimumRows) {
                  lines.push(empty);
                  inputRows++;
                }
              }
            }
          }
          return lines;
        } catch (error) { failComposer(error); return [plain]; }
      },
      renderBottom(chrome) {
        if (composerFailed || (process.stdout.rows || 24) < 2) return undefined;
        try {
          const border = chrome.topBorder;
          if (!border) return chrome.borderColor(chrome.box.horizontal.repeat(chrome.width));
          return border.content
            + chrome.borderColor(chrome.box.horizontal.repeat(Math.max(0, chrome.width - border.width)));
        } catch (error) { failComposer(error); return undefined; }
      },
    },
  });
}
