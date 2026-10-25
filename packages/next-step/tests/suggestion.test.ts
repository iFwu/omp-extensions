import { describe, expect, test } from "bun:test";
import type { AssistantMessage, UserMessage } from "@oh-my-pi/pi-ai";
import type { AgentEndEvent } from "@oh-my-pi/pi-coding-agent";
import { buildContext, parseSuggestion, type Suggestion } from "../src/suggestion";

type Message = AgentEndEvent["messages"][number];
const action = { title: "继续排查", draft: "帮我继续排查连接失败的原因。", tradeoff: "" };
const single: Suggestion = { kind: "single", reason: "有明确后续意图", question: "", actions: [action] };
const choice: Suggestion = {
  kind: "choice", selectionMode: "single", reason: "两种真实替代方案", question: "你想选哪种？",
  actions: [{ ...action, tradeoff: "保留现有配置" }, { title: "更换方案", draft: "帮我换成集中管理配置的方案。", tradeoff: "需要迁移配置" }],
};
const parse = (value: unknown) => parseSuggestion(JSON.stringify(value));
function user(content: UserMessage["content"], synthetic = false): UserMessage {
  return { role: "user", content, synthetic, timestamp: 1 };
}
function assistant(content: string, overrides: Partial<AssistantMessage> = {}): AssistantMessage {
  return {
    role: "assistant", content: [{ type: "text", text: content }], api: "openai-responses", provider: "openai", model: "test",
    usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
    stopReason: "stop", timestamp: 2, ...overrides,
  };
}
const toolResult: Message = { role: "toolResult", toolCallId: "call-1", toolName: "read", content: [{ type: "text", text: "SECRET TOOL LOG" }], isError: false, timestamp: 3 };

describe("parseSuggestion", () => {
  test("accepts none and single without selectionMode", () => {
    const none: Suggestion = { kind: "none", reason: "没有明确后续", question: "", actions: [] };
    for (const value of [none, single]) {
      const result = parse(value);
      expect(result).toEqual(value);
      expect(Object.hasOwn(result, "selectionMode")).toBe(false);
    }
  });

  test.each(["single", "multiple"] as const)("preserves %s choice mode and original action order", selectionMode => {
    const value = { ...choice, selectionMode };
    expect(parse(value)).toEqual(value);
    const three = { ...value, actions: [...value.actions, { title: "检查依赖", draft: "帮我检查依赖版本。", tradeoff: "定位兼容问题" }] };
    expect(parse(three)).toEqual(three);
    for (const actions of [[], [value.actions[0]], [...three.actions, { title: "查看日志", draft: "帮我分析错误日志。", tradeoff: "补充错误线索" }]]) {
      expect(() => parse({ ...value, actions })).toThrow();
    }
  });

  test("requires an exact choice selectionMode without legacy defaults", () => {
    for (const selectionMode of [undefined, null, false, 1, "", "Single", "single ", "multi", [], {}]) {
      expect(() => parse({ ...choice, selectionMode })).toThrow();
    }
  });

  test("rejects selectionMode on every non-choice kind", () => {
    for (const value of [single, { kind: "none", reason: "没有明确后续", question: "", actions: [] }]) {
      for (const selectionMode of ["single", "multiple", null, false, ""]) {
        expect(() => parse({ ...value, selectionMode })).toThrow();
      }
    }
  });

  test("keeps semantic grounding in the prompt, not a completed-action phrase filter", () => {
    for (const draft of ["我试过了，还是不行，继续排查。", "I have tried it; it still fails. Investigate further."]) {
      expect(parse({ ...single, actions: [{ ...action, draft }] }).actions[0].draft).toBe(draft);
    }
    expect(parse({ ...single, actions: [{ ...action, title: "🧪".repeat(48), draft: "中".repeat(1200) }] }).kind).toBe("single");
  });

  test("rejects malformed JSON and fenced output rather than repairing", () => {
    for (const source of ["", "{", "null", "[]", "true", "```json\n" + JSON.stringify(single) + "\n```", JSON.stringify(single) + " trailing"]) {
      expect(() => parseSuggestion(source)).toThrow();
    }
  });

  test("rejects unknown/missing fields and non-string fields", () => {
    for (const value of [{ ...single, extra: true }, { kind: "single" }, { ...single, kind: "other" },
      { ...single, reason: 1 }, { ...single, question: null }, { ...single, actions: {} },
      { ...single, actions: [null] }, { ...single, actions: [{ ...action, title: 1 }] },
      { ...single, actions: [{ ...action, draft: [] }] }, { ...single, actions: [{ ...action, tradeoff: false }] },
      { ...single, actions: [{ ...action, extra: "unexpected" }] }]) expect(() => parse(value)).toThrow();
  });

  test("requires every base and action field in both choice modes", () => {
    for (const selectionMode of ["single", "multiple"] as const) {
      const value = { ...choice, selectionMode };
      for (const field of Object.keys(value)) {
        const missing = Object.fromEntries(Object.entries(value).filter(([key]) => key !== field));
        expect(() => parse(missing)).toThrow();
      }
      expect(() => parse({ ...value, extra: true })).toThrow();
      for (const field of Object.keys(action)) {
        const missing = Object.fromEntries(Object.entries(value.actions[0]).filter(([key]) => key !== field));
        expect(() => parse({ ...value, actions: [missing, value.actions[1]] })).toThrow();
      }
      expect(() => parse({ ...value, actions: [{ ...value.actions[0], selectionMode }, value.actions[1]] })).toThrow();
    }
  });

  test("enforces cardinality and choice-only fields", () => {
    for (const value of [{ ...single, kind: "none" }, { ...single, actions: [] }, { ...single, actions: choice.actions },
      { ...choice, actions: [choice.actions[0]] }, { ...choice, actions: [...choice.actions, ...choice.actions] },
      { ...single, question: "Why?" },
      { ...choice, question: "" }, { ...choice, actions: [action, choice.actions[1]] }]) expect(() => parse(value)).toThrow();
  });

  test("enforces exact Unicode length bounds", () => {
    expect(parse({ ...single, reason: "中".repeat(240) }).reason.length).toBe(240);
    expect(parse({ ...choice, question: "中".repeat(120), actions: choice.actions.map(item => ({ ...item, tradeoff: "中".repeat(160) })) }).kind).toBe("choice");
    for (const value of [{ ...single, reason: "中".repeat(241) }, { ...single, reason: " " },
      { ...choice, question: "中".repeat(121) }, { ...choice, question: " " },
      { ...single, actions: [{ ...action, title: "🧪".repeat(49) }] },
      { ...single, actions: [{ ...action, title: "" }] }, { ...single, actions: [{ ...action, draft: " " }] },
      { ...single, actions: [{ ...action, draft: "中".repeat(1201) }] },
      { ...choice, actions: [{ ...choice.actions[0], tradeoff: "中".repeat(161) }, choice.actions[1]] }]) expect(() => parse(value)).toThrow();
  });

  test("rejects controls, invalid Unicode, and normalized duplicates", () => {
    for (const title of ["bad\nlabel", "bad\u001blabel", "bad\u0085label", "\ud800"]) {
      expect(() => parse({ ...single, actions: [{ ...action, title }] })).toThrow();
    }
    expect(() => parse({ ...single, actions: [{ ...action, draft: "bad\u0000draft" }] })).toThrow();
    expect(parse({ ...single, actions: [{ ...action, draft: "第一行\n\t第二行" }] }).kind).toBe("single");
    expect(() => parse({ ...choice, actions: [choice.actions[0], { ...choice.actions[1], title: ` ${action.title} ` }] })).toThrow();
    expect(() => parse({ ...choice, actions: [choice.actions[0], { ...choice.actions[1], draft: action.draft }] })).toThrow();
    expect(() => parse({ ...choice, actions: [{ ...choice.actions[0], title: "Ａ" }, { ...choice.actions[1], title: "a" }] })).toThrow();
  });
});

describe("buildContext", () => {
  test("keeps two recent requests and related final answers, not session origin", () => {
    expect(buildContext([user("ORIGINAL SESSION PROMPT"), assistant("old answer"), user("recent request"), assistant("recent final"), user("latest goal"), assistant("latest final")])).toEqual({
      messages: [{ role: "user", content: "recent request" }, { role: "assistant", content: "recent final" }, { role: "user", content: "latest goal" }, { role: "assistant", content: "latest final" }],
    });
  });

  test("excludes thinking, tools, commentary, synthetic and custom internal text", () => {
    const messages: Message[] = [user([{ type: "text", text: "actual goal" }, { type: "image", data: "SECRET IMAGE", mimeType: "image/png" }]),
      assistant("", { stopReason: "toolUse", content: [{ type: "toolCall", id: "call-1", name: "read", arguments: {} }] }), toolResult,
      user("SECRET SYNTHETIC", true),
      assistant("", { content: [{ type: "thinking", thinking: "SECRET THINKING" },
        { type: "text", text: "SECRET COMMENTARY", textSignature: '{"v":1,"phase":"commentary"}' },
        { type: "text", text: "visible final", textSignature: '{"v":1,"phase":"final_answer"}' }] }),
      { role: "custom", customType: "internal", content: "SECRET CUSTOM", display: false, timestamp: 4 }];
    expect(buildContext(messages)).toEqual({ messages: [{ role: "user", content: "actual goal" }, { role: "assistant", content: "visible final" }] });
  });

  test("truncates explicitly while reserving latest goal and substantial final", () => {
    const context = buildContext([user("old".repeat(8000)), assistant("old final".repeat(8000)),
      user("LATEST GOAL START " + "目".repeat(20000) + " LATEST GOAL END"),
      assistant("FINAL START " + "答".repeat(20000) + " FINAL END")]);
    expect(context).toBeDefined();
    const entries = context!.messages;
    expect(entries.reduce((sum, entry) => sum + entry.content.length, 0)).toBeLessThanOrEqual(16000);
    expect(entries[2].content).toContain("LATEST GOAL START");
    expect(entries[2].content).toContain("LATEST GOAL END");
    expect(entries[3].content).toContain("FINAL START");
    expect(entries[3].content).toContain("FINAL END");
    expect(entries[3].content.length).toBeGreaterThanOrEqual(9900);
    for (const entry of entries) expect(entry.content).toContain("[... truncated ...]");
  });

  test("does not cut surrogate pairs and leaves small latest goal intact", () => {
    const context = buildContext([user("保留这个目标"), assistant("🧪".repeat(20000))]);
    expect(context?.messages[0].content).toBe("保留这个目标");
    expect(context?.messages[1].content.isWellFormed()).toBe(true);
    expect(context!.messages.reduce((sum, entry) => sum + entry.content.length, 0)).toBeLessThanOrEqual(16000);
  });

  test.each(["error", "aborted", "length", "toolUse"] as const)("skips nonfinal stop %s", stopReason => {
    expect(buildContext([user("goal"), assistant("previous final"), assistant("partial", { stopReason })])).toBeUndefined();
  });

  test("skips pending calls even if a later message claims to be final", () => {
    const call = assistant("", { content: [{ type: "toolCall", id: "call-1", name: "read", arguments: {} }] });
    expect(buildContext([user("goal"), call])).toBeUndefined();
    expect(buildContext([user("goal"), call, assistant("final")])).toBeUndefined();
    expect(buildContext([user("goal"), call, toolResult, assistant("final")])).toBeDefined();
    expect(buildContext([user("old goal"), call, assistant("cancelled", { stopReason: "aborted" }), user("new goal"), assistant("completed new goal")])).toBeDefined();
  });

  test("requires a textual latest request and completed final answer", () => {
    expect(buildContext([])).toBeUndefined();
    expect(buildContext([assistant("unsolicited")])).toBeUndefined();
    expect(buildContext([user("goal"), assistant("old final"), user("new goal")])).toBeUndefined();
    expect(buildContext([user("goal"), assistant(""), toolResult])).toBeUndefined();
    expect(buildContext([user("goal"), assistant("", { content: [{ type: "thinking", thinking: "private" }] })])).toBeUndefined();
    expect(buildContext([user("goal"), assistant("", { content: [{ type: "text", text: "working", textSignature: '{"v":1,"phase":"commentary"}' }] })])).toBeUndefined();
    expect(buildContext([user([{ type: "image", data: "image", mimeType: "image/png" }]), assistant("final")])).toBeUndefined();
  });
});
