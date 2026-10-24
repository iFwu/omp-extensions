import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

// `/model <selector>` is session-only, same as `/switch`. Bare `/model` stays the role hub.
export function sessionSwitchCommand(text: string): string | undefined {
  const trimmed = text.trim();
  const split = trimmed.search(/[ \t]/);
  if (split <= 0 || /[\r\n]/.test(trimmed)) return;
  const name = trimmed.slice(0, split).toLowerCase();
  if (name !== "/model" && name !== "/models") return;
  const selector = trimmed.slice(split).trim();
  if (!selector) return;
  return `/switch ${selector}`;
}

export default function (pi: ExtensionAPI) {
  pi.on("input", (event) => {
    const text = sessionSwitchCommand(event.text);
    if (text === undefined) return;
    return { text };
  });
}
