"""Optional display failures must preserve the same OMP process and conversation."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import select
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import unittest

from test_support import OMP_BIN, extension_path, isolated_env, write_yaml

if os.name == "posix":
    import fcntl
    import pty
    import termios


@unittest.skipUnless(os.name == "posix" and OMP_BIN, "POSIX OMP TUI required")
class ExtensionIsolationTests(unittest.TestCase):
    @contextmanager
    def session(self, *extensions, final_stream_seconds=0, stream_chunks=False, final_delay=0):
        requests = []
        gate = threading.Event()
        gate.set()
        blocked = [None]
        with tempfile.TemporaryDirectory(prefix="omp-isolation-") as directory:
            root = Path(directory)
            (root / "input.txt").write_text("LOCAL_TOOL_RESULT\n")

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_POST(self):
                    requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                    turn = len(requests)
                    if turn == blocked[0] and not gate.wait(20):
                        self.send_error(504)
                        return
                    text = "BEFORE_TOOLS" if turn == 1 else "LIVE_BODY" if turn == 2 else f"FOLLOWUP_{turn}_OK"
                    if stream_chunks and turn >= 2:
                        text = ("STREAM_BODY " if turn == 2 else "FINAL_BODY ") + " ".join(f"chunk{n}" for n in range(24))
                    if turn == 3 and final_delay:
                        time.sleep(final_delay)
                    long_final = final_stream_seconds and turn == 1
                    if long_final:
                        text = "FINAL_STREAM_START\nFINAL_STREAM_END"
                    output = [{"type": "message", "id": f"msg_{turn}", "role": "assistant", "status": "completed",
                               "phase": "final_answer" if long_final or turn >= 3 else "commentary",
                               "content": [{"type": "output_text", "text": text, "annotations": []}]}]
                    if turn == 1 and not long_final:
                        output += [{"type": "function_call", "id": f"fc_{i}", "call_id": f"call_{i}", "name": "read",
                                    "status": "completed", "arguments": json.dumps({"path": str(root / "input.txt"), "i": "Reading fixture"})}
                                   for i in range(3)]
                    if turn == 2:
                        output.insert(0, {"type": "reasoning", "id": "rs_before", "summary": [{"type": "summary_text", "text": "Initial reasoning"}]})
                        output.append({"type": "reasoning", "id": "rs_after", "summary": [{"type": "summary_text", "text": "Continued reasoning"}]})
                    response = {"id": f"resp_{turn}", "object": "response", "status": "completed", "output": output,
                                "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}}
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()

                    def event(kind, **data):
                        self.wfile.write((f"event: {kind}\ndata: " + json.dumps({"type": kind, **data}) + "\n\n").encode())
                        self.wfile.flush()

                    try:
                        event("response.created", response=response | {"status": "in_progress", "output": []})
                        for index, item in enumerate(output):
                            initial = item | ({"summary": []} if item["type"] == "reasoning" else
                                              {"content": []} if item["type"] == "message" else {"arguments": ""})
                            event("response.output_item.added", output_index=index, item=initial)
                            if item["type"] == "reasoning":
                                event("response.reasoning_summary_part.added", output_index=index, item_id=item["id"], summary_index=0,
                                      part={"type": "summary_text", "text": ""})
                                event("response.reasoning_summary_text.delta", output_index=index, item_id=item["id"], summary_index=0,
                                      delta=item["summary"][0]["text"])
                                time.sleep(0.3)
                            elif item["type"] == "message":
                                if long_final:
                                    event("response.output_text.delta", output_index=index, item_id=item["id"], delta="FINAL_STREAM_START\n")
                                    time.sleep(final_stream_seconds)
                                    event("response.output_text.delta", output_index=index, item_id=item["id"], delta="FINAL_STREAM_END")
                                else:
                                    if stream_chunks and turn >= 2:
                                        for number, chunk in enumerate(text.split(" ")):
                                            event("response.output_text.delta", output_index=index, item_id=item["id"], delta=(" " if number else "") + chunk)
                                            time.sleep(0.4 if number % 6 == 5 else 0.12)
                                        time.sleep(0.5)
                                    else:
                                        event("response.output_text.delta", output_index=index, item_id=item["id"], delta=text)
                            else:
                                event("response.function_call_arguments.delta", output_index=index, item_id=item["id"], delta=item["arguments"])
                            event("response.output_item.done", output_index=index, item=item)
                        event("response.completed", response=response)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            write_yaml(root / "models.yml", {"providers": {"isolation": {
                "baseUrl": f"http://127.0.0.1:{server.server_port}/v1", "api": "openai-responses", "auth": "apiKey",
                "apiKey": "test-only-key", "models": [{"id": "fixture", "name": "Isolation Fixture", "reasoning": True,
                "input": ["text"], "contextWindow": 100000, "maxTokens": 1024}],
            }}})
            write_yaml(root / "config.yml", {
                "startup": {"setupWizard": False, "checkUpdate": False, "quiet": True},
                "display": {"hideToolActivity": True}, "hideThinkingBlock": True,
                "providers": {"cacheWarming": "off"}, "retry": {"enabled": False, "modelFallback": False},
                "compaction": {"enabled": False}, "completion": {"notify": "off"},
                "composer": {"shape": "dotfiles/claude-context"} if "composer" in extensions else {},
            })
            write_yaml(root / "shared.yml", {"display": {"hideToolActivity": True}})
            write_yaml(root / "keybindings.yml", {"app.tools.toggleVisibility": "Ctrl+O"})
            injector = root / "injector.ts"
            injector.write_text('''
import { AssistantMessageComponent } from "@oh-my-pi/pi-tui/chat/assistant-message";
import { TranscriptContainer } from "@oh-my-pi/pi-tui/chrome/transcript-container";
import { theme } from "@oh-my-pi/pi-tui";
import { toolRenderers } from "@oh-my-pi/pi-tui/tools";
import { lookup } from "@oh-my-pi/pi-coding-agent/config/registry";
import { writeFileSync } from "node:fs";
export default function(pi) {
 let grouping=false, queue=false, input=false, visibility=false, ask="";
 const describe=AssistantMessageComponent.prototype.describe;
 AssistantMessageComponent.prototype.describe=function(...args) {
   if(grouping) {grouping=false;throw new Error("Injected grouping display failure");}
   return describe.apply(this,args);
 };
 const bold=theme.bold;
 theme.bold=function(text) {
   if(queue && text.includes("▌")) {queue=false;throw new Error("Injected queue styling failure");}
   return bold.call(this,text);
 };
 const fill=theme.bgFill;
 theme.bgFill=function(color,text) {
   if(input && text.includes("INPUT_SURVIVES_FAILURE")) {input=false;throw new Error("Injected input styling failure");}
   return fill.call(this,color,text);
 };
 const hideTools=lookup("display.hideToolActivity");
 const override=hideTools.override;
 hideTools.override=function(...args) {
   if(visibility) {visibility=false;throw new Error("Injected visibility microtask failure");}
   return override.apply(this,args);
 };
 const askResult=toolRenderers.ask.renderResult;
 toolRenderers.ask.renderResult=function(...args) {
   if(ask==="factory") throw new Error("Injected Ask factory failure");
   if(ask==="render") return {render(){throw new Error("Injected Ask render failure");},invalidate(){}};
   return askResult.apply(this,args);
 };
 pi.registerCommand("inject-failure", {description:"Inject an isolated display failure",handler:(mode,ctx)=>{
   if(mode==="grouping") grouping=true;
   if(mode==="queue") queue=true;
   if(mode==="input") input=true;
   if(mode==="visibility") visibility=true;
   if(mode.startsWith("ask-")) {
     ask=mode.slice(4);
     pi.sendMessage({customType:"dotfiles.ask-history",content:"QUESTION: Storage mode\\nANSWER: Keep",display:true});
   }
   ctx.ui.setWidget("injection-pulse",["Fault armed: "+mode]);
 }});
 pi.registerCommand("capture-transcript", {description:"Inspect native transcript",handler:(_args,ctx)=>{
   ctx.ui.setWidget("capture",tui=>{
     const messages=tui.children.filter(c=>c instanceof TranscriptContainer).flatMap(c=>c.children.filter(m=>m instanceof AssistantMessageComponent).map(m=>m.render(80).map(r=>Bun.stripANSI(r))));
     writeFileSync(new URL("./snapshot.json",import.meta.url),JSON.stringify(messages));
     return {render:()=>[],invalidate(){}};
   });
   ctx.ui.setWidget("capture",undefined);
 }});
 pi.on("session_shutdown",()=>{
   AssistantMessageComponent.prototype.describe=describe;
   theme.bold=bold;theme.bgFill=fill;toolRenderers.ask.renderResult=askResult;
   hideTools.override=override;
 });
}
''')
            if stream_chunks:
                observer = root / "frames.ts"
                observer.write_text('''
import { TranscriptContainer } from "@oh-my-pi/pi-tui/chrome/transcript-container";
import { AssistantMessageComponent } from "@oh-my-pi/pi-tui/chat/assistant-message";
import { appendFileSync } from "node:fs";
export default function(pi) {
 pi.on("session_start",(_event,ctx)=>{
  ctx.ui.setWidget("frame-observer",tui=>{
   const seen=new WeakSet();
   tui.addPaintListener(()=>{
    for(const root of tui.children) if(root instanceof TranscriptContainer) {
     for(const child of root.children) if(child instanceof AssistantMessageComponent && !seen.has(child)) {
      seen.add(child);
      const render=child.render;
      child.render=function(width) {
       const rows=render.call(this,width);
       appendFileSync(new URL("./frames.jsonl",import.meta.url),JSON.stringify(rows.map(row=>Bun.stripANSI(row)))+"\\n");
       return rows;
      };
     }
    }
   });
   return {render:()=>[],invalidate(){}};
  });
  ctx.ui.setWidget("frame-observer",undefined);
 });
}
''')
            env = isolated_env(directory)
            env.update(PI_CODING_AGENT_DIR=directory, TERM="xterm-256color", NOTIFY_DRY_RUN="1")
            env["PI_CONFIG_FILES"] = str(root / "shared.yml")
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 45, 100, 0, 0))
            command = [OMP_BIN, "--cwd", directory, "--model", "isolation/fixture", "--tools", "read",
                       "--no-extensions", "-e", str(injector), "--no-skills", "--no-rules", "--no-lsp", "--no-title", "--thinking", "low"]
            for extension in extensions:
                command.extend(["-e", str(extension_path(extension))])
            if stream_chunks:
                command.extend(["-e", str(observer)])
            process = subprocess.Popen(command, env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
            os.close(slave)
            output = bytearray()

            def drain():
                if select.select([master], [], [], 0.05)[0]:
                    try:
                        output.extend(os.read(master, 65536))
                    except OSError:
                        pass

            def until(predicate, label, timeout=15):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    drain()
                    if predicate():
                        return
                    if process.poll() is not None:
                        if predicate():
                            return
                        break
                self.fail(f"{label}; exit={process.poll()}; output={output[-6000:].decode(errors='replace')}")

            def see(text):
                until(lambda: text.encode() in output, text)

            def send(text, submit=True):
                os.write(master, text.encode() + (b"\r" if submit else b""))

            def settled(turn, timeout=15):
                expected = "FINAL_STREAM_START\nFINAL_STREAM_END" if final_stream_seconds and turn == 1 else (
                    "LIVE_BODY" if turn == 2 else f"FOLLOWUP_{turn}_OK")
                if stream_chunks and turn >= 2:
                    expected = ("STREAM_BODY " if turn == 2 else "FINAL_BODY ") + " ".join(f"chunk{n}" for n in range(24))
                until(lambda: any(json.loads(line).get("message", {}).get("role") == "assistant" and
                      json.loads(line).get("message", {}).get("stopReason") == "stop" and
                      any(block.get("text") == expected
                          for block in json.loads(line)["message"].get("content", []))
                      for path in (root / "sessions").rglob("*.jsonl") for line in path.read_text().splitlines()), "settled reply", timeout)

            try:
                see("Isolation Fixture")
                yield root, process, requests, gate, blocked, send, see, until, settled, output
            finally:
                gate.set()
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                os.close(master)
                server.shutdown()
                server.server_close()

    def test_bundle_preserves_input_and_grouping_after_ask_styling_failure(self):
        with self.session("composer", "transcript-grouping", "ask-history", "skill-completion", "model-switch") as (
                root, process, requests, gate, blocked, send, see, until, settled, output):
            send("/inject-failure ask-factory")
            see("ANSWER: Keep")
            see("Ask history styling disabled after an error")
            send("BUNDLE_INPUT_UNCHANGED ￥100")
            settled(2)
            self.assertIn("BUNDLE_INPUT_UNCHANGED ￥100", json.dumps(requests[0], ensure_ascii=False))
            self.assertNotIn("QUESTION: Storage mode", json.dumps(requests))
            send("/capture-transcript")
            until(lambda: (root / "snapshot.json").exists(), "bundle transcript after Ask failure")
            rows = json.loads((root / "snapshot.json").read_text())
            body = "\n".join(row for message in rows for row in message)
            self.assertIn("3 tools", body)
            self.assertIn("LIVE_BODY", body)
            send("Continue with the other extensions still active.")
            settled(3)
            self.assertNotIn("Grouping disabled", output.decode(errors="replace"))
            self.assertNotIn("Composer styling disabled", output.decode(errors="replace"))

    def test_grouping_live_thinking_and_fault_do_not_interrupt_followups(self):
        with self.session("transcript-grouping") as (root, process, requests, gate, blocked, send, see, until, settled, output):
            send("Exercise hidden thinking and grouping.")
            settled(2)
            send("/capture-transcript")
            until(lambda: (root / "snapshot.json").exists(), "grouped native transcript")
            snapshot = json.loads((root / "snapshot.json").read_text())
            body = "\n".join(row for message in snapshot for row in message)
            self.assertIn("3 tools", body)
            self.assertIn("LIVE_BODY", body)
            self.assertNotIn("Grouping disabled", output.decode(errors="replace"))
            send("/inject-failure grouping")
            see("Grouping disabled after an error")
            send("Continue after the display failure.")
            settled(3)
            send("/grouping")
            see("Grouping is disabled after an error")
            send("/new")
            see("New session started")
            send("Continue in a new conversation.")
            settled(4)
            self.assertIsNone(process.poll())
            self.assertNotIn("dotfiles.grouping", json.dumps(requests))

    def test_composer_and_queue_faults_preserve_input_and_queued_delivery(self):
        with self.session("composer") as (root, process, requests, gate, blocked, send, see, until, settled, output):
            send("/inject-failure input")
            see("Fault armed: input")
            send("INPUT_SURVIVES_FAILURE", submit=False)
            see("Composer styling disabled after an error")
            send("")
            settled(2)
            self.assertIn("INPUT_SURVIVES_FAILURE", json.dumps(requests[0]))
            blocked[0] = 3
            gate.clear()
            send("Start a blocking turn.")
            until(lambda: len(requests) == 3, "blocked request")
            send("/inject-failure queue")
            see("Fault armed: queue")
            send("QUEUED_MESSAGE_SURVIVES")
            see("Queue enhancements disabled after an error")
            see("QUEUED_MESSAGE_SURVIVES")
            gate.set()
            settled(4)
            last_input = requests[-1]["input"]
            user_texts = [part.get("text", "") for item in last_input if item.get("role") == "user"
                          for part in item.get("content", []) if part.get("type") == "input_text"]
            self.assertEqual(sum(text.count("QUEUED_MESSAGE_SURVIVES") for text in user_texts), 1)
            self.assertIsNone(process.poll())

    def test_visibility_microtask_fault_preserves_native_toggle_and_followup(self):
        with self.session("composer") as (root, process, requests, gate, blocked, send, see, until, settled, output):
            send("/inject-failure visibility")
            see("Fault armed: visibility")
            send("\x0f", submit=False)
            see("Queue enhancements disabled after an error")
            send("Continue after the visibility microtask failure.")
            settled(2)
            send("/new")
            see("New session started")
            send("Continue after switching sessions.")
            settled(3)
            self.assertIsNone(process.poll())

    def test_ask_factory_and_lazy_render_faults_preserve_answers_and_followup(self):
        for mode in ("factory", "render"):
            with self.subTest(mode=mode), self.session("ask-history") as (root, process, requests, gate, blocked, send, see, until, settled, output):
                send(f"/inject-failure ask-{mode}")
                see("ANSWER: Keep")
                see("Ask history styling disabled after an error")
                send("Continue after the Ask display failure.")
                settled(2)
                self.assertIsNone(process.poll())
                self.assertNotIn("QUESTION: Storage mode", json.dumps(requests))

    def test_streamed_gap_marker_stays_visible_on_every_frame(self):
        self.check_streamed_marker(final=False)

    def test_streamed_final_marker_stays_visible_on_every_frame(self):
        self.check_streamed_marker(final=True)

    def check_streamed_marker(self, final):
        with self.session("transcript-grouping", stream_chunks=True, final_delay=121 if final else 0) as (root, process, requests, gate, blocked, send, see, until, settled, output):
            send("Stream commentary after tool work.")
            settled(2)
            if final:
                send("Stream a final after the two-minute threshold.")
                until(lambda: len(requests) == 3, "final request")
                (root / "frames.jsonl").unlink(missing_ok=True)
                until(lambda: (root / "frames.jsonl").exists() and any("FINAL_BODY" in line and "chunk23" in line for line in (root / "frames.jsonl").read_text().splitlines()), "final streaming frames", timeout=145)
                settled(3)
            marker = "══ Done" if final else "3 tools"
            frames = [json.loads(line) for line in (root / "frames.jsonl").read_text().splitlines()]
            visible = [rows for rows in frames if any(("FINAL_BODY" if final else "STREAM_BODY") in row for row in rows)]
            # Inspect actual render calls during streaming, not a post-completion snapshot.
            self.assertGreaterEqual(len({"\n".join(rows) for rows in visible}), 5)
            missing = [rows for rows in visible if not any(marker in row for row in rows)]
            self.assertFalse(missing, f"{marker} disappeared in {len(missing)}/{len(visible)} streaming frames; first={missing[:1]}")
            self.assertNotIn("Grouping disabled", output.decode(errors="replace"))
            print(f"Real OMP: {marker} stable in all {len(visible)} streaming frames")
            send("Continue after streaming.")
            settled(4 if final else 3)

    def test_final_crossing_two_minutes_during_stream_gets_completed_marker(self):
        with self.session("transcript-grouping", final_stream_seconds=121) as (root, process, requests, gate, blocked, send, see, until, settled, output):
            started = time.monotonic()
            send("Stream a final answer across the two-minute threshold.")
            see("FINAL_STREAM_START")
            snapshot_path = root / "snapshot.json"
            send("/capture-transcript")
            until(snapshot_path.exists, "early final snapshot")
            self.assertNotIn("Done", snapshot_path.read_text())
            settled(1, timeout=145)
            snapshot_path.unlink()
            send("/capture-transcript")
            until(snapshot_path.exists, "completed final snapshot")
            rows = [row for message in json.loads(snapshot_path.read_text()) for row in message]
            marker = next(row for row in rows if "Done" in row)
            self.assertRegex(marker, r"^ ══ Done · 2m\d{2}s ═+$")
            self.assertNotIn("⟡", "\n".join(rows))
            self.assertIn("FINAL_STREAM_END", "\n".join(rows))
            self.assertGreaterEqual(time.monotonic() - started, 120)
            self.assertNotIn("Grouping disabled", output.decode(errors="replace"))
            send("Continue after the long final.")
            settled(2)
            self.assertIsNone(process.poll())
            print(f"Real OMP: final started before threshold, completed after {time.monotonic() - started:.1f}s -> {marker.strip()}")


if __name__ == "__main__":
    unittest.main()
