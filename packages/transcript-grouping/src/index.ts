import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import type { AssistantMessage } from "@oh-my-pi/pi-ai";
import { Markdown, type Component, type TUI } from "@oh-my-pi/pi-tui";
import { AssistantMessageComponent } from "@oh-my-pi/pi-tui/chat/assistant-message";
import { FigureMarkdown } from "@oh-my-pi/pi-tui/chat/figure-markdown";
import { TranscriptContainer } from "@oh-my-pi/pi-tui/chrome/transcript-container";
import { renderGroupingLabel, type GroupingMarker } from "./render";
import { GroupingState } from "./state";

export default function (pi: ExtensionAPI, now?: () => number) {
  let state = new GroupingState(now);
  let enabled = true;
  let tui: TUI | undefined;
  let context: ExtensionContext;
  let dispose: (() => void) | undefined;
  let failed = false;

  function fail(error: unknown) {
    if (failed) return;
    failed = true;
    enabled = false;
    dispose?.();
    console.error("[transcript-grouping] disabled after an extension error", error);
    queueMicrotask(() => {
      try {
        context.ui.notify("Grouping disabled after an error; native transcript remains active. Restart OMP to retry.", "warning");
      } catch (notificationError) {
        console.error("[transcript-grouping] could not display failure notice", notificationError);
      }
    });
  }

  function guard(action: () => void) {
    if (failed) return;
    try { action(); } catch (error) { fail(error); }
  }

  function install(host: TUI) {
    const roots = new WeakSet<TranscriptContainer>();
    const components = new WeakSet<AssistantMessageComponent>();
    const restores: (() => void)[] = [];

    function attach(component: AssistantMessageComponent, root: TranscriptContainer) {
      if (components.has(component)) return;
      components.add(component);
      const update = component.updateContent;
      const render = component.render;
      const describe = component.describe;
      const release = component.releaseRenderCaches;
      const finalized = component.isTranscriptBlockFinalized;
      let message: AssistantMessage | undefined;
      let frozen: Map<number, GroupingMarker> | undefined;
      let displayed = new Map<number, GroupingMarker>();
      const blockMode = component.transcriptBlockMode;
      const mutableBlock = component as unknown as { transcriptBlockMode: "appendOnly" | "mutable" };

      const updateContent: typeof update = function (this: AssistantMessageComponent, value, options) {
        message = value;
        return update.call(this, value, options);
      };
      // shortcut: OMP 18.12 terminal body children; replace when a display-only renderer is available.
      const decorations = () => {
        if (frozen) return frozen;
        const result = new Map<number, GroupingMarker>();
        if (!enabled || !message) return result;
        message.content.forEach((block, index) => {
          if (block.type !== "text") return;
          const marker = state.find(message!, index)?.marker;
          if (marker) result.set(index, { ...marker });
        });
        return result;
      };
      const decoratedRender: typeof render = function (this: AssistantMessageComponent, width) {
        if (failed) return render.call(this, width);
        try {
          displayed = decorations();
        } catch (error) {
          fail(error);
          return render.call(this, width);
        }
        if (!displayed.size || width < 12) return render.call(this, width);
        const rows = render.call(this, width);
        try {
          const body = this.children[0];
          if (!body || !("children" in body) || !Array.isArray(body.children)) {
            throw new Error("Grouping cannot locate the native assistant body");
          }
          const children = body.children as Component[];
          const textIndices: number[] = [];
          const visibleIndices: number[] = [];
          for (const node of describe.call(this).c ?? []) {
            const match = /^([tk])(\d+)(?:\.|$)/.exec("key" in node && typeof node.key === "string" ? node.key : "");
            if (!match) continue;
            const index = Number(match[2]);
            if (visibleIndices.at(-1) !== index) visibleIndices.push(index);
            if (match[1] === "t" && textIndices.at(-1) !== index) textIndices.push(index);
          }
          const proseCount = children.filter(child => child instanceof Markdown || child instanceof FigureMarkdown).length;
          // Hidden live thinking has a semantic kN node but no Markdown child.
          const indices = proseCount === textIndices.length ? textIndices : visibleIndices;
          if (proseCount !== indices.length) {
            throw new Error("Grouping cannot match native assistant text blocks");
          }
          const starts = new Map<number, GroupingMarker | undefined>();
          let offset = 0;
          let index = 0;
          for (const child of children) {
            if (child instanceof Markdown || child instanceof FigureMarkdown) {
              starts.set(offset, displayed.get(indices[index++]));
            }
            offset += child.render(width).length;
          }
          const { theme } = context.ui;
          const result: string[] = [];
          rows.forEach((row, index) => {
            const marker = starts.get(index);
            const label = marker ? renderGroupingLabel(marker, width - 1, theme) : "";
            if (label) result.push(` ${label}`);
            if (label && (marker!.kind === "phase" || marker!.kind === "final")) result.push("");
            result.push(row);
          });
          return result;
        } catch (error) {
          fail(error);
          return rows;
        }
      };
      // Register rollback before touching any native method.
      const isFinalized: typeof finalized = function (this: AssistantMessageComponent) {
        const result = finalized.call(this);
        if (failed) return result;
        try { return result && (!message || !state.awaitingFinal(message)); }
        catch (error) { fail(error); return result; }
      };
      const releaseCaches: typeof release = function (this: AssistantMessageComponent) {
        guard(() => { if (!root.canRemoveBlock(this)) frozen ??= new Map(displayed); });
        return release.call(this);
      };
      restores.push(() => {
        if (component.updateContent === updateContent) component.updateContent = update;
        if (component.render === decoratedRender) component.render = render;
        if (component.releaseRenderCaches === releaseCaches) component.releaseRenderCaches = release;
        if (component.isTranscriptBlockFinalized === isFinalized) component.isTranscriptBlockFinalized = finalized;
        if (mutableBlock.transcriptBlockMode === "mutable") mutableBlock.transcriptBlockMode = blockMode;
      });
      component.updateContent = updateContent;
      component.render = decoratedRender;
      component.isTranscriptBlockFinalized = isFinalized;
      component.releaseRenderCaches = releaseCaches;
      mutableBlock.transcriptBlockMode = "mutable";
      component.invalidate();
    }

    function adapt() {
      guard(() => {
        for (const root of host.children) {
          if (!(root instanceof TranscriptContainer) || roots.has(root)) continue;
          roots.add(root);
          const add = root.addChild;
          const addChild: typeof add = function (this: TranscriptContainer, child) {
            guard(() => { if (child instanceof AssistantMessageComponent) attach(child, this); });
            return add.call(this, child);
          };
          restores.push(() => { if (root.addChild === addChild) root.addChild = add; });
          root.addChild = addChild;
          for (const child of root.children) {
            if (failed) break;
            if (child instanceof AssistantMessageComponent) attach(child, root);
          }
        }
      });
    }
    let unsubscribe = () => {};
    let restored = false;
    const restore = () => {
      if (restored) return;
      restored = true;
      for (const cleanup of [unsubscribe, ...restores.reverse()]) {
        try { cleanup(); }
        catch (error) { console.error("[transcript-grouping] rollback failed", error); }
      }
    };
    dispose = restore;
    unsubscribe = host.addPaintListener(adapt);
    adapt();
    return restore;
  }

  for (const event of ["session_start", "session_switch", "session_tree", "session_branch"] as const) {
    pi.on(event as "session_start", (_event, ctx) => guard(() => {
      context = ctx;
      dispose?.();
      state = new GroupingState(now);
      enabled = true;
      if (!ctx.hasUI) return;
      ctx.ui.setWidget("grouping-host", host => {
        tui = host;
        guard(() => { install(host); });
        return { render: () => [], invalidate() {} };
      });
      ctx.ui.setWidget("grouping-host", undefined);
    }));
  }
  pi.on("before_agent_start", (_event, ctx) => guard(() => {
    if (!tui) return;
    context = ctx;
    state.begin();
  }));
  pi.on("message_start", ({ message }) => guard(() => {
    if (message.role === "assistant") state.observe(message, true);
  }));
  pi.on("message_update", ({ message, assistantMessageEvent }) => guard(() => {
    if (message.role !== "assistant") return;
    state.observe(message);
    if (assistantMessageEvent.type === "text_end") state.textEnded();
  }));
  pi.on("message_end", ({ message }) => guard(() => {
    if (message.role !== "assistant") return;
    state.observe(message);
  }));
  pi.on("tool_execution_start", ({ toolCallId }) => guard(() => state.toolStarted(toolCallId)));
  pi.on("tool_execution_end", ({ toolCallId, isError }) => guard(() => state.toolFinished(toolCallId, isError)));
  pi.on("agent_end", ({ messages }) => guard(() => {
    const last = messages.findLast(message => message.role === "assistant");
    state.finish(last?.role === "assistant" ? last : undefined);
    tui?.requestRender();
  }));
  pi.on("session_shutdown", () => { dispose?.(); dispose = undefined; tui = undefined; });

  function toggle(ctx: ExtensionContext) {
    if (failed) {
      ctx.ui.notify("Grouping is disabled after an error. Restart OMP to retry.", "warning");
      return;
    }
    enabled = !enabled;
    tui?.invalidate();
    tui?.requestRender();
    ctx.ui.notify(`Grouping ${enabled ? "on" : "off"}`, "info");
  }
  pi.registerShortcut("ctrl+s", { description: "Toggle transcript grouping", handler: toggle });
  pi.registerCommand("grouping", { description: "Toggle transcript grouping (Ctrl+S)", handler: async (_args, ctx) => toggle(ctx) });
}
