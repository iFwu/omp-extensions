"""Show one timed line after a minute, then freeze completion time and release timers."""

import os
import shutil
import subprocess
import unittest

from test_support import extension_path
from pathlib import Path


@unittest.skipUnless(shutil.which("bun"), "Bun is not installed")
class TurnTimeTests(unittest.TestCase):
    def test_live_duration_completion_time_and_session_lifecycle(self):
        script = r"""
import assert from "node:assert/strict";
import { mock } from "bun:test";
mock.module("@oh-my-pi/pi-tui", () => ({
  Container: class {}, fieldComposerStyle: {}, theme: {}, truncateToWidth: () => "", visibleWidth: () => 0,
}));
mock.module("@oh-my-pi/pi-tui/prompt/queued-messages", () => ({ QueuedMessagesBand: class {} }));
mock.module("@oh-my-pi/pi-coding-agent/config/registry", () => ({ lookup: () => ({ get: () => true }) }));
const { default: extension } = await import(process.argv[1]);
let now = 0;
Object.defineProperty(performance, "now", { value: () => now });
const RealDate = Date;
let wallNow = Date.UTC(2026, 0, 1, 17, 48);
globalThis.Date = class extends RealDate {
  constructor() { super(wallNow); }
};
const handlers = new Map();
const timers = new Map();
let widget;
let working;
const ctx = {
  isIdle: () => true,
  ui: {
    theme: { fg: (_color, text) => text },
    setWidget: (_key, lines) => { widget = lines; },
    setWorkingMessage: text => { working = text; },
  },
  setInterval(callback, delay) {
    const handle = {};
    timers.set(handle, { callback, delay, at: now + delay });
    return handle;
  },
  clearTimer: handle => { timers.delete(handle); },
};
await extension({
  on(event, handler) { handlers.set(event, handler); },
  registerComposerShape() {},
});
const emit = (event, data = {}) => handlers.get(event)?.(data, ctx);
const streamedIntent = intent => ({
  message: { role: "assistant", content: [{ type: "toolCall", arguments: { i: intent } }] },
  assistantMessageEvent: { type: "toolcall_delta" },
});
const duration = () => (working ?? widget?.[0])?.match(/\d+[hms]\b/g)?.map(part => part.replace(/^0+(?=\d)/, ""));
const completion = () => widget?.[0].match(/\b(\d{2}):(\d{2})\b/)?.slice(1);
const timedLines = () => (working ? 1 : 0) + (widget?.length ?? 0);
function advance(milliseconds) {
  const target = now + milliseconds;
  for (;;) {
    const due = [...timers].sort((a, b) => a[1].at - b[1].at)[0];
    if (!due || due[1].at > target) break;
    now = due[1].at;
    due[1].at += due[1].delay;
    due[1].callback();
  }
  now = target;
}
emit("agent_start");
assert.equal(duration(), undefined);
assert.equal(widget, undefined);
assert.equal(timedLines(), 0);
advance(59999);
assert.equal(duration(), undefined);
assert.equal(widget, undefined);
assert.equal(timedLines(), 0);
advance(1);
assert.deepEqual(duration(), ["1m", "0s"]);
// Native streaming can derive an intent before tool_execution_start supplies it
// to extensions. Its deduplication then does not repaint the same intent.
ctx.ui.setWorkingMessage("Inspecting derived tool intent");
advance(1000);
assert.deepEqual(duration(), ["1m", "1s"]);
emit("tool_execution_start", { intent: "Inspecting derived tool intent" });
assert.equal(working, "Inspecting derived tool intent");
advance(29000);
assert.equal(working, "Inspecting derived tool intent");
advance(1000);
assert.deepEqual(duration(), ["1m", "31s"]);
advance(1000);
assert.deepEqual(duration(), ["1m", "32s"]);
emit("agent_start");
advance(60000);
assert.equal(timedLines(), 1);
advance(500);
emit("message_update", streamedIntent("Inspecting the active configuration"));
advance(8500);
emit("message_update", { ...streamedIntent("Inspecting the active configuration"),
  assistantMessageEvent: { type: "thinking_delta" } });
emit("message_update", streamedIntent(" Inspecting the active configuration... "));
advance(21499);
assert.equal(working, "Inspecting the active configuration");
advance(501);
assert.deepEqual(duration(), ["1m", "31s"]);
emit("tool_execution_start", { intent: "Checking the runtime state" });
advance(29000);
emit("tool_execution_start", { intent: "Checking the runtime state..." });
advance(999);
assert.equal(working, "Checking the runtime state");
advance(1);
assert.deepEqual(duration(), ["2m", "1s"]);
emit("message_update", { message: { role: "assistant", content: [] },
  assistantMessageEvent: { type: "text_delta" } });
advance(1000);
assert.deepEqual(duration(), ["2m", "2s"]);
emit("message_update", streamedIntent({ malformed: true }));
advance(1000);
assert.deepEqual(duration(), ["2m", "3s"]);
advance(121000);
assert.deepEqual(duration(), ["4m", "4s"]);
assert.equal(timedLines(), 1);
assert.equal(timers.size, 1);
emit("agent_end");
assert.deepEqual(duration(), ["4m", "4s"]);
assert.deepEqual(completion(), ["17", "48"]);
assert.equal(working, undefined);
assert.equal(timedLines(), 1);
assert.equal(timers.size, 0);
const completedWidget = [...widget];
advance(600000);
wallNow += 600000;
emit("agent_end");
assert.deepEqual(widget, completedWidget);
emit("agent_start");
assert.equal(duration(), undefined);
assert.equal(widget, undefined);
assert.equal(timedLines(), 0);
advance(115000);
emit("tool_execution_start", { intent: "Checking the runtime state" });
advance(29999);
assert.equal(working, "Checking the runtime state");
advance(1);
assert.deepEqual(duration(), ["2m", "25s"]);
wallNow = RealDate.UTC(2026, 0, 1, 0, 9);
emit("agent_end");
assert.deepEqual(duration(), ["2m", "25s"]);
assert.deepEqual(completion(), ["00", "09"]);
emit("agent_start");
advance(3599000);
assert.deepEqual(duration(), ["59m", "59s"]);
advance(1000);
assert.deepEqual(duration(), ["1h", "0m", "0s"]);
advance(123000);
emit("agent_end");
assert.deepEqual(duration(), ["1h", "2m", "3s"]);
emit("agent_start");
advance(9000);
assert.equal(duration(), undefined);
emit("agent_end");
assert.deepEqual(duration(), ["9s"]);
assert.equal(timedLines(), 1);
emit("agent_start");
advance(1000);
emit("agent_start");
assert.equal(timers.size, 1);
assert.equal(duration(), undefined);
emit("session_switch");
assert.equal(widget, undefined);
assert.equal(working, undefined);
assert.equal(timers.size, 0);
advance(120000);
emit("agent_end");
assert.equal(widget, undefined);
assert.equal(working, undefined);
emit("agent_start");
advance(70000);
emit("agent_end", { willContinue: true, awaitingAsyncWork: true });
assert.equal(widget, undefined, "a background wait must not publish a completion");
advance(30000);
assert.deepEqual(duration(), ["1m", "40s"]);
emit("agent_start");
advance(20000);
assert.deepEqual(duration(), ["2m", "0s"], "automatic continuation keeps the task's origin");
emit("agent_end", { willContinue: true });
advance(10000);
emit("agent_start");
advance(10000);
emit("agent_end");
assert.deepEqual(duration(), ["2m", "20s"]);
assert.equal(timers.size, 0);
emit("agent_start");
advance(5000);
emit("agent_end", { messages: [{ role: "assistant", stopReason: "aborted" }] });
assert.deepEqual(duration(), ["5s"]);
emit("agent_start");
advance(60000);
assert.deepEqual(duration(), ["1m", "0s"], "a new task must not inherit cancelled work");
emit("session_switch");
assert.equal(timers.size, 0);
emit("agent_start");
advance(70000);
emit("agent_end", { willContinue: true });
emit("input", { source: "extension", text: "continue" });
emit("agent_start");
advance(10000);
assert.deepEqual(duration(), ["1m", "20s"]);
emit("agent_end", { willContinue: true, awaitingAsyncWork: true });
emit("input", { source: "interactive", text: "A new task" });
emit("agent_start");
advance(60000);
assert.deepEqual(duration(), ["1m", "0s"]);
emit("session_shutdown");
assert.equal(timers.size, 0);
assert.equal(widget, undefined);
assert.equal(working, undefined);
console.log("PASS: single live duration, fixed completion time and timer cleanup");
"""
        result = subprocess.run(
            [shutil.which("bun"), "--no-install", "--eval", script, str(extension_path("composer"))],
            env=os.environ | {"TZ": "UTC"}, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
