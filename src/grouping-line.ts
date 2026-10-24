import { visibleWidth } from "@oh-my-pi/pi-tui";

export type GroupingMarker = {
  kind: "gap" | "phase" | "final";
  seconds: number;
  tools: number;
  failures: number;
  /** Foreground tool wait inside a long gap, in seconds; concurrent calls count once. */
  blocking?: number;
};

type ColorName = "dim" | "mdLink" | "mdLinkUrl" | "mdHr" | "borderMuted";
type Colors = { isLight: boolean; fg: (color: ColorName, text: string) => string };
const RULE_WIDTH = 72;

function duration(seconds: number, compact: boolean): string {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor(total / 60) % 60;
  const rest = String(total % 60).padStart(2, "0");
  if (hours) {
    const middle = String(minutes).padStart(2, "0");
    return compact ? `${hours}:${middle}:${rest}` : `${hours}h${middle}m${rest}s`;
  }
  if (minutes) return compact ? `${minutes}:${rest}` : `${minutes}m${rest}s`;
  return `${total}s`;
}

export function renderGroupingLabel(marker: GroupingMarker, limit: number, colors: Colors): string {
  if (!Number.isFinite(limit) || limit < 1) return "";
  if (marker.kind === "final" && marker.seconds < 120) return "";
  const dim = (text: string) => colors.fg("dim", text);
  // Built-in light themes make mdLinkUrl equal to dim and mdHr as dark as muted text.
  const strong = (text: string) => colors.fg(colors.isLight ? "mdLink" : "mdLinkUrl", text);
  const ruleColor: ColorName = colors.isLight ? "borderMuted" : "mdHr";

  // Drop tool wait first, then shorten units, elapsed time and tool counts; failures and "Done" stay longest.
  for (let step = 0; step < 6; step++) {
    const level = Math.max(0, step - 1);
    const separator = level < 2 ? " · " : " ";
    const parts: string[] = [];
    if (marker.kind === "final") parts.push(strong("══ Done"));
    if (level < 3) {
      const time = duration(marker.seconds, level >= 2);
      parts.push(marker.kind === "phase" ? strong(time) : dim(time));
    }
    if (step === 0 && marker.blocking !== undefined && marker.blocking > 0) parts.push(dim(`⟡ ${duration(marker.blocking, false)}`));
    if (marker.tools > 0 && level < 4) {
      parts.push(dim(level === 0 ? `${marker.tools} ${marker.tools === 1 ? "tool" : "tools"}` : `${marker.tools}t`));
    }
    if (marker.failures > 0) parts.push(dim(level === 0 ? `${marker.failures} failed` : `${marker.failures}!`));
    const label = parts.join(dim(separator));
    const width = visibleWidth(label);
    if (!label || width > limit) continue;
    const rest = Math.min(RULE_WIDTH, limit) - width - 1;
    return marker.kind === "final" && rest > 0 ? `${label}${colors.fg(ruleColor, ` ${"═".repeat(rest)}`)}` : label;
  }
  return "";
}
