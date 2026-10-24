import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { lookup } from "@oh-my-pi/pi-coding-agent/config/registry";
import { Container, theme, truncateToWidth } from "@oh-my-pi/pi-tui";
import { QueuedMessagesBand } from "@oh-my-pi/pi-tui/prompt/queued-messages";

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

export function createQueueEnhancements(pi: ExtensionAPI, displayFailure: (name: string, error: unknown) => void) {
  const hideToolActivity = lookup("display.hideToolActivity")!;
  let restoreQueueUI: (() => void) | undefined;
  let queueFailed = false;
  function failQueue(error: unknown) {
    if (queueFailed) return;
    queueFailed = true;
    restoreQueueUI?.();
    displayFailure("Queue enhancements", error);
  }

  return {
    session(event: "session_start" | "session_switch" | "agent_start", ctx: ExtensionContext) {
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
    },
    shutdown() {
      restoreQueueUI?.();
      restoreQueueUI = undefined;
    },
  };
}
