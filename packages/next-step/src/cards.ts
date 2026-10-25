import { truncateToWidth, visibleWidth, wrapTextWithAnsi, type Theme } from "@oh-my-pi/pi-tui";
import type { Suggestion } from "./suggestion";

const GAP = 3;

export function choiceRows(theme: Pick<Theme, "fg" | "bold">, result: Suggestion, selected: number, checked: ReadonlySet<number>, editing: boolean, width: number): string[] {
  const row = (text: string) => truncateToWidth(` ${text}`, width);
  const frame = (text: string) => theme.fg("borderMuted", text);
  const muted = (text: string) => theme.fg("muted", text);
  const multiple = result.kind === "choice" && result.selectionMode === "multiple";
  const lead = multiple ? 12 : 8;
  const column = Math.min(Math.max(...result.actions.map(action => visibleWidth(action.title))), Math.max(8, Math.floor((width - lead - GAP) / 2)));
  const inline = Math.max(...result.actions.map(action => visibleWidth(action.tradeoff))) <= width - lead - column - GAP;
  const rows = [row(`${frame("╭─")} ${muted(result.question)}`)];
  result.actions.forEach((action, index) => {
    const active = !editing && index === selected;
    const title = truncateToWidth(action.title, inline ? column : width - lead);
    const mark = multiple ? `${checked.has(index) ? theme.fg("accent", "[x]") : muted("[ ]")} ` : "";
    const head = `${frame("│")} ${active ? theme.fg("accent", "›") : " "} ${mark}${muted(String(index + 1))}  ${active ? theme.fg("accent", theme.bold(title)) : theme.bold(title)}`;
    if (inline) rows.push(row(`${head}${" ".repeat(column - visibleWidth(title) + GAP)}${muted(action.tradeoff)}`));
    else rows.push(row(head), ...wrapTextWithAnsi(action.tradeoff, Math.max(1, width - lead)).map(line => row(`${frame("│")}${" ".repeat(lead - 2)}${muted(line)}`)));
  });
  const targets = multiple && checked.size ? [...checked].sort((a, b) => a - b).map(index => index + 1).join("、") : String(selected + 1);
  const hint = editing ? "输入框内容原样发送 · Esc 忽略建议" :
    `↑↓ 移动${multiple ? " · Space 勾选" : ""} · Enter 发送 ${targets} · Tab 填入 · Esc 忽略`;
  rows.push(row(`${frame("╰─")} ${muted(hint)}`));
  return rows;
}
