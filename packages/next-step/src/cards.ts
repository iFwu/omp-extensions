import { truncateToWidth, visibleWidth, wrapTextWithAnsi, type Theme } from "@oh-my-pi/pi-tui";
import type { Suggestion } from "./suggestion";

const GAP = 3;
/** Draft preview lines below the options; longer drafts end in an ellipsis. */
const DRAFT_ROWS = 3;

/** Indices Enter/Tab would adopt: checked actions in option order, otherwise the focused one. */
export function targetIndices(result: Suggestion, selected: number, checked: ReadonlySet<number>): number[] {
  if (result.kind !== "choice") return [0];
  return result.selectionMode === "multiple" && checked.size ? [...checked].sort((a, b) => a - b) : [selected];
}

export function suggestionRows(theme: Pick<Theme, "fg" | "bold">, result: Suggestion, selected: number, checked: ReadonlySet<number>, editing: boolean, width: number): string[] {
  const row = (text: string) => truncateToWidth(` ${text}`, width);
  const frame = (text: string) => theme.fg("borderMuted", text);
  const muted = (text: string) => theme.fg("muted", text);
  const choice = result.kind === "choice";
  const multiple = choice && result.selectionMode === "multiple";
  const rows = [row(`${frame("╭─")} ${muted(choice && result.question ? result.question : "下一步建议")}`)];
  if (choice) {
    const lead = multiple ? 12 : 8;
    const column = Math.min(Math.max(...result.actions.map(action => visibleWidth(action.title))), Math.max(8, Math.floor((width - lead - GAP) / 2)));
    const inline = Math.max(...result.actions.map(action => visibleWidth(action.tradeoff))) <= width - lead - column - GAP;
    result.actions.forEach((action, index) => {
      const active = !editing && index === selected;
      const title = truncateToWidth(action.title, inline ? column : width - lead);
      const mark = multiple ? `${checked.has(index) ? theme.fg("accent", "[x]") : muted("[ ]")} ` : "";
      const head = `${frame("│")} ${active ? theme.fg("accent", "›") : " "} ${mark}${muted(String(index + 1))}  ${active ? theme.fg("accent", theme.bold(title)) : theme.bold(title)}`;
      if (inline) rows.push(row(`${head}${" ".repeat(column - visibleWidth(title) + GAP)}${muted(action.tradeoff)}`));
      else rows.push(row(head), ...wrapTextWithAnsi(action.tradeoff, Math.max(1, width - lead)).map(line => row(`${frame("│")}${" ".repeat(lead - 2)}${muted(line)}`)));
    });
  }
  const targets = targetIndices(result, selected, checked);
  if (!choice || !editing) {
    const draft = targets.map(index => result.actions[index].draft).join(" ").replace(/\s+/g, " ");
    const lines = wrapTextWithAnsi(draft, Math.max(1, width - 4));
    const shown = lines.slice(0, DRAFT_ROWS);
    if (lines.length > DRAFT_ROWS) shown[DRAFT_ROWS - 1] = truncateToWidth(`${shown[DRAFT_ROWS - 1]}${"\u2026".repeat(2)}`, width - 4);
    rows.push(...shown.map(line => row(`${frame("│")} ${line}`)));
  }
  const hint = editing ? "输入框内容原样发送 · Esc 忽略建议" : choice
    ? `↑↓ 移动${multiple ? " · Space 勾选" : ""} · Enter 发送 ${targets.map(index => index + 1).join("、")} · Tab 填入 · Esc 忽略`
    : "Enter 发送 · Tab 填入 · Esc 忽略";
  rows.push(row(`${frame("╰─")} ${muted(hint)}`));
  return rows;
}
