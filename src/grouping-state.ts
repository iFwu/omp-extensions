import type { AssistantMessage } from "@oh-my-pi/pi-ai";
import type { GroupingMarker } from "./grouping-line";

type Phase = "commentary" | "final_answer";
type TextGroup = {
  index: number;
  marker?: GroupingMarker;
  phase?: Phase;
  seconds: number;
  tools: number;
  failures: number;
  length: number;
};
type MessageGroups = { key: string; texts: TextGroup[] };

function messageKey(message: AssistantMessage): string {
  // responseId may be absent in streamed events and added only to the finalized message.
  return JSON.stringify([message.timestamp, message.provider, message.model]);
}

function phaseOf(signature: string | undefined): Phase | undefined {
  if (!signature?.startsWith("{")) return;
  try {
    const parsed = JSON.parse(signature);
    if (parsed.v === 1 && (parsed.phase === "commentary" || parsed.phase === "final_answer")) return parsed.phase;
  } catch {
    // textSignature is provider-owned and can be an opaque string.
  }
}

export class GroupingState {
  private groups = new Map<string, MessageGroups>();
  private messages = new Map<string, AssistantMessage>();
  private startedAt: number | undefined;
  private lastTextAt: number | undefined;
  private tools = new Set<string>();
  private failures = new Set<string>();
  private previousTools = 0;
  private previousFailures = 0;
  private current: MessageGroups | undefined;
  private activeTools = new Set<string>();
  private toolIntervals: [number, number][] = [];
  private toolsStartedAt: number | undefined;

  constructor(private now: () => number = () => performance.now()) {}

  begin() {
    this.startedAt = this.now();
    this.lastTextAt = undefined;
    this.tools.clear();
    this.failures.clear();
    this.previousTools = 0;
    this.previousFailures = 0;
    this.current = undefined;
    this.activeTools.clear();
    this.toolIntervals = [];
    this.toolsStartedAt = undefined;
  }

  toolStarted(id: string) {
    if (this.startedAt === undefined || this.tools.has(id)) return;
    this.tools.add(id);
    if (this.activeTools.size === 0) this.toolsStartedAt = this.now();
    this.activeTools.add(id);
  }

  toolFinished(id: string, failed: boolean) {
    if (this.startedAt === undefined) return;
    this.tools.add(id);
    if (failed) this.failures.add(id);
    if (this.activeTools.delete(id) && this.activeTools.size === 0) {
      this.toolIntervals.push([this.toolsStartedAt!, this.now()]);
      this.toolsStartedAt = undefined;
    }
  }

  private blockingSeconds(from: number, to: number): number {
    let total = this.toolsStartedAt === undefined ? 0 : Math.max(0, to - Math.max(this.toolsStartedAt, from));
    for (const [start, end] of this.toolIntervals) total += Math.max(0, Math.min(end, to) - Math.max(start, from));
    return Math.floor(total / 1000);
  }

  observe(message: AssistantMessage, fresh = false) {
    if (this.startedAt === undefined) return;
    const key = messageKey(message);
    if (fresh || !this.current) {
      this.current = { key, texts: [] };
    }
    const group = this.current;
    if (group.key !== key) {
      this.groups.delete(group.key);
      this.messages.delete(group.key);
      group.key = key;
    }
    this.groups.set(key, group);
    this.messages.set(key, message);
    for (let index = 0; index < message.content.length; index++) {
      const block = message.content[index];
      if (block.type !== "text" || !block.text.trim()) continue;
      const phase = phaseOf(block.textSignature);
      let text = group.texts.find(item => item.index === index);
      if (!text) {
        const now = this.now();
        const from = this.lastTextAt ?? this.startedAt;
        const seconds = Math.max(0, Math.floor((now - from) / 1000));
        const tools = this.tools.size - this.previousTools;
        const failures = this.failures.size - this.previousFailures;
        const kind = seconds >= 120 ? "phase" : seconds >= 10 || tools >= 3 || failures > 0 ? "gap" : undefined;
        const marker: GroupingMarker | undefined = this.lastTextAt !== undefined && kind ? { kind, seconds, tools, failures } : undefined;
        if (marker?.kind === "phase") {
          const blocking = this.blockingSeconds(from, now);
          if (blocking > 0) marker.blocking = blocking;
        }
        text = { index, seconds, tools, failures, length: 0, phase, marker };
        group.texts.push(text);
        this.previousTools = this.tools.size;
        this.previousFailures = this.failures.size;
      }
      if (phase === "final_answer" && text.marker?.kind !== "final") {
        text.marker = this.finalMarker(text);
      }
      text.phase = phase;
      if (text.length !== block.text.length) {
        text.length = block.text.length;
        this.lastTextAt = this.now();
      }
    }
  }

  textEnded() {
    if (this.lastTextAt !== undefined) this.lastTextAt = this.now();
  }

  finish(message?: AssistantMessage) {
    if (this.startedAt === undefined) return;
    if (message?.stopReason === "stop" && !message.content.some(block => block.type === "toolCall")) {
      const group = this.groups.get(messageKey(message));
      const text = group?.texts.at(-1);
      if (text && text.phase !== "commentary") text.marker = this.finalMarker(text);
    }
    this.startedAt = undefined;
  }

  awaitingFinal(message: AssistantMessage): boolean {
    if (this.startedAt === undefined) return false;
    const key = messageKey(message);
    const full = this.messages.get(key);
    const group = this.groups.get(key);
    return !!full && full.stopReason === "stop" && !full.content.some(block => block.type === "toolCall")
      && !!group?.texts.length && group.texts.at(-1)?.phase !== "commentary";
  }

  private finalMarker(text: TextGroup): GroupingMarker {
    const seconds = Math.max(0, Math.floor((this.now() - this.startedAt!) / 1000));
    return { kind: "final", seconds, tools: text.tools, failures: text.failures };
  }

  find(message: AssistantMessage, localIndex: number): TextGroup | undefined {
    const key = messageKey(message);
    const group = this.groups.get(key);
    const full = this.messages.get(key);
    const block = message.content[localIndex];
    if (!group || !full || block?.type !== "text") return;
    // Native slices omit tools; smooth streaming displays a prefix of provider text.
    let occurrence = 0;
    for (let index = 0; index < localIndex; index++) {
      const preceding = message.content[index];
      if (preceding.type === "text" && preceding.text.startsWith(block.text)
        && (!block.textSignature || preceding.textSignature === block.textSignature)) occurrence++;
    }
    for (let index = 0; index < full.content.length; index++) {
      const candidate = full.content[index];
      if (candidate.type !== "text" || !candidate.text.startsWith(block.text)) continue;
      if (block.textSignature && candidate.textSignature !== block.textSignature) continue;
      if (occurrence-- === 0) return group.texts.find(item => item.index === index);
    }
  }
}
