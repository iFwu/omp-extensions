import { describe, expect, test } from "bun:test";
import { visibleWidth } from "@oh-my-pi/pi-tui";
import { suggestionRows } from "../src/cards";
import type { Suggestion } from "../src/suggestion";

const theme = {
  fg: (color: string, text: string) => color === "accent" ? `\x1b[33m${text}\x1b[39m` : text,
  bold: (text: string) => `\x1b[1m${text}\x1b[22m`,
} as Parameters<typeof suggestionRows>[0];
const choice: Suggestion = {
  kind: "choice", selectionMode: "single", reason: "两种真实替代方案", question: "先做哪个？",
  actions: [
    { title: "生成 Karabiner 规则", draft: "直接生成可导入的规则。", tradeoff: "一步到位，但可能导入后才发现问题" },
    { title: "先验证单键", draft: "先验证单键链路。", tradeoff: "风险最低，但多一轮" },
  ],
};
const plain = (rows: string[]) => rows.map(row => Bun.stripANSI(row));

describe("suggestionRows", () => {
  test("shows the question once and aligns tradeoffs beside titles when they fit", () => {
    const rows = plain(suggestionRows(theme, choice, 0, new Set(), false, 100));
    expect(rows.join("\n").split(choice.question)).toHaveLength(2);
    const starts = choice.actions.map((action, index) => {
      expect(rows[index + 1]).toContain(action.title);
      return visibleWidth(rows[index + 1].slice(0, rows[index + 1].indexOf(action.tradeoff)));
    });
    expect(new Set(starts).size).toBe(1);
    expect(rows.filter(row => row.includes("›"))).toEqual([rows[1]]);
  });

  test("marks only the focused action", () => {
    const rows = suggestionRows(theme, choice, 1, new Set(), false, 100);
    expect(plain(rows).filter(row => row.includes("›"))).toEqual([plain(rows)[2]]);
    expect(rows[2]).toContain("\x1b[33m");
    expect(rows[1]).not.toContain("\x1b[33m");
  });

  test("wraps long tradeoffs below titles without dropping text or exceeding width", () => {
    const tradeoff = "一步到位拿到配置，但在尚未验证输入链路的情况下，可能导入后才发现 Esc 与后续字符被分开处理。";
    const long = { ...choice, actions: [{ ...choice.actions[0], tradeoff }, choice.actions[1]] };
    const rows = plain(suggestionRows(theme, long, 0, new Set(), false, 40));
    for (const row of rows) expect(visibleWidth(row)).toBeLessThanOrEqual(40);
    const detail = rows.slice(2, rows.findIndex(row => row.includes(choice.actions[1].title)));
    expect(detail.map(row => row.replace(/^\s*│\s+/, "")).join("").replaceAll(" ", "")).toBe(tradeoff.replaceAll(" ", ""));
  });

  test("keeps checks distinct from focus and preserves choices while editing", () => {
    const multi: Suggestion = { ...choice, selectionMode: "multiple" };
    const checks = new Set([1]);
    const focused = plain(suggestionRows(theme, multi, 0, checks, false, 110));
    expect(focused[1]).toContain("› [ ] 1");
    expect(focused[2]).toContain("[x] 2");
    expect(focused[2]).not.toContain("›");
    const editing = plain(suggestionRows(theme, multi, 0, checks, true, 110));
    expect(editing.join("\n")).not.toContain("›");
    for (const action of multi.actions) {
      expect(editing.join("\n")).toContain(action.title);
      expect(editing.join("\n")).toContain(action.tradeoff);
    }
    expect(editing[2]).toContain("[x] 2");
  });

  test("previews the Enter target's draft and hides it while editing", () => {
    expect(plain(suggestionRows(theme, choice, 1, new Set(), false, 100)).join("\n")).toContain(choice.actions[1].draft);
    expect(plain(suggestionRows(theme, choice, 1, new Set(), false, 100)).join("\n")).not.toContain(choice.actions[0].draft);
    const multi: Suggestion = { ...choice, selectionMode: "multiple" };
    const both = plain(suggestionRows(theme, multi, 0, new Set([0, 1]), false, 100)).join("\n");
    expect(both).toContain(`${choice.actions[0].draft} ${choice.actions[1].draft}`);
    expect(plain(suggestionRows(theme, choice, 1, new Set(), true, 100)).join("\n")).not.toContain(choice.actions[1].draft);
  });

  test("renders a single suggestion as a card and caps long drafts within width", () => {
    const draft = "按刚才的安全条件修改 Commit Sweep，满足条件时自动清除隔离标记并记录原因，然后在 dev 和 Step 上各跑一轮验证。".repeat(3);
    const single: Suggestion = { kind: "single", reason: "一个明确的后续", question: "", actions: [{ title: "修改", draft, tradeoff: "" }] };
    const rows = plain(suggestionRows(theme, single, 0, new Set(), false, 40));
    expect(rows[0]).toContain("下一步建议");
    expect(rows.at(-1)).toContain("Enter 发送");
    expect(rows.length).toBe(5);
    expect(rows[3]).toContain("…");
    for (const row of rows) expect(visibleWidth(row)).toBeLessThanOrEqual(40);
    expect(rows.join("\n")).not.toContain("›");
  });
});
