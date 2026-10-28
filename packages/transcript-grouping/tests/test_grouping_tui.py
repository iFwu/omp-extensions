"""Exercise hidden tools, final boundaries, and independent toggles in the real OMP TUI."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import select
import re
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


@unittest.skipUnless(os.name == "posix" and OMP_BIN, "POSIX OMP TUI is not available")
class GroupingTuiTests(unittest.TestCase):
    def test_hidden_work_final_boundary_and_independent_toggle(self):
        requests = []
        fixture_root = None
        timing = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append(request)
                turn = len(requests)
                output = []

                def text(value, phase=None):
                    item = {"type": "message", "id": f"msg_{turn}_{len(output)}", "role": "assistant",
                            "status": "completed", "content": [{"type": "output_text", "text": value, "annotations": []}]}
                    if phase:
                        item["phase"] = phase
                    output.append(item)

                if turn < 3:
                    text("FIRST_COMMENTARY" if turn == 1 else "SECOND_COMMENTARY", "commentary")
                    for number in range(3 if turn == 1 else 10):
                        if turn == 2 and number == 9:
                            output.append({"type": "function_call", "id": "fc_blocking", "call_id": "call_blocking",
                                           "name": "grouping_wait", "status": "completed", "arguments": "{}"})
                            continue
                        target = fixture_root / ("missing.txt" if turn == 1 and number == 1 else "input.txt")
                        output.append({"type": "function_call", "id": f"fc_{turn}_{number}",
                                       "call_id": f"call_{turn}_{number}", "name": "read", "status": "completed",
                                       "arguments": json.dumps({"path": str(target), "i": "Reading local fixture"})})
                elif turn == 3:
                    text("THIRD_COMMENTARY", "commentary")
                    text("AFTER_LONG_GAP", "commentary")
                    for number in range(2):
                        target = fixture_root / ("missing.txt" if number == 1 else "input.txt")
                        output.append({"type": "function_call", "id": f"fc_{turn}_{number}",
                                       "call_id": f"call_{turn}_{number}", "name": "read", "status": "completed",
                                       "arguments": json.dumps({"path": str(target), "i": "Reading final segment fixture"})})
                elif turn == 4:
                    text("FINAL_DONE", "final_answer")
                elif turn == 5:
                    text("UNPHASED_DONE")
                else:
                    text("RESUMED_DONE")
                response = {"id": f"resp_{turn}", "object": "response", "status": "completed", "output": output,
                            "usage": {"input_tokens": 3000, "output_tokens": 100, "total_tokens": 3100}}
                events = [("response.created", {"response": response | {"status": "in_progress", "output": []}})]
                for index, item in enumerate(output):
                    added = item | ({"content": []} if item["type"] == "message" else {"arguments": ""})
                    events.append(("response.output_item.added", {"output_index": index, "item": added}))
                    if item["type"] == "message":
                        events.append(("response.output_text.delta", {"output_index": index, "item_id": item["id"], "delta": item["content"][0]["text"]}))
                    else:
                        events.append(("response.function_call_arguments.delta", {"output_index": index, "item_id": item["id"], "delta": item["arguments"]}))
                    events.append(("response.output_item.done", {"output_index": index, "item": item}))
                events.append(("response.completed", {"response": response}))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for kind, data in events:
                    if turn == 3 and kind == "response.output_item.added" and data["output_index"] == 1:
                        started = time.monotonic()
                        time.sleep(12)
                        timing["long_gap"] = time.monotonic() - started
                    if turn == 4 and kind == "response.output_item.added" and data["output_index"] == 0:
                        timing["final_gap"] = time.monotonic() - timing["last_commentary"]
                    self.wfile.write(f"event: {kind}\ndata: {json.dumps({'type': kind} | data)}\n\n".encode())
                    self.wfile.flush()
                    if turn == 3 and kind == "response.output_text.delta" and data["output_index"] == 1:
                        timing["last_commentary"] = time.monotonic()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture_root = root
            (root / "input.txt").write_text("grouping fixture\n")
            snapshot = root / "screen.json"
            observer = root / "observer.ts"
            observer.write_text('''
import { TranscriptContainer } from "@oh-my-pi/pi-tui/chrome/transcript-container";
import { AssistantMessageComponent } from "@oh-my-pi/pi-tui/chat/assistant-message";
import { writeFileSync } from "node:fs";
export default function(pi) {
  pi.registerTool({name:"grouping_wait", label:"Fixture wait", description:"Wait at the external tool boundary",
    parameters:{type:"object",properties:{}},
    async execute() {
      await new Promise(resolve=>setTimeout(resolve,121000));
      return {content:[{type:"text",text:"Foreground wait completed"}],details:{}};
    }});
  pi.registerCommand("grouping-snapshot", {description:"Read rendered transcript for the offline smoke",handler:(args,ctx)=>{
    ctx.ui.setWidget("snapshot",tui=>{
      const roots=tui.children.filter(root=>root instanceof TranscriptContainer);
      const messages=roots.flatMap(root=>root.children.filter(child=>child instanceof AssistantMessageComponent).map(child=>child.render(Number(args) || 80).map(row=>Bun.stripANSI(row))));
      writeFileSync(''' + json.dumps(str(snapshot)) + ''',JSON.stringify(messages));
      return {render:()=>[],invalidate(){}};
    });
    ctx.ui.setWidget("snapshot",undefined);
  }});
}
''')
            write_yaml(root / "models.yml", {"providers": {"grouping-test": {
                "baseUrl": f"http://127.0.0.1:{server.server_port}/v1", "api": "openai-responses",
                "auth": "apiKey", "apiKey": "test-only-key", "models": [{"id": "fixture", "name": "Fixture",
                "reasoning": False, "input": ["text"], "contextWindow": 100000, "maxTokens": 1024}],
            }}})
            write_yaml(root / "config.yml", {
                "startup": {"setupWizard": False, "checkUpdate": False, "quiet": True},
                "hideThinkingBlock": True, "display": {"hideToolActivity": True, "smoothStreaming": False},
                "tools": {"approvalMode": "yolo"}, "retry": {"enabled": False, "modelFallback": False},
                "providers": {"cacheWarming": "off"}, "compaction": {"enabled": False},
                "completion": {"notify": "off"}, "terminal": {"showImages": False},
                "tui": {"autoGraph": "off"},
            })
            env = isolated_env(directory)
            env.update(PI_CODING_AGENT_DIR=directory, TERM="xterm-256color", NOTIFY_DRY_RUN="1")
            env.pop("PI_CONFIG_FILES", None)
            write_yaml(root / "keybindings.yml", {"app.tools.expand": "Ctrl+]", "app.tools.toggleVisibility": "Ctrl+O",
                                                       "app.session.observe": [], "app.exit": []})
            def launch(resume=False):
                master, slave = pty.openpty()
                self.addCleanup(os.close, master)
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 80, 0, 0))
                command = [OMP_BIN, "--cwd", directory, "--model", "grouping-test/fixture", "--tools", "read,grouping_wait",
                           "--no-extensions", "-e", str(extension_path("transcript-grouping")), "-e", str(observer),
                           "--no-skills", "--no-rules", "--no-lsp", "--no-title", "--thinking", "off",
                           "--session-dir", str(root / "sessions")]
                if resume:
                    command.append("--continue")
                process = subprocess.Popen(command, env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
                os.close(slave)
                return process, master

            process, master = launch()
            output = bytearray()

            def drain(seconds=0.2):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if select.select([master], [], [], max(0, deadline - time.monotonic()))[0]:
                        try:
                            chunk = os.read(master, 65536)
                        except OSError:
                            break
                        if not chunk:
                            break
                        output.extend(chunk)

            def wait_for(text, timeout=60):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    drain()
                    if text.encode() in output:
                        return
                    if process.poll() is not None:
                        break
                self.fail(f"Missing {text!r}; output: {output[-5000:].decode(errors='replace')}")

            def capture(width=80):
                snapshot.unlink(missing_ok=True)
                os.write(master, f"/grouping-snapshot {width}\r".encode())
                deadline = time.monotonic() + 10
                while not snapshot.exists() and time.monotonic() < deadline:
                    drain()
                self.assertTrue(snapshot.exists(), output[-5000:].decode(errors="replace"))
                return json.loads(snapshot.read_text())

            def stop():
                if process.poll() is None:
                    os.write(master, b"\x03\x03")
                    deadline = time.monotonic() + 5
                    while process.poll() is None and time.monotonic() < deadline:
                        drain()
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)

            try:
                wait_for("Fixture")
                os.write(master, b"Exercise grouping.\r")
                wait_for("FINAL_DONE", timeout=200)
                drain(0.5)
                messages = capture()
                rendered = "\n".join(row for message in messages for row in message)
                compact_message = next(message for message in messages if any("SECOND_COMMENTARY" in row for row in message))
                compact_body = [row for row in compact_message if "3 tools" not in row]
                self.assertIn("3 tools", rendered)
                self.assertIn("10 tools", rendered)
                self.assertIn("1 failed", rendered)
                long_gap = rendered[rendered.index("SECOND_COMMENTARY"):rendered.index("THIRD_COMMENTARY")].splitlines()
                long_marker = next(row for row in long_gap if "⟡" in row)
                blocking = re.search(r"^ 2m\d{2}s · ⟡ (\d+)m(\d{2})s · 10 tools", long_marker)
                self.assertIsNotNone(blocking, long_marker)
                self.assertGreaterEqual(int(blocking[1]) * 60 + int(blocking[2]), 120)
                self.assertLess(int(blocking[1]) * 60 + int(blocking[2]), 130)
                provider_gap = rendered[rendered.index("THIRD_COMMENTARY"):rendered.index("AFTER_LONG_GAP")]
                self.assertNotIn("⟡", provider_gap)
                self.assertGreaterEqual(timing["long_gap"], 12)
                self.assertLess(timing["final_gap"], 30)
                final_message = next(message for message in messages if any("FINAL_DONE" in row for row in message))
                final_line = next(row for row in final_message if "══ Done" in row)
                duration = re.search(r"^ ══ Done · (\d+)m(\d{2})s · 2 tools · 1 failed ═+$", final_line.rstrip())
                self.assertIsNotNone(duration, final_line)
                self.assertGreaterEqual(int(duration[1]) * 60 + int(duration[2]), 120)
                self.assertNotIn("⟡", final_line)
                fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 48, 0, 0))
                drain(0.3)
                mobile = "\n".join(row for message in capture(48) for row in message)
                self.assertIn(" ══ Done", mobile)
                self.assertIn("1 failed", mobile)
                self.assertRegex(mobile, r"(?m)^ 2m\d{2}s · ⟡")
                self.assertIn("FINAL_DONE", mobile)
                self.assertTrue(all(len(row) <= 48 for row in mobile.splitlines()))
                fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 80, 0, 0))
                drain(0.3)
                os.write(master, b"\x13")
                wait_for("Grouping off")
                off_messages = capture()
                off = "\n".join(row for message in off_messages for row in message)
                unmarked_body = next(message for message in off_messages if any("SECOND_COMMENTARY" in row for row in message))
                self.assertEqual([row.rstrip() for row in compact_body], [row.rstrip() for row in unmarked_body])
                self.assertNotIn("⟡", off)
                self.assertNotIn("══ Done", off)
                self.assertIn("FINAL_DONE", off)
                os.write(master, b"Unphased answer.\r")
                wait_for("UNPHASED_DONE")
                os.write(master, b"/grouping\r")
                wait_for("Grouping on")
                messages = capture()
                self.assertNotIn("══", "\n".join(messages[-1]))
                self.assertIn("══ Done", "\n".join(row for message in messages for row in message))
                os.write(master, b"\x0f")
                drain(0.3)
                self.assertIn("══ Done", "\n".join(row for message in capture() for row in message))
                os.write(master, b"\x0f")
                drain(0.3)
                output.clear()
                os.write(master, b"\x13")
                wait_for("Grouping off")
                stop()
                session_file = next((root / "sessions").rglob("*.jsonl"))
                entries = [json.loads(line) for line in session_file.read_text().splitlines() if line.strip()]
                grouping_types = {"dotfiles.grouping", "dotfiles.grouping-enabled"}
                self.assertEqual([entry for entry in entries if entry.get("customType") in grouping_types], [])
                legacy = [
                    {"type": "custom", "id": "legacy-grouping", "parentId": entries[-1]["id"],
                     "timestamp": "2026-01-01T00:00:00.000Z", "customType": "dotfiles.grouping", "data": {"retired": True}},
                    {"type": "custom", "id": "legacy-toggle", "parentId": "legacy-grouping",
                     "timestamp": "2026-01-01T00:00:00.000Z", "customType": "dotfiles.grouping-enabled", "data": {"enabled": False}},
                ]
                session_file.write_text("\n".join(json.dumps(entry) for entry in entries + legacy) + "\n")
                process, master = launch(resume=True)
                output.clear()
                wait_for("Fixture")
                restored = "\n".join(row for message in capture() for row in message)
                self.assertNotIn("══ Done", restored)
                self.assertIn("UNPHASED_DONE", restored)
                os.write(master, b"/grouping\r")
                wait_for("Grouping off")
                restored = "\n".join(row for message in capture() for row in message)
                self.assertNotIn("══ Done", restored)
                self.assertNotIn("⟡", restored)
                os.write(master, b"Continue after resuming.\r")
                wait_for("RESUMED_DONE")
                resumed_reply = "\n".join(capture()[-1])
                self.assertNotIn("══ Done", resumed_reply)
                self.assertIn("RESUMED_DONE", resumed_reply)
                self.assertEqual(len(requests), 6)
                self.assertNotIn("⟡", json.dumps(requests, ensure_ascii=False))
                self.assertNotIn("══ Done", json.dumps(requests, ensure_ascii=False))
                self.assertNotIn("dotfiles.grouping", json.dumps(requests))
                stop()
                entries = [json.loads(line) for line in session_file.read_text().splitlines() if line.strip()]
                self.assertEqual([entry for entry in entries if entry.get("customType") in grouping_types], legacy)
                print(f"Real OMP: foreground wait -> {long_marker.strip()}; {timing['long_gap']:.1f}s provider wait excluded; "
                      f"{timing['final_gap']:.1f}s final gap -> {final_line.strip()}")
            finally:
                stop()


if __name__ == "__main__":
    unittest.main()
