"""Keep Ask answers in history without unhiding tools or duplicating model input."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import unittest

import pexpect
from pexpect.fdpexpect import fdspawn
import pyte

from test_support import OMP_BIN, extension_path, isolated_env, write_yaml

if os.name == "posix":
    import fcntl
    import pty
    import termios


@unittest.skipUnless(OMP_BIN, "OMP is not installed")
class AskHistoryTests(unittest.TestCase):
    def test_native_answers_survive_resume_without_duplicate_model_context(self):
        self.exercise_history()

    @unittest.skipUnless(os.name == "posix", "POSIX OMP TUI required")
    def test_native_form_and_legacy_answers_render_after_resume(self):
        self.exercise_history(native_form=True)

    def exercise_history(self, native_form=False):
        received = []
        html = """<form>
<fieldset><legend>Choose the storage mode</legend>
<label><input type="radio" name="choice" value="keep" checked>Keep</label>
<label><input type="radio" name="choice" value="change">Change</label></fieldset>
<fieldset><legend>Choose features</legend>
<label><input type="checkbox" name="features" value="search">Search</label>
<label><input type="checkbox" name="features" value="export">Export</label></fieldset>
<label>Add feedback<input name="feedback"></label>
</form>"""

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append(body)
                number = len(received)
                if number == 1:
                    item = {"id": "fc_read", "type": "function_call", "call_id": "read_1", "name": "read",
                            "arguments": json.dumps({"path": str(root / "ordinary-tool.txt")})}
                elif number == 2:
                    item = {"id": "fc_ask", "type": "function_call", "call_id": "ask_1", "name": "ask",
                            "arguments": json.dumps({"html": html})}
                else:
                    item = {"id": "msg_final", "type": "message", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": "ASK_HISTORY_DONE", "annotations": []}]}
                response = {"id": f"resp_{number}", "object": "response", "status": "completed", "output": [item],
                            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}
                events = [
                    {"type": "response.created", "response": response | {"status": "in_progress", "output": []}},
                    {"type": "response.output_item.added", "output_index": 0, "item": item},
                    {"type": "response.output_item.done", "output_index": 0, "item": item},
                    {"type": "response.completed", "response": response},
                ]
                payload = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory(prefix="omp-ask-history-") as directory:
            root = Path(directory)
            agent = root / "agent"
            agent.mkdir()
            (root / "ordinary-tool.txt").write_text("ORDINARY_TOOL_OUTPUT\n")
            write_yaml(agent / "models.yml", {"providers": {"ask-test": {
                "baseUrl": f"http://127.0.0.1:{server.server_port}/v1", "api": "openai-responses",
                "auth": "apiKey", "apiKey": "test-only-key", "models": [{
                    "id": "ask-model", "name": "Ask Model", "reasoning": False, "input": ["text"],
                    "contextWindow": 100000, "maxTokens": 1024,
                }],
            }}})
            write_yaml(agent / "config.yml", {
                "display": {"hideToolActivity": True},
                "startup": {"setupWizard": False, "checkUpdate": False},
                "retry": {"enabled": False, "modelFallback": False},
                "providers": {"cacheWarming": "off"},
            })
            env = isolated_env(directory)
            env.update(PI_CODING_AGENT_DIR=str(agent), NOTIFY_DRY_RUN="1")
            env.pop("PI_CONFIG_FILES", None)

            @contextmanager
            def session(resume=None):
                frames = queue.Queue()
                pending = []
                with tempfile.TemporaryFile(mode="w+") as errors:
                    command = [OMP_BIN, "--profile", "default", "--cwd", directory,
                               "--model", "ask-test/ask-model", "--mode", "rpc-ui", "--tools", "read,ask",
                               "--no-extensions", "-e", str(extension_path("ask-history")),
                               "--no-skills", "--no-rules", "--no-lsp", "--no-title", "--thinking", "off"]
                    if resume:
                        command.extend(["--resume", resume])
                    process = subprocess.Popen(command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                               stderr=errors, text=True)

                    def read_frames():
                        try:
                            for line in process.stdout:
                                frames.put(json.loads(line))
                        finally:
                            frames.put(None)

                    threading.Thread(target=read_frames, daemon=True).start()

                    def wait_for(predicate):
                        for index, frame in enumerate(pending):
                            if predicate(frame):
                                return pending.pop(index)
                        deadline = time.monotonic() + 15
                        while time.monotonic() < deadline:
                            try:
                                frame = frames.get(timeout=max(0.01, deadline - time.monotonic()))
                            except queue.Empty:
                                break
                            if frame is None:
                                break
                            self.assertNotEqual(frame.get("type"), "extension_error", frame)
                            if predicate(frame):
                                return frame
                            pending.append(frame)
                        errors.seek(0)
                        self.fail(f"Missing RPC frame; stderr={errors.read()}; pending={pending}")

                    sequence = 0

                    def send(kind, **fields):
                        nonlocal sequence
                        sequence += 1
                        identity = f"command-{sequence}"
                        process.stdin.write(json.dumps({"id": identity, "type": kind} | fields) + "\n")
                        process.stdin.flush()
                        reply = wait_for(lambda frame: frame.get("id") == identity and frame["type"] == "response")
                        self.assertTrue(reply["success"], reply)
                        return reply.get("data")

                    try:
                        wait_for(lambda frame: frame["type"] == "ready")
                        yield process, send, wait_for
                    finally:
                        process.stdin.close()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.terminate()
                            process.wait(timeout=5)
                        process.stdout.close()

            if native_form:
                legacy = root / "legacy-ask.ts"
                legacy.write_text('''
export default function(pi) {
 pi.registerCommand("legacy-ask", {description:"Restore a pre-form answer fixture", handler:()=>{
  pi.sendMessage({customType:"dotfiles.ask-history", content:"LEGACY_STORAGE_QUESTION: Archive\\nLEGACY_STORAGE_ANSWER: Preserve",
   details:{results:[{id:"archive",question:"LEGACY_STORAGE_QUESTION",selectedOptions:["Preserve"]}]}, display:true});
 }});
}
''')
                command = ["--profile", "default", "--cwd", directory, "--model", "ask-test/ask-model",
                           "--tools", "read,ask", "--no-extensions", "-e", str(extension_path("ask-history")),
                           "-e", str(legacy), "--no-skills", "--no-rules", "--no-lsp", "--no-title", "--thinking", "off",
                           "--session-dir", str(root / "sessions")]

                @contextmanager
                def terminal(*extra):
                    master, slave = pty.openpty()
                    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 120, 0, 0))
                    try:
                        process = subprocess.Popen([OMP_BIN, *command, *extra], stdin=slave, stdout=slave, stderr=slave,
                                                   env={**env, "TERM": "xterm-256color"}, start_new_session=True)
                    finally:
                        os.close(slave)
                    child = fdspawn(master, encoding="utf-8", timeout=15)
                    screen = pyte.Screen(120, 50)
                    stream = pyte.Stream(screen)

                    def wait_text(text):
                        deadline = time.monotonic() + 15
                        while time.monotonic() < deadline:
                            if text in "\n".join(screen.display):
                                return
                            try:
                                stream.feed(child.read_nonblocking(65536, timeout=0.1))
                            except pexpect.TIMEOUT:
                                pass
                        self.fail(f"Missing TUI text {text!r}:\n" + "\n".join(screen.display))

                    try:
                        yield child, wait_text, screen
                    finally:
                        if process.poll() is None:
                            process.terminate()
                            deadline = time.monotonic() + 5
                            while process.poll() is None and time.monotonic() < deadline:
                                try:
                                    child.read_nonblocking(65536, timeout=0.1)
                                except pexpect.TIMEOUT:
                                    pass
                                except pexpect.EOF:
                                    break
                            if process.poll() is None:
                                process.kill()
                            process.wait(timeout=5)
                        child.close()

                with terminal("Read the fixture, ask the questions, then finish.") as (child, wait_text, screen):
                    wait_text("Submit")
                    wait_text("Choose the storage mode")
                    child.send("\t")
                    child.send(" ")
                    child.send("\x1b[B")
                    child.send(" ")
                    child.send("\t")
                    child.send("Keep the question visible")
                    child.send("\t")
                    child.send("\r")
                    wait_text("ASK_HISTORY_DONE")
                    wait_text("Search, Export")
                    wait_text("Keep the question visible")
                    self.assertNotIn("ORDINARY_TOOL_OUTPUT", "\n".join(screen.display))
                    child.send("/legacy-ask\r")
                    wait_text("LEGACY_STORAGE_ANSWER: Preserve")
                session_files = list((root / "sessions").rglob("*.jsonl"))
                self.assertEqual(len(session_files), 1, session_files)
                session_file = str(session_files[0])
                with terminal("--resume", session_file) as (_child, wait_text, _screen):
                    wait_text("LEGACY_STORAGE_ANSWER: Preserve")
                    wait_text("Search, Export")
                    wait_text("Keep the question visible")
                with session(session_file) as (_process, send, _wait_for):
                    records = [message for message in send("get_messages")["messages"]
                               if message.get("customType") == "dotfiles.ask-history"]
                    self.assertEqual(len(records), 2, records)
                    self.assertEqual(records[0]["details"]["answers"], [
                        {"name": "choice", "question": "Choose the storage mode", "answer": "Keep"},
                        {"name": "features", "question": "Choose features", "answer": "Search, Export"},
                        {"name": "feedback", "question": "Add feedback", "answer": "Keep the question visible"},
                    ])
                self.assertEqual(len(received), 3)
                final_input = received[-1]["input"]
                self.assertEqual(json.dumps(final_input).count(json.dumps(records[0]["content"])[1:-1]), 1, final_input)
                return

            with session() as (process, send, wait_for):
                send("prompt", message="Read the fixture, ask the questions, then finish.")
                def answer(method, value):
                    dialog = wait_for(lambda frame: frame.get("method") == method)
                    process.stdin.write(json.dumps({"type": "extension_ui_response", "id": dialog["id"],
                                                    "value": value(dialog) if callable(value) else value}) + "\n")
                    process.stdin.flush()

                answer("select", "Keep")
                answer("select", "Search")
                answer("select", "Export")
                answer("select", lambda dialog: next(option for option in dialog["options"] if "Done selecting" in option))
                answer("input", "Keep the question visible")
                wait_for(lambda frame: frame["type"] == "session_settled")
                messages = send("get_messages")["messages"]
                records = [message for message in messages if message.get("customType") == "dotfiles.ask-history"]
                self.assertEqual(len(records), 1, messages)
                self.assertEqual(records[0]["details"]["answers"], [
                    {"name": "choice", "question": "Choose the storage mode", "answer": "Keep"},
                    {"name": "features", "question": "Choose features", "answer": "Search, Export"},
                    {"name": "feedback", "question": "Add feedback", "answer": "Keep the question visible"},
                ])
                self.assertEqual(len(received), 3)
                record_text = records[0]["content"]
                final_input = received[-1]["input"]
                self.assertEqual(json.dumps(final_input).count(json.dumps(record_text)[1:-1]), 1, final_input)
                session_file = send("get_state")["sessionFile"]
            with session(session_file) as (_process, send, _wait_for):
                restored = send("get_messages")["messages"]
                restored_records = [message for message in restored if message.get("customType") == "dotfiles.ask-history"]
                self.assertEqual([record["details"] for record in restored_records], [records[0]["details"]])
                self.assertEqual(len(received), 3)


if __name__ == "__main__":
    unittest.main()
