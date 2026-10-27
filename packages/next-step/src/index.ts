import { randomUUID } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { completeSimple, Effort } from "@oh-my-pi/pi-ai";
import type { AgentEndEvent, ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { getPluginSettings } from "@oh-my-pi/pi-coding-agent/extensibility/plugins";
import { matchesKey, type TUI } from "@oh-my-pi/pi-tui";
import { CustomEditor } from "@oh-my-pi/pi-tui/prompt/custom-editor";
import { appendFeedback, type FeedbackEvent } from "./feedback";
import { choiceRows } from "./cards";
import { summarizeError } from "./errors";
import { buildContext, parseSuggestion, PROMPT_VERSION, SYSTEM_PROMPT, type Suggestion } from "./suggestion";

const WIDGET = "ifwu.next-step";
const EFFORTS = [Effort.Minimal, Effort.Low, Effort.Medium, Effort.High, Effort.XHigh];
interface Sample {
  id: string;
  session: string;
  directory?: string;
  file?: string;
  controller: AbortController;
  pending: boolean;
  displayed: boolean;
  accepted?: string;
  result?: Suggestion;
}

export default function nextStep(pi: ExtensionAPI) {
  pi.registerFlag("next-step", { type: "boolean", description: "Generate optional next-step drafts after completed turns" });
  pi.registerFlag("next-step-model", { type: "string", description: "Next-step model selector; independent of the main model" });
  pi.registerFlag("next-step-effort", { type: "string", description: "Next-step reasoning effort" });
  pi.registerFlag("next-step-data-dir", { type: "string", description: "Private local next-step dataset directory" });

  let enabled = false;
  let initialized = false;
  let modelSpec = "@smol";
  let effort = Effort.Low;
  let dataEnabled = true;
  let dataDirectory: string | undefined;
  let dataFailed = false;
  let failed = false;
  let warned = false;
  let outcome = "off";
  let lastFailure: (Extract<FeedbackEvent, { type: "failed" }> & { at: string; session: string }) | undefined;
  let current: Sample | undefined;
  let visible = false;
  let selected = 0;
  const checked = new Set<number>();
  let previewText: string | undefined;
  let picker: AbortController | undefined;
  let revision = 0;
  let run = 0;
  let scheduledRun = -1;
  let scheduled: Timer | undefined;
  let context: ExtensionContext | undefined;
  let editor: CustomEditor | undefined;
  let tui: TUI | undefined;
  let unsubscribe: (() => void) | undefined;
  let restoreEditor: (() => void) | undefined;
  let restorePrediction: (() => void) | undefined;

  function record(sample: Sample, event: FeedbackEvent) {
    if (!dataEnabled || dataFailed || !sample.file || !sample.directory) return;
    try { appendFeedback(sample.directory, sample.file, sample.id, event); }
    catch {
      dataFailed = true;
      try { context?.ui.notify("下一步建议的本地记录写入失败，已停止采集；建议功能不受影响。", "warning"); }
      catch { console.error("[next-step] local collection disabled after a write error"); }
    }
  }

  function hide(ctx: ExtensionContext) {
    visible = false;
    selected = 0;
    checked.clear();
    previewText = undefined;
    ctx.ui.setWidget(WIDGET, undefined);
  }

  function invalidate(ctx: ExtensionContext, reason: string) {
    revision++;
    clearTimeout(scheduled);
    scheduled = undefined;
    picker?.abort();
    picker = undefined;
    if (current?.pending) {
      current.pending = false;
      current.controller.abort();
      record(current, { type: "cancelled", reason });
    } else if (current && visible) record(current, { type: "dismissed", reason });
    hide(ctx);
    outcome = reason;
  }

  function end(ctx: ExtensionContext, reason: string) {
    invalidate(ctx, reason);
    if (current) record(current, { type: "ended", reason, displayed: current.displayed, accepted: current.accepted !== undefined });
    current = undefined;
  }

  function fail(ctx: ExtensionContext) {
    if (failed) return;
    failed = true;
    enabled = false;
    current?.controller.abort();
    picker?.abort();
    clearTimeout(scheduled);
    unsubscribe?.();
    restorePrediction?.();
    restoreEditor?.();
    try { hide(ctx); ctx.ui.notify("下一步建议因界面异常已停用；输入和对话不受影响，重启 OMP 后恢复。", "warning"); }
    catch { console.error("[next-step] UI disabled after an error"); }
  }

  function ownsInput(ctx: ExtensionContext): boolean {
    return enabled && !failed && ctx.mode === "tui" && ctx.agent.kind === "main" && ctx.isIdle() &&
      !ctx.hasPendingMessages() && !ctx.getPendingPlanReview() &&
      !!editor && !editor.isAutocompleteActive() && tui?.getFocused() === editor && !tui.hasOverlay();
  }

  function available(ctx: ExtensionContext): boolean {
    return ownsInput(ctx) && ctx.ui.getEditorText().length === 0;
  }

  function selectedIndices(result: Suggestion): number[] {
    if (result.kind === "single") return [0];
    return result.kind === "choice" && result.selectionMode === "multiple" && checked.size
      ? result.actions.flatMap((_action, index) => checked.has(index) ? [index] : [])
      : [selected];
  }

  function dismiss(ctx: ExtensionContext) {
    invalidate(ctx, "dismissed");
    if (current) current.result = undefined;
  }

  function render(ctx: ExtensionContext, sample: Sample) {
    const result = sample.result;
    if (!result || result.kind === "none") return;
    previewText = selectedIndices(result).map(index => result.actions[index].draft).join(" ").replace(/\s+/g, " ");
    if (result.kind === "single") {
      ctx.ui.setWidget(WIDGET, [ctx.ui.theme.fg("muted", "下一步建议 · Enter 发送 · Tab 填入输入框 · Esc 忽略")], { placement: "aboveEditor" });
    } else {
      const chosen = selected;
      const marked = new Set(checked);
      ctx.ui.setWidget(WIDGET, (_tui, theme) => {
        let cached: { width: number; editing: boolean; rows: string[] } | undefined;
        return {
          render: width => {
            const editing = ctx.ui.getEditorText().length > 0;
            if (!cached || cached.width !== width || cached.editing !== editing) {
              cached = { width, editing, rows: choiceRows(theme, result, chosen, marked, editing, width) };
            }
            return cached.rows;
          },
          invalidate: () => { cached = undefined; },
        };
      }, { placement: "aboveEditor" });
    }
    visible = true;
    if (!sample.displayed) {
      sample.displayed = true;
      record(sample, { type: "displayed" });
    }
    outcome = "shown";
  }

  function accept(ctx: ExtensionContext, indices: number[]) {
    const sample = current;
    const result = sample?.result;
    if (!sample || !result || sample.session !== ctx.sessionManager.getSessionId() || !available(ctx)) return;
    const draft = indices.map(index => result.actions[index].draft).join("\n\n");
    invalidate(ctx, "accepted into draft");
    ctx.ui.setEditorText(draft);
    sample.accepted = draft;
    record(sample, { type: "accepted", indices, draft });
  }

  async function choose(ctx: ExtensionContext) {
    const sample = current;
    if (!sample?.result?.actions.length || picker || sample.session !== ctx.sessionManager.getSessionId() || !available(ctx)) return;
    const captured = revision;
    const controller = new AbortController();
    picker = controller;
    try {
      const options = sample.result.actions.map((action, index) => ({ label: `${index + 1}. ${action.title}`, description: action.draft }));
      const selected = await ctx.ui.select(`${sample.result.question || "下一步"} · 选中后填入输入框，不发送`, options, { signal: controller.signal });
      if (controller.signal.aborted || captured !== revision || current !== sample) return;
      picker = undefined;
      const index = options.findIndex(option => option.label === selected);
      if (index >= 0) accept(ctx, [index]);
    } catch { if (!controller.signal.aborted) fail(ctx); }
    finally { if (picker === controller) picker = undefined; }
  }

  async function generate(event: AgentEndEvent, ctx: ExtensionContext, captured: number) {
    if (captured !== revision || !available(ctx)) return;
    const snapshot = buildContext(event.messages);
    if (!snapshot) { outcome = "no completed text turn"; return; }
    const model = modelSpec === "current" ? ctx.model : ctx.models.resolve(modelSpec);
    if (!model) {
      outcome = "model unavailable";
      if (!warned) { warned = true; ctx.ui.notify(`下一步建议的模型不可用：${modelSpec}。可用 /next-step model 重新设置。`, "warning"); }
      return;
    }
    const sessionFile = ctx.sessionManager.getSessionFile();
    const directory = dataDirectory ? resolve(ctx.cwd, dataDirectory) :
      sessionFile ? join(dirname(sessionFile), "next-step") : undefined;
    const session = ctx.sessionManager.getSessionId();
    const sample: Sample = {
      id: randomUUID(), session, directory, file: directory ? join(directory, `${session}.jsonl`) : undefined,
      controller: new AbortController(), pending: true, displayed: false,
    };
    current = sample;
    const modelName = `${model.provider}/${model.id}`;
    const requested = { context: snapshot, model: modelName, effort, promptVersion: PROMPT_VERSION };
    record(sample, { type: "requested", ...requested });
    outcome = "generating";
    const started = performance.now();
    const signal = AbortSignal.any([sample.controller.signal, AbortSignal.timeout(60_000)]);
    let stage: "provider" | "parse" = "provider";
    let stopReason: string | undefined;
    try {
      const response = await completeSimple(model, {
        systemPrompt: [SYSTEM_PROMPT],
        messages: [{ role: "user", content: JSON.stringify(snapshot), timestamp: Date.now() }],
      }, {
        apiKey: ctx.modelRegistry.resolver(model, session), reasoning: model.reasoning ? effort : undefined,
        maxTokens: 2048, signal, statefulResponses: false, storeResponses: false,
      });
      if (sample.controller.signal.aborted || current !== sample || captured !== revision || sample.session !== ctx.sessionManager.getSessionId()) return;
      sample.pending = false;
      stopReason = response.stopReason;
      if (response.stopReason !== "stop") throw new Error(response.errorMessage || `Provider stopped with ${response.stopReason}`);
      stage = "parse";
      const result = parseSuggestion(response.content.filter(block => block.type === "text").map(block => block.text).join(""));
      sample.result = result;
      record(sample, { type: "generated", ...requested, result, latencyMs: Math.round(performance.now() - started) });
      if (!available(ctx)) { record(sample, { type: "skipped", reason: "input or UI became busy" }); outcome = "not displayed"; return; }
      if (result.kind === "none") { outcome = "none"; return; }
      try { render(ctx, sample); } catch { fail(ctx); }
    } catch (error) {
      if (sample.controller.signal.aborted || current !== sample || captured !== revision) return;
      sample.pending = false;
      outcome = signal.aborted ? "generation timeout" : "generation failed";
      lastFailure = {
        type: "failed", at: new Date().toISOString(), session, reason: outcome, model: modelName, effort,
        stage, stopReason, error: signal.aborted ? "Generation exceeded the 60-second deadline" : summarizeError(error, stage),
        latencyMs: Math.round(performance.now() - started),
      };
      const { session: _session, ...failure } = lastFailure;
      record(sample, failure);
      if (!warned) { warned = true; ctx.ui.notify("下一步建议生成失败，本轮不显示；可用 /next-step status 查看原因。", "warning"); }
    }
  }

  async function install(ctx: ExtensionContext) {
    context = ctx;
    if (ctx.mode !== "tui" || ctx.agent.kind !== "main" || failed) return;
    if (!initialized) {
      // The suite exposes the same settings under flag-style names; standalone settings win when both exist.
      const standalone = await getPluginSettings("@ifwu/omp-next-step", ctx.cwd);
      const suite = await getPluginSettings("@ifwu/omp-extensions", ctx.cwd);
      const setting = (key: string, name: string) => standalone[key] ?? suite[name];
      initialized = true;
      enabled = (pi.getFlag("next-step") ?? setting("enabled", "next-step")) === true;
      const flagModel = pi.getFlag("next-step-model") ?? setting("model", "next-step-model");
      if (typeof flagModel === "string" && flagModel) modelSpec = flagModel;
      const flagDirectory = pi.getFlag("next-step-data-dir") ?? setting("dataDir", "next-step-data-dir");
      if (typeof flagDirectory === "string" && flagDirectory) dataDirectory = flagDirectory;
      dataEnabled = setting("collect", "next-step-collect") !== false;
      const flagEffort = pi.getFlag("next-step-effort") ?? setting("effort", "next-step-effort") ?? "low";
      const selectedEffort = EFFORTS.find(value => value === flagEffort);
      if (selectedEffort) effort = selectedEffort;
      else { enabled = false; ctx.ui.notify("Next-step effort 无效；请用 /next-step effort 设置后开启。", "warning"); }
      const previous = ctx.ui.getEditorComponent();
      const factory: NonNullable<typeof previous> = (host, theme, keys) => {
        tui = host;
        const component = previous ? previous(host, theme, keys) : new CustomEditor(host, theme, keys);
        editor = component;
        queueMicrotask(() => {
          if (failed || component !== editor) return;
          try {
            restorePrediction?.();
            // Native setup assigns prediction after the factory returns; compose with that owner.
            const previousPrediction = component.prediction;
            const prediction = () => {
              if (enabled && visible && !failed && context && available(context)) return previewText;
              return previousPrediction?.();
            };
            component.prediction = prediction;
            restorePrediction = () => {
              if (component.prediction === prediction) component.prediction = previousPrediction;
            };
          } catch { fail(context ?? ctx); }
        });
        const original = component.handleInput;
        component.handleInput = data => {
          original.call(component, data);
          try {
            if (!matchesKey(data, "enter") && current?.accepted !== undefined && component.getExpandedText().length === 0) current.accepted = undefined;
          } catch { fail(context ?? ctx); }
        };
        return component;
      };
      restoreEditor = () => { if (ctx.ui.getEditorComponent() === factory) ctx.ui.setEditorComponent(previous); };
      ctx.ui.setEditorComponent(factory);
      outcome = enabled ? "ready" : "off";
    }
    unsubscribe?.();
    unsubscribe = ctx.ui.onTerminalInput(data => {
      if (failed || !enabled || picker) return undefined;
      if (data === "\x1b[I" || data === "\x1b[O" || /^\x1b\[<\d+;\d+;\d+[Mm]$/.test(data)) return undefined;
      try {
        if ((visible || current?.pending || scheduled) && ownsInput(ctx) && matchesKey(data, "escape")) {
          dismiss(ctx);
          return { consume: true };
        }
        if (visible && available(ctx)) {
          const result = current?.result;
          const up = matchesKey(data, "up");
          if (result?.kind === "choice" && (up || matchesKey(data, "down"))) {
            const count = result.actions.length;
            selected = (selected + (up ? count - 1 : 1)) % count;
            render(ctx, current!);
            return { consume: true };
          }
          if (result?.kind === "choice" && result.selectionMode === "multiple" && matchesKey(data, "space")) {
            if (checked.has(selected)) checked.delete(selected);
            else checked.add(selected);
            render(ctx, current!);
            return { consume: true };
          }
          if (result && (matchesKey(data, "tab") || matchesKey(data, "right") || matchesKey(data, "enter"))) {
            accept(ctx, selectedIndices(result));
            return matchesKey(data, "enter") ? undefined : { consume: true };
          }
          if (data === "\x1b/" || matchesKey(data, "alt+/")) { void choose(ctx); return { consume: true }; }
          const index = (["alt+1", "alt+2", "alt+3"] as const).findIndex((key, number) => data === `\x1b${number + 1}` || matchesKey(data, key));
          if (index >= 0 && current?.result?.actions[index]) { accept(ctx, [index]); return { consume: true }; }
        }
        previewText = undefined;
        if (current?.pending || scheduled || (visible && current?.result?.kind === "single")) {
          invalidate(ctx, "user input");
          if (current) current.result = undefined;
        }
      } catch { fail(ctx); }
      return undefined;
    });
  }

  pi.on("session_start", async (_event, ctx) => { try { await install(ctx); } catch { fail(ctx); } });
  pi.on("input", (event, ctx) => {
    if (event.source !== "interactive" || !current) return;
    try {
      if (!event.text.startsWith("/")) {
        record(current, { type: "submitted", outcome: current.accepted === undefined ? "other" : event.text === current.accepted ? "accepted" : "edited",
          text: event.text.slice(0, 16_000), truncated: event.text.length > 16_000, displayed: current.displayed });
        invalidate(ctx, "submitted");
        current = undefined;
      }
    } catch { fail(ctx); }
  });
  pi.on("agent_start", (_event, ctx) => { run++; try { end(ctx, "new turn"); } catch { fail(ctx); } });
  pi.on("agent_end", (event, ctx) => {
    if (!enabled || failed || ctx.mode !== "tui" || ctx.agent.kind !== "main" || event.willContinue || event.awaitingAsyncWork || ctx.hasPendingMessages()) return;
    if (scheduledRun === run) return;
    scheduledRun = run;
    try {
      end(ctx, "completed turn");
      const captured = revision;
      scheduled = setTimeout(() => {
        scheduled = undefined;
        void generate(event, ctx, captured).catch(() => fail(ctx));
      }, 0);
    } catch { fail(ctx); }
  });
  const beforeSessionChange = (event: { type: string }, ctx: ExtensionContext) => {
    try { end(ctx, event.type); } catch { fail(ctx); }
  };
  const afterSessionChange = async (event: { type: string }, ctx: ExtensionContext) => {
    run++;
    try { end(ctx, event.type); await install(ctx); } catch { fail(ctx); }
  };
  pi.on("session_before_switch", beforeSessionChange);
  pi.on("session_before_branch", beforeSessionChange);
  pi.on("session_before_tree", beforeSessionChange);
  pi.on("session_before_compact", beforeSessionChange);
  pi.on("session_switch", afterSessionChange);
  pi.on("session_branch", afterSessionChange);
  pi.on("session_tree", afterSessionChange);
  pi.on("session_shutdown", (_event, ctx) => {
    try { end(ctx, "session shutdown"); } finally { unsubscribe?.(); restorePrediction?.(); restoreEditor?.(); }
  });
  pi.registerCommand("next-step", {
    description: "Optional next-step drafts: on|off|status|model <selector>|effort <level>|data on|off|pick",
    handler: async (args, ctx) => {
      const [action = "status", ...rest] = args.trim().split(/\s+/);
      const value = rest.join(" ");
      if (ctx.mode !== "tui") { ctx.ui.notify("Next-step 仅用于 TUI。", "info"); return; }
      if (failed) { ctx.ui.notify("Next-step UI 已停用，需要重启加载。", "warning"); return; }
      if (action === "pick") { await choose(ctx); return; }
      if (action === "on") { enabled = true; warned = false; outcome = "ready for next completed turn"; }
      else if (action === "off") { end(ctx, "disabled"); enabled = false; }
      else if (action === "model" && value) {
        if (!(value === "current" ? ctx.model : ctx.models.resolve(value))) { ctx.ui.notify(`模型不可用：${value}`, "warning"); return; }
        end(ctx, "model changed"); modelSpec = value; warned = false;
      } else if (action === "effort" && value) {
        const selected = EFFORTS.find(level => level === value);
        if (!selected) { ctx.ui.notify(`effort: ${EFFORTS.join(" | ")}`, "warning"); return; }
        end(ctx, "effort changed"); effort = selected; warned = false;
      } else if (action === "data" && (value === "on" || value === "off")) {
        end(ctx, "collection changed"); dataEnabled = value === "on"; dataFailed = false;
      } else if (action !== "status" && action !== "") {
        ctx.ui.notify("/next-step on|off|status|model <selector>|effort minimal|low|medium|high|xhigh|data on|off|pick", "info"); return;
      }
      const sessionFile = ctx.sessionManager.getSessionFile();
      const location = dataDirectory ? resolve(ctx.cwd, dataDirectory) : sessionFile ? join(dirname(sessionFile), "next-step") : "unavailable in ephemeral session";
      const failure = lastFailure?.session === ctx.sessionManager.getSessionId() ? lastFailure : undefined;
      const detail = failure ? `\n最近失败：${failure.at} · ${failure.model} / ${failure.effort} · ${failure.stage}${failure.stopReason ? ` / ${failure.stopReason}` : ""}\n${failure.error}` : "";
      ctx.ui.notify(`下一步建议：${enabled ? "开启" : "关闭"} · ${modelSpec} / ${effort} · ${outcome}${detail}\n本地采集：${dataEnabled && !dataFailed ? location : "关闭"}（含对话摘录、候选和下一条发送内容，仅存本机）`, "info");
    },
  });
}
