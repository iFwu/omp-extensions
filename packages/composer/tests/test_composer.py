"""Exercise the context rule through the installed OMP TUI, offline."""

import codecs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import select
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import unittest
import pyte

from test_support import OMP_BIN, extension_path, isolated_env, write_yaml

if os.name == "posix":
    import fcntl
    import pty
    import termios


@unittest.skipUnless(os.name == "posix" and OMP_BIN, "POSIX OMP TUI is not available")
class ComposerTests(unittest.TestCase):
    def test_context_rule_tracks_live_provider_usage(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                message = {"id": "msg_ui", "type": "message", "role": "assistant", "status": "completed",
                           "content": [{"type": "output_text", "text": "CONTEXT_DONE", "annotations": []}]}
                response = {"id": "resp_ui", "object": "response", "status": "completed", "output": [message],
                            "usage": {"input_tokens": 40000, "output_tokens": 10, "total_tokens": 40010}}
                events = [
                    ("response.created", {"response": response | {"status": "in_progress", "output": []}}),
                    ("response.output_item.added", {"output_index": 0, "item": message | {"content": []}}),
                    ("response.output_text.delta", {"item_id": "msg_ui", "output_index": 0, "delta": "CONTEXT_DONE"}),
                    ("response.output_item.done", {"output_index": 0, "item": message}),
                    ("response.completed", {"response": response}),
                ]
                payload = "".join(f"event: {kind}\ndata: {json.dumps({'type': kind} | data)}\n\n"
                                  for kind, data in events).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_yaml(root / "models.yml", {"providers": {"ui-test": {
                "baseUrl": f"http://127.0.0.1:{server.server_port}/v1", "api": "openai-responses",
                "auth": "apiKey", "apiKey": "test-only-key", "models": [{
                    "id": "ui-model", "name": "UI Model", "reasoning": False, "input": ["text"],
                    "contextWindow": 100000, "maxTokens": 1024,
                }],
            }}})
            write_yaml(root / "config.yml", {
                "composer": {"shape": "dotfiles/claude-context"},
                "symbolPreset": "unicode",
                "compaction": {"thresholdPercent": 60, "asyncEnabled": False},
                "statusLine": {"transparent": True, "contextLine": "embedded"},
                "startup": {"setupWizard": False, "checkUpdate": False, "quiet": True},
                "retry": {"enabled": False, "modelFallback": False},
                "providers": {"cacheWarming": "off"},
            })
            master, slave = pty.openpty()
            self.addCleanup(os.close, master)
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 110, 0, 0))
            env = isolated_env(directory)
            env.update(PI_CODING_AGENT_DIR=directory, TERM="xterm-256color", NOTIFY_DRY_RUN="1")
            env.pop("PI_CONFIG_FILES", None)
            process = subprocess.Popen(
                [OMP_BIN, "--cwd", directory, "--model", "ui-test/ui-model",
                 "--no-tools", "--no-extensions", "-e", str(extension_path("composer")),
                 "--no-skills", "--no-rules", "--no-lsp", "--no-title", "--no-session", "--thinking", "off"],
                env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
            )
            os.close(slave)
            screen = pyte.Screen(110, 30)
            terminal = pyte.Stream(screen)
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

            def wait_for_rule(minimum, maximum):
                output = ""
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if select.select([master], [], [], max(0, deadline - time.monotonic()))[0]:
                        try:
                            chunk = os.read(master, 65536)
                        except OSError:
                            break
                        if not chunk:
                            break
                        text = decoder.decode(chunk)
                        output += text
                        terminal.feed(text)
                        for row in screen.display:
                            if "100K" not in row or "┃" not in row:
                                continue
                            percent = re.search(r"(\d+(?:\.\d+)?)%", row)
                            if percent and minimum <= float(percent.group(1)) / 100 <= maximum:
                                return
                self.fail(f"No context rule in {minimum:.0%}–{maximum:.0%}; terminal tail: {output[-2000:]!r}")

            try:
                wait_for_rule(0.001, 0.15)
                os.write(master, b"Check context.\r")
                wait_for_rule(0.38, 0.43)
                texts = [part["text"] for item in received[-1]["input"] if item.get("role") == "user"
                         for part in item["content"] if part.get("type") == "input_text"]
                self.assertEqual(texts[-1], "Check context.")
            finally:
                try:
                    if process.poll() is None:
                        os.write(master, b"\x03\x03")
                        deadline = time.monotonic() + 5
                        # Drain terminal output while OMP flushes its exit frame.
                        while process.poll() is None and time.monotonic() < deadline:
                            if select.select([master], [], [], max(0, deadline - time.monotonic()))[0]:
                                try:
                                    if not os.read(master, 65536):
                                        break
                                except OSError:
                                    break
                finally:
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                        raise


if __name__ == "__main__":
    unittest.main()
