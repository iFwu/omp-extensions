import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { lookup } from "@oh-my-pi/pi-coding-agent/config/registry";
import { Container, Text, type Component } from "@oh-my-pi/pi-tui";
import { toolRenderers } from "@oh-my-pi/pi-tui/tools";

const messageType = "dotfiles.ask-history";

export default function (pi: ExtensionAPI) {
  const hideToolActivity = lookup("display.hideToolActivity")!;
  let failed = false;
  let context: ExtensionContext | undefined;
  function fail(error: unknown) {
    if (failed) return;
    failed = true;
    console.error("[ask-history] native history renderer disabled after an error", error);
    try {
      context?.setTimeout(() => {
        try { context?.ui.notify("Ask history styling disabled after an error; answers remain available as text.", "warning"); }
        catch (notificationError) { console.error("[ask-history] could not display failure notice", notificationError); }
      }, 0);
    } catch (notificationError) {
      console.error("[ask-history] could not schedule failure notice", notificationError);
    }
  }
  pi.on("session_start", (_event, ctx) => { context = ctx; });

  pi.registerMessageRenderer(messageType, (message, options, theme) => {
    const plain = new Text(String(message.content), 0, 0);
    let component: Component;
    try {
      if (!hideToolActivity.get(pi.pi.settings)) return new Container();
      if (failed) return plain;
      const rendered = toolRenderers.ask.renderResult!({
        content: [{ type: "text", text: String(message.content) }],
        details: message.details,
      }, { ...options, isPartial: false }, theme);
      if (!rendered) throw new Error("Native Ask renderer returned no component");
      component = rendered;
    } catch (error) { fail(error); return plain; }
    return {
      render(width) {
        if (failed) return plain.render(width);
        try { return component.render(width); }
        catch (error) { fail(error); return plain.render(width); }
      },
      invalidate() {
        plain.invalidate();
        if (!failed) {
          try { component.invalidate?.(); } catch (error) { fail(error); }
        }
      },
    };
  });

  pi.on("tool_execution_end", (event, ctx) => {
    if (event.toolName !== "ask" || ctx.agent.kind !== "main") return;
    const result = event.result as { content: { type: string; text?: string }[]; details?: unknown };
    const content = result.content
      .filter((part) => part.type === "text")
      .map((part) => part.text)
      .join("\n");
    pi.sendMessage({
      customType: messageType,
      content,
      details: result.details,
      display: true,
    }, ctx.isIdle() ? {} : { deliverAs: "aside" });
  });

  pi.on("context", (event) => ({
    messages: event.messages.filter((message) => message.role !== "custom" || message.customType !== messageType),
  }));
}
