"""`/model <selector>` rewrites to a session-only `/switch` and leaves role assignments alone."""

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

from test_support import OMP_BIN, extension_path, isolated_env, read_yaml, write_yaml


@unittest.skipUnless(OMP_BIN, "OMP is not installed")
class ModelSwitchTests(unittest.TestCase):
    def test_model_argument_switches_session_without_saving_role(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.send_response(500)
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory(prefix="omp-switch-") as directory:
            root = Path(directory)
            agent = root / "agent"
            agent.mkdir()
            extension = extension_path("model-switch")
            write_yaml(agent / "models.yml", {"providers": {
                "switch-test": {
                    "baseUrl": f"http://127.0.0.1:{server.server_port}/v1",
                    "api": "openai-responses",
                    "auth": "apiKey",
                    "apiKey": "test-only-key",
                    "models": [
                        {"id": model, "name": model, "reasoning": True, "input": ["text"],
                         "contextWindow": 200000, "maxTokens": 1024}
                        for model in ("gpt-check", "claude-check")
                    ],
                },
            }})
            write_yaml(agent / "config.yml", {
                "modelRoles": {
                    "default": "switch-test/gpt-check",
                    "other": "switch-test/claude-check",
                },
                "startup": {"setupWizard": False, "checkUpdate": False},
                "retry": {"enabled": False, "modelFallback": False},
                "providers": {"cacheWarming": "off"},
            })
            saved_roles = read_yaml(agent / "config.yml")["modelRoles"]
            env = isolated_env(directory)
            env.update(PI_CODING_AGENT_DIR=str(agent), NOTIFY_DRY_RUN="1")
            env.pop("PI_CONFIG_FILES", None)
            with tempfile.TemporaryFile(mode="w+") as errors:
                process = subprocess.Popen(
                    [OMP_BIN, "--profile", "default", "--cwd", directory, "--mode", "rpc",
                     "--no-tools", "--no-extensions", "-e", str(extension), "--no-skills", "--no-rules",
                     "--no-lsp", "--no-title", "--no-session", "--thinking", "off"],
                    env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True,
                )
                frames = queue.Queue()

                def read_frames():
                    try:
                        for line in process.stdout:
                            frames.put(json.loads(line))
                    finally:
                        frames.put(None)

                reader = threading.Thread(target=read_frames, daemon=True)
                reader.start()
                sequence = 0
                pending = []

                def wait_for(predicate):
                    for index, frame in enumerate(pending):
                        if predicate(frame):
                            return pending.pop(index)
                    deadline = time.monotonic() + 20
                    while True:
                        try:
                            frame = frames.get(timeout=max(0, deadline - time.monotonic()))
                        except queue.Empty:
                            errors.seek(0)
                            self.fail(f"Timed out waiting for an OMP RPC frame; stderr: {errors.read()}; pending: {pending}")
                        if frame is None:
                            errors.seek(0)
                            self.fail(f"OMP exited before the expected frame: {errors.read()}")
                        self.assertNotEqual(frame["type"], "extension_error", frame)
                        if predicate(frame):
                            return frame
                        pending.append(frame)

                def send(kind, **fields):
                    nonlocal sequence
                    sequence += 1
                    identity = f"command-{sequence}"
                    process.stdin.write(json.dumps({"id": identity, "type": kind} | fields) + "\n")
                    process.stdin.flush()
                    reply = wait_for(lambda frame: frame.get("id") == identity and frame["type"] == "response")
                    self.assertTrue(reply["success"], reply)
                    return reply

                def command_text():
                    texts = [frame.get("text", "") for frame in pending if frame.get("type") == "command_output"]
                    pending[:] = [frame for frame in pending if frame.get("type") != "command_output"]
                    return "\n".join(texts)

                def model():
                    selected = send("get_state")["data"]["model"]
                    return {"provider": selected["provider"], "id": selected["id"]}

                try:
                    wait_for(lambda frame: frame["type"] == "ready")
                    self.assertEqual(model(), {"provider": "switch-test", "id": "gpt-check"})

                    bare = send("prompt", message="/model")
                    self.assertFalse(bare["data"]["agentInvoked"])
                    self.assertIn("Current model: switch-test/gpt-check", command_text())
                    self.assertEqual(model()["id"], "gpt-check")

                    switched = send("prompt", message="/model @other")
                    self.assertFalse(switched["data"]["agentInvoked"])
                    self.assertEqual(model(), {"provider": "switch-test", "id": "claude-check"})
                    self.assertEqual(read_yaml(agent / "config.yml")["modelRoles"], saved_roles)

                    alias = send("prompt", message="/models switch-test/gpt-check:high")
                    self.assertFalse(alias["data"]["agentInvoked"])
                    state = send("get_state")["data"]
                    self.assertEqual(state["model"]["provider"], "switch-test")
                    self.assertEqual(state["model"]["id"], "gpt-check")
                    self.assertEqual(state["thinkingLevel"], "high")
                    self.assertEqual(read_yaml(agent / "config.yml")["modelRoles"], saved_roles)

                    missing = send("prompt", message="/model nope")
                    self.assertFalse(missing["data"]["agentInvoked"])
                    self.assertIn("Unknown model: nope", command_text())
                    self.assertEqual(model()["id"], "gpt-check")
                    self.assertEqual(read_yaml(agent / "config.yml")["modelRoles"], saved_roles)
                finally:
                    process.stdin.close()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        process.wait(timeout=5)
                        self.fail("OMP did not exit after stdin closed")
                    finally:
                        reader.join(timeout=2)
                        process.stdout.close()
                self.assertEqual(process.returncode, 0)


if __name__ == "__main__":
    unittest.main()
