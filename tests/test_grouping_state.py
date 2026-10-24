"""Grouping boundaries use hidden work, not streamed chunks or repaint timing."""
import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("bun"), "Bun is not installed")
class GroupingStateTests(unittest.TestCase):
    def test_boundaries_finality_and_repeated_events(self):
        script = r'''
import assert from "node:assert/strict";
import { GroupingState } from "./src/grouping-state.ts";
let now = 0;
const state = new GroupingState(() => now);
let serial = 0;
function message(text, phase, stopReason = "toolUse") {
  return { role: "assistant", timestamp: ++serial, provider: "fixture", model: "test", responseId: String(serial), stopReason,
    content: [{ type: "text", text, textSignature: phase ? JSON.stringify({ v: 1, id: String(serial), phase }) : "opaque" }] };
}
const see = m => { state.observe(m, true); return state.find(m, 0); };
state.begin();
const first = message("start", "commentary");
assert.equal(see(first).marker, undefined);
now = 9000;
state.observe({ ...first, content: [{ ...first.content[0], text: "start plus streamed text" }] });
state.textEnded();
now = 18000;
assert.equal(see(message("continuous", "commentary")).marker, undefined);
for (let n = 0; n < 3; n++) { state.toolStarted(String(n)); state.toolFinished(String(n), n === 1); }
state.toolFinished("1", true);
const short = message("short", "commentary");
assert.deepEqual(see(short).marker, { kind: "gap", seconds: 0, tools: 3, failures: 1 });
for (let n = 3; n < 13; n++) state.toolStarted(String(n));
assert.deepEqual(see(message("busy gap", "commentary")).marker, { kind: "gap", seconds: 0, tools: 10, failures: 0 });
for (let n = 3; n < 13; n++) state.toolFinished(String(n), false);
now += 10000;
const timeGap = see(message("time gap", "commentary")).marker;
assert.equal(timeGap.kind, "gap");
assert.equal(timeGap.blocking, undefined);
// Tool time before the previous text ended belongs to that text, not to the following gap.
state.toolStarted("blocking-first");
now += 20000; state.toolFinished("blocking-first", false);
now += 60000; state.toolStarted("blocking-second"); state.toolStarted("blocking-second");
now += 40000;
const phase = see(message("time phase", "commentary")).marker;
assert.deepEqual(phase, { kind: "phase", seconds: 120, tools: 2, failures: 0, blocking: 60 });
state.toolFinished("blocking-second", false);
const final = message("final", "final_answer", "stop");
assert.deepEqual(see(final).marker, { kind: "final", seconds: 148, tools: 0, failures: 0 });
now += 2000;
state.finish(final);
assert.equal(state.find(final, 0).marker.seconds, 150);
now += 10000;
state.finish(final);
assert.equal(state.find(final, 0).marker.seconds, 150);
state.begin();
assert.equal(see(message("new prompt", "commentary")).marker, undefined);
const unknown = message("unphased final", undefined, "stop");
assert.equal(see(unknown).marker, undefined);
state.finish(unknown);
assert.equal(state.find(unknown, 0).marker.kind, "final");
state.begin();
const solo = message("solo final", "final_answer", "stop");
see(solo); state.finish(solo);
assert.equal(state.find(solo, 0).marker.kind, "final");
for (const reason of ["error", "aborted", "length"]) {
  state.begin();
  const incomplete = message(reason, undefined, reason);
  see(incomplete); state.finish(incomplete);
  assert.equal(state.find(incomplete, 0).marker, undefined);
}
state.begin();
const commentary = message("not final", "commentary", "stop");
see(commentary); state.finish(commentary);
assert.equal(state.find(commentary, 0).marker, undefined);
state.begin();
const mixed = message("preamble", "commentary");
see(mixed);
const text = { type: "text", text: "final after tool", textSignature: JSON.stringify({v:1,id:"final",phase:"final_answer"}) };
mixed.content.push({type:"toolCall",id:"call",name:"read",arguments:{}}, text);
state.observe(mixed);
assert.equal(state.find({...mixed,content:[text]},0).marker.kind,"final");
state.begin();
const repeated = message("same words", "commentary");
see(repeated);
repeated.content.push({ type: "text", text: "same words", textSignature: JSON.stringify({v:1,id:"second",phase:"final_answer"}) });
state.observe(repeated);
assert.equal(state.find(repeated,0).marker,undefined);
assert.equal(state.find(repeated,1).marker.kind,"final");
for (const [elapsed, tools, kind] of [
  [9999, 0, undefined], [10000, 0, "gap"], [20000, 10, "gap"],
  [0, 100, "gap"], [119999, 0, "gap"], [120000, 0, "phase"], [120001, 3, "phase"],
]) {
  state.begin();
  see(message("before boundary", "commentary"));
  for (let n = 0; n < tools; n++) state.toolStarted(String(n));
  now += elapsed;
  assert.equal(see(message("after boundary", "commentary")).marker?.kind, kind, `${elapsed}ms / ${tools} tools`);
}
console.log("PASS: time/tool thresholds, deduplication, finality, reset and native text slices");
'''
        result = subprocess.run([shutil.which("bun"), "--no-install", "--eval", script],
                                cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_blocking_time_unions_calls_and_excludes_background_lifetime(self):
        script = r'''
import assert from "node:assert/strict";
import { GroupingState } from "./src/grouping-state.ts";
let now = 0, serial = 0;
const state = new GroupingState(() => now);
const text = () => {
  const message = {role:"assistant", timestamp:++serial, provider:"fixture", model:"test", stopReason:"toolUse",
    content:[{type:"text",text:String(serial)}]};
  state.observe(message, true);
  return state.find(message, 0)?.marker;
};
state.begin(); text();
now = 1000; state.toolStarted("a");
now = 2000; state.toolStarted("b"); state.toolStarted("a");
now = 4000; state.toolFinished("a", false);
now = 6000; state.toolFinished("b", true); state.toolFinished("b", true);
now = 7000; state.toolStarted("background-launch");
now = 8000; state.toolFinished("background-launch", false);
// The job keeps running, but only a later foreground wait blocks the agent.
now = 90000; state.toolStarted("wait");
now = 95000; state.toolFinished("wait", false);
now = 130000;
assert.deepEqual(text(), {kind:"phase",seconds:130,tools:4,failures:1,blocking:11});
// A completed background job or unmatched duplicate end adds no waiting time.
now = 150000; state.toolFinished("background-launch", false);
now = 260000;
assert.deepEqual(text(), {kind:"phase",seconds:130,tools:0,failures:0});
state.toolStarted("crossing");
now = 265000; text();
now = 275000; state.toolFinished("crossing", false);
now = 390000;
assert.equal(text().blocking, 10);
state.toolStarted("abandoned");
state.finish();
state.begin(); text();
now = 520000;
assert.deepEqual(text(), {kind:"phase",seconds:130,tools:0,failures:0});
console.log("PASS: overlapping calls, background handoff, explicit wait, clipping, duplicate ends and reset");
'''
        result = subprocess.run([shutil.which("bun"), "--no-install", "--eval", script],
                                cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_final_duration_tracks_whole_turn_including_streamed_output(self):
        script = r'''
import assert from "node:assert/strict";
import { GroupingState } from "./src/grouping-state.ts";
for (const phase of ["final_answer", "late", undefined]) {
  let now = 0;
  const state = new GroupingState(() => now);
  const message = (timestamp, text, phase, stopReason = "toolUse") => ({
    role: "assistant", timestamp, provider: "fixture", model: "test", stopReason,
    content: [{type: "text", text, textSignature: phase ? JSON.stringify({v: 1, phase}) : "opaque"}],
  });
  state.begin();
  now = 5000;
  state.observe(message(1, "first commentary", "commentary"), true);
  state.toolStarted("old");
  state.toolFinished("old", true);
  now = 100000;
  state.observe(message(2, "last commentary", "commentary"), true);
  now = 105000;
  state.textEnded();
  state.toolStarted("new-1");
  state.toolFinished("new-1", false);
  state.toolStarted("new-2");
  state.toolFinished("new-2", true);
  state.toolFinished("new-2", true);
  now = 140000;
  const final = message(3, "final", phase === "final_answer" ? phase : undefined, "stop");
  state.observe(final, true);
  assert.equal(state.find(final, 0).marker.seconds, phase === "final_answer" ? 140 : 35);
  assert.equal(state.find(final, 0).marker.tools, 2);
  assert.equal(state.find(final, 0).marker.failures, 1);
  now = 150000;
  final.content[0].text += " output continues";
  if (phase === "late") final.content[0].textSignature = JSON.stringify({v: 1, phase: "final_answer"});
  state.observe(final);
  state.textEnded();
  now = 160000;
  state.finish(final);
  assert.deepEqual(state.find(final, 0).marker, {kind: "final", seconds: 160, tools: 2, failures: 1});
}
let now = 0;
const state = new GroupingState(() => now);
state.begin();
now = 32000;
const only = {role: "assistant", timestamp: 1, provider: "fixture", model: "test", stopReason: "stop",
  content: [{type: "text", text: "only final", textSignature: JSON.stringify({v: 1, phase: "final_answer"})}]};
state.observe(only, true);
now = 45000;
state.finish(only);
assert.equal(state.find(only, 0).marker.seconds, 45);
'''
        result = subprocess.run([shutil.which("bun"), "--no-install", "--eval", script],
                                cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_final_marker_survives_response_id_added_after_streaming(self):
        script = r'''
import assert from "node:assert/strict";
import { GroupingState } from "./src/grouping-state.ts";
let now = 0;
const state = new GroupingState(() => now);
state.begin();
now = 120000;
const streamed = {role:"assistant", timestamp:123, provider:"fixture", model:"test", stopReason:"stop",
  content:[{type:"text",text:"final text",textSignature:JSON.stringify({v:1,id:"msg_final",phase:"final_answer"})}]};
state.observe(streamed, true);
const persisted = {...streamed, responseId:"resp_assigned_after_stream"};
assert.equal(state.find(persisted,0)?.marker?.kind,"final");
assert.equal(state.awaitingFinal(persisted),true);
now = 125000;
state.finish(persisted);
assert.equal(state.find(persisted,0)?.marker?.seconds,125);
assert.equal(state.awaitingFinal(persisted),false);
'''
        result = subprocess.run([shutil.which("bun"), "--no-install", "--eval", script],
                                cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_group_markers_survive_lagging_display_prefixes_and_native_slices(self):
        script = r'''
import assert from "node:assert/strict";
import { GroupingState } from "./src/grouping-state.ts";
for (const signed of [false, true]) for (const kind of ["gap", "phase", "final"]) {
  let now = 0;
  const state = new GroupingState(() => now);
  const text = (value, id, phase = "commentary") => ({type:"text", text:value,
    ...(signed ? {textSignature:JSON.stringify({v:1,id,phase})} : {})});
  const first = text("same prefix before tools", "first");
  const message = {role:"assistant", timestamp:1, provider:"fixture", model:"test", stopReason:"toolUse", content:[first]};
  state.begin();
  state.observe(message, true);
  state.toolStarted("call");
  now = kind === "gap" ? 15000 : 125000;
  const second = text("same prefix after tools and more streamed text", "second", kind === "final" ? "final_answer" : "commentary");
  message.content.push({type:"toolCall",id:"call",name:"read",arguments:{}}, second);
  state.observe(message);
  if (kind === "final" && !signed) state.finish({...message, content:[first, second], stopReason:"stop"});
  for (let length = 1; length <= second.text.length; length++) {
    const partial = {...second, text:second.text.slice(0,length)};
    // Both text blocks remain when tools are hidden; overlapping prefixes must not
    // transfer the second block's marker to the first block.
    const display = {...message, content:[first,partial]};
    assert.equal(state.find(display,0)?.marker,undefined);
    assert.equal(state.find(display,1)?.marker?.kind,kind,`${signed}/${kind}/${length}`);
    if (signed) assert.equal(state.find({...message,content:[partial]},0)?.marker?.kind,kind);
  }
  assert.equal(state.find({...message, content:[{...second,text:"unrelated text"}]},0),undefined);
}
'''
        result = subprocess.run([shutil.which("bun"), "--no-install", "--eval", script],
                                cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
