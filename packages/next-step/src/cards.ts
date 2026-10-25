import { truncateToWidth, visibleWidth, wrapTextWithAnsi, type Theme } from "@oh-my-pi/pi-tui";
import type { Suggestion } from "./suggestion";

// Each title follows " │ › 1  " (8 cells); tradeoffs share title rows only when every one fits there whole.
const LEAD = 8;
const GAP = 3;

export function choiceRows(theme: Pick<Theme, "fg" | "bold">, result: Suggestion, selected: number | undefined, width: number): string[] {
  const row = (text: string) => truncateToWidth(` ${text}`, width);
  const frame = (text: string) => theme.fg("borderMuted", text);
  const muted = (text: string) => theme.fg("muted", text);
  const column = Math.min(Math.max(...result.actions.map(action => visibleWidth(action.title))), Math.max(8, Math.floor((width - LEAD - GAP) / 2)));
  const inline = Math.max(...result.actions.map(action => visibleWidth(action.tradeoff))) <= width - LEAD - column - GAP;
  const rows = [row(`${frame("╭─")} ${muted(result.question)}`)];
  result.actions.forEach((action, index) => {
    const active = index === selected;
    const title = truncateToWidth(action.title, inline ? column : width - LEAD);
    const head = `${frame("│")} ${active ? theme.fg("accent", "›") : " "} ${muted(String(index + 1))}  ${active ? theme.fg("accent", theme.bold(title)) : theme.bold(title)}`;
    if (inline) rows.push(row(`${head}${" ".repeat(column - visibleWidth(title) + GAP)}${muted(action.tradeoff)}`));
    else rows.push(row(head), ...wrapTextWithAnsi(action.tradeoff, Math.max(1, width - LEAD)).map(line => row(`${frame("│")}      ${muted(line)}`)));
  });
  rows.push(row(`${frame("╰─")} ${muted(selected === undefined ? "↑↓ 选择 · Alt+/ 查看全文 · Esc 忽略" : "Enter 发送 · Tab 填入输入框 · Esc 忽略")}`));
  return rows;
}
