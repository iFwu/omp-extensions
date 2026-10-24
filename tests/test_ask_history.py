"""Keep Ask answers in history without unhiding tools or duplicating model input."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import unittest

from support import OMP_BIN, SRC, isolated_env, write_yaml


@unittest.skipUnless(OMP_BIN, "OMP is not installed")
class AskHistoryTests(unittest.TestCase):
    def test_native_answers_survive_resume_without_duplicate_model_context(self):
        received = []
        questions = [
            {"id": "choice", "question": "Choose the storage mode", "options": [{"label": "Keep"}, {"label": "Change"}]},
            {"id": "features", "question": "Choose features", "multi": True,
             "options": [{"label": "Search"}, {"label": "Export"}]},
            {"id": "feedback", "question": "Add feedback", "options": [{"label": "No changes"}]},
        ]

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
                            "arguments": json.dumps({"questions": questions})}
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
                               "--no-extensions", "-e", str(SRC / "ask-history.ts"),
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

            with session() as (process, send, wait_for):
                send("set_ask_dialog", enabled=True)
                send("prompt", message="Read the fixture, ask the questions, then finish.")
                dialog = wait_for(lambda frame: frame.get("method") == "ask")
                self.assertEqual(dialog["questions"], questions)
                process.stdin.write(json.dumps({"type": "extension_ui_response", "id": dialog["id"], "answers": [
                    {"id": "choice", "selectedOptions": ["Keep"]},
                    {"id": "features", "selectedOptions": ["Search", "Export"]},
                    {"id": "feedback", "selectedOptions": [], "customInput": "Keep the question visible"},
                ]}) + "\n")
                process.stdin.flush()
                wait_for(lambda frame: frame["type"] == "session_settled")
                messages = send("get_messages")["messages"]
                records = [message for message in messages if message.get("customType") == "dotfiles.ask-history"]
                self.assertEqual(len(records), 1, messages)
                results = records[0]["details"]["results"]
                self.assertEqual([result["selectedOptions"] for result in results], [["Keep"], ["Search", "Export"], []])
                self.assertEqual(results[2]["customInput"], "Keep the question visible")
                self.assertEqual([result["question"] for result in results], [q["question"] for q in questions])
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
