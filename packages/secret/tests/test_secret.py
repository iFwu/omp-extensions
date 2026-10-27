"""Real standalone OMP PTY + deterministic loopback provider; synthetic credentials only.

Run from the repository root with its Python environment:
  python3 -m unittest discover -s packages/secret/tests -v
Set OMP_BIN to the native standalone OMP executable. Requires pexpect, pyte and curl.
No provider requests, terminal transcripts or credential values are written by this fixture.
"""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from queue import Empty, Queue
import secrets
import shutil
import tempfile
import threading
import time
import unittest

from test_support import OMP_BIN, extension_path, isolated_env, write_yaml

try:
    import pexpect
    import pyte
except ImportError:
    pexpect = pyte = None


class FixtureServer(ThreadingHTTPServer):
    """Speak OpenAI streaming tool calls, retaining only in-memory synthetic traffic."""
    daemon_threads = True

    def __init__(self, credential):
        super().__init__(("127.0.0.1", 0), FixtureHandler)
        self.credential = credential
        self.requests = []
        self.tool_results = []
        self.auth = []
        self.errors = []
        self.plans = Queue()


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        valid = self.path == "/credential" and self.headers.get("Authorization") == "Bearer " + self.server.credential
        self.server.auth.append(valid)
        self.send_response(200 if valid else 401)
        self.end_headers()
        self.wfile.write(b"AUTH_OK" if valid else b"AUTH_FAILED")

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(body)
        messages = body.get("messages", [])
        if messages and messages[-1].get("role") == "tool":
            self.server.tool_results.append(messages[-1]["content"])
            delta = {"content": f"SECRET_DONE_{len(self.server.tool_results)}"}
            finish = "stop"
        else:
            try:
                tool, args = self.server.plans.get_nowait()
            except Empty:
                self.server.errors.append("Unexpected provider request without a planned tool")
                delta, finish = {"content": "UNPLANNED_REQUEST"}, "stop"
            else:
                delta = {"tool_calls": [{"index": 0, "id": f"call_{len(self.server.requests)}", "type": "function",
                                         "function": {"name": tool, "arguments": json.dumps(args)}}]}
                finish = "tool_calls"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            for payload in [
                {"id": "fixture", "object": "chat.completion.chunk", "model": "fixture",
                 "choices": [{"index": 0, "delta": {"role": "assistant", **delta}, "finish_reason": None}]},
                {"id": "fixture", "object": "chat.completion.chunk", "model": "fixture",
                 "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                 "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
            ]:
                self.wfile.write(("data: " + json.dumps(payload) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            self.server.errors.append("Provider stream closed before completion")


class NativeSession:
    def __init__(self, testcase, root, server, forbidden):
        self.testcase = testcase
        self.server = server
        self.forbidden = forbidden
        self.terminal_leaked = False
        self.carry = ""
        agent = root / "agent"
        agent.mkdir()
        write_yaml(agent / "config.yml", {
            "modelRoles": {"default": "fixture/fixture"}, "enabledModels": ["fixture/**"],
            "startup": {"setupWizard": False, "checkUpdate": False},
            "providers": {"cacheWarming": "off"}, "retry": {"enabled": False},
            "autocomplete": {"enabled": False},
        })
        write_yaml(agent / "models.yml", {"providers": {"fixture": {
            "baseUrl": f"http://127.0.0.1:{server.server_port}/v1", "api": "openai-completions",
            "auth": "apiKey", "apiKey": "fake-fixture-key", "models": [{
                "id": "fixture", "name": "Fixture", "reasoning": False, "input": ["text"],
                "contextWindow": 128000, "maxTokens": 2048,
            }],
        }}})
        env = isolated_env(root)
        tmp = root / "tmp"
        tmp.mkdir()
        env.update(PI_CODING_AGENT_DIR=str(agent), TERM="xterm-256color", NOTIFY_DRY_RUN="1",
                   TMPDIR=str(tmp), TMP=str(tmp), TEMP=str(tmp))
        # --tools secret would force top-level exposure and invalidate discovery coverage.
        args = ["--profile", "default", "--cwd", str(root), "--no-extensions",
                "-e", str(extension_path("secret")), "--secret", "--no-skills", "--no-rules",
                "--no-lsp", "--no-title", "--thinking", "off", "--model", "fixture/fixture",
                "--approval-mode", "yolo",
                "--system-prompt", "Synthetic credential transport fixture. Use the supplied tools."]
        self.child = pexpect.spawn(OMP_BIN, args, cwd=str(root), env=env, encoding="utf-8",
                                   dimensions=(42, 130), timeout=30)
        testcase.addCleanup(self.close)
        self.screen = pyte.Screen(130, 42)
        self.output_tail = ""
        self.stream = pyte.Stream(self.screen)
        self.wait(lambda: "sec: 0 active" in self.visible(), "extension startup", timeout=40)
        testcase.assertNotIn("another extension owns", self.visible())

    def visible(self):
        return "\n".join(self.screen.display)

    def diagnostic(self):
        text = self.visible() + "\nRecent terminal bytes: " + self.output_tail
        for value in self.forbidden:
            text = text.replace(value, "[credential withheld]")
        return repr(text[-16000:])

    def record_terminal(self, data):
        self.output_tail = (self.output_tail + data)[-32768:]
        combined = self.carry + data
        self.terminal_leaked |= any(value in combined for value in self.forbidden)
        self.carry = combined[-max(map(len, self.forbidden)):]
        self.stream.feed(data)

    def pump(self, duration=0.15):
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            try:
                data = self.child.read_nonblocking(65536, timeout=min(0.05, max(0.001, deadline - time.monotonic())))
                self.record_terminal(data)
                if "\x1b[6n" in data:
                    self.child.send("\x1b[1;1R")
            except pexpect.TIMEOUT:
                pass
            except pexpect.EOF:
                self.testcase.fail("OMP exited unexpectedly\n" + self.diagnostic())

    def wait(self, predicate, label, timeout=25):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump()
            if self.server.errors:
                self.testcase.fail(self.server.errors[-1])
            if predicate():
                return
        self.testcase.fail(f"Timed out: {label}\n{self.diagnostic()}")

    def send(self, text):
        self.child.send(text)
        self.pump(0.1)
        self.child.send("\r")

    def start_turn(self, tool, args):
        previous = len(self.server.tool_results)
        self.server.plans.put((tool, args))
        self.send("Run the next synthetic check.")
        return previous

    def finish_turn(self, previous):
        self.wait(lambda: len(self.server.tool_results) > previous, "tool round trip")
        self.wait(lambda: f"SECRET_DONE_{previous + 1}" in self.visible(), "assistant completion")
        self.pump(0.2)
        result = self.server.tool_results[-1]
        return result if isinstance(result, str) else json.dumps(result)

    def turn(self, tool, args):
        return self.finish_turn(self.start_turn(tool, args))

    def secret(self, args):
        return self.turn("write", {"i": "Managing synthetic credentials", "path": "xd://secret", "content": json.dumps(args)})

    def close(self):
        if self.child.isalive():
            self.child.sendcontrol("c")
            time.sleep(0.15)
            self.child.sendcontrol("c")
            try:
                self.child.expect(pexpect.EOF, timeout=5)
            except pexpect.TIMEOUT:
                self.child.terminate(force=True)
            self.record_terminal(self.child.before or "")
        self.child.close()


def contains_canary(path, values):
    """Scan runtime files in bounded chunks, including matches crossing chunk boundaries."""
    carry = b""
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            combined = carry + chunk
            if any(value in combined for value in values):
                return True
            carry = combined[-max(map(len, values)):]
    return False


@unittest.skipUnless(os.name == "posix" and OMP_BIN and pexpect and pyte and shutil.which("curl"),
                     "POSIX standalone OMP, pexpect, pyte and curl required")
class SecretRuntimeTests(unittest.TestCase):
    def test_discovery_masked_request_transport_guards_and_session_lifetime(self):
        canary = "test-" + secrets.token_hex(20) + "'\"$; $(printf injected) space"
        # The unique raw prefix also catches JSON-escaped values with quotes/backslashes.
        forbidden = [canary, canary[:45], base64.b64encode(canary.encode()).decode(),
                     base64.urlsafe_b64encode(canary.encode()).decode().rstrip("="), canary.encode().hex()]
        directory = tempfile.TemporaryDirectory(prefix="omp-secret-test-")
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        server = FixtureServer(canary)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        session = NativeSession(self, root, server, forbidden)

        with self.subTest("manual short input and cancellation"):
            session.send("/sec add short")
            session.wait(lambda: "paste is fine" in session.visible(), "short credential dialog")
            session.child.send("1234\r")
            session.wait(lambda: "requires at least 8 characters" in session.visible(), "short credential rejection")
            session.send("/sec add cancelled")
            session.wait(lambda: "paste is fine" in session.visible(), "cancel dialog")
            session.child.send("synthetic-cancelled-value")
            session.pump(0.2)
            session.child.send("\x1b")
            session.wait(lambda: "paste is fine" not in session.visible(), "cancelled dialog dismissal")

        with self.subTest("on-demand discovery without schema promotion"):
            schema = session.turn("read", {"i": "Discovering credential input", "path": "xd://secret"})
            self.assertIn("request", schema)
            self.assertIn("reason", schema)
            names = [tool.get("function", {}).get("name") for tool in server.requests[0].get("tools", [])]
            self.assertIn("read", names)
            self.assertIn("write", names)
            self.assertNotIn("secret", names, "secret must remain discoverable, not top-level")

        request = {"action": "request", "name": "canary", "reason": "Authenticate local smoke endpoint"}
        with self.subTest("model-triggered masked input"):
            previous = session.start_turn("write", {"i": "Requesting credential input", "path": "xd://secret",
                                                     "content": json.dumps(request)})
            session.wait(lambda: "Purpose: Authenticate local smoke endpoint" in session.visible(), "model-triggered input")
            session.child.send("\x1b[200~" + canary + "\x1b[201~")
            session.pump(0.4)
            self.assertIn("••••", session.visible())
            self.assertFalse(session.terminal_leaked, "credential reached terminal")
            session.child.send("\r")
            result = session.finish_turn(previous)
            self.assertIn("stored", result)
            self.assertIn("{{sec:canary}}", result)
            self.assertIn("available", session.secret(request))
            result = session.secret({"action": "list"})
            self.assertIn("{{sec:canary}}", result)
            self.assertNotIn("sec:cancelled", result)
            self.assertNotIn("sec:short", result)

        with self.subTest("exact loopback receipt and echoed output redaction"):
            command = (f'curl -fsS -H "Authorization: Bearer {{{{sec:canary}}}}" '
                       f'http://127.0.0.1:{server.server_port}/credential; printf "\\n%s\\n" "{{{{sec:canary}}}}"')
            result = session.turn("bash", {"i": "Testing credential transport", "command": command, "timeout": 10})
            self.assertEqual(server.auth, [True], "target must receive the exact punctuation-bearing value")
            self.assertIn("AUTH_OK", result)
            self.assertIn("{{sec:canary}}", result)
            self.assertFalse(any(value in result for value in forbidden), "credential leaked in tool result")

        with self.subTest("native persistent shell remains native"):
            result = session.turn("bash", {"i": "Testing native shell", "command": "export SECRET_FIXTURE_PERSIST=kept; printf native_ok", "timeout": 5})
            self.assertIn("native_ok", result)
            result = session.turn("bash", {"i": "Testing persistent shell", "command": 'printf "$SECRET_FIXTURE_PERSIST"', "timeout": 5})
            self.assertIn("kept", result)

        with self.subTest("unsupported execution and missing references"):
            result = session.turn("bash", {"i": "Testing missing reference", "command": 'printf "%s" "{{sec:missing}}"', "timeout": 5})
            self.assertIn("missing", result)
            self.assertTrue("not found" in result or "unknown" in result)
            result = session.turn("write", {"i": "Testing unsafe ref persistence", "path": "credential.txt", "content": "{{sec:canary}}"})
            self.assertFalse((root / "credential.txt").exists(), "blocked reference must not create a file")
            self.assertTrue("bash" in result or "placeholder" in result)
            for flag, value in (("pty", True), ("async", True), ("name", "secret-fixture-service"),
                                ("ready", {"log": "READY"})):
                result = session.turn("bash", {"i": "Testing foreground restriction", "command": 'printf "%s" "{{sec:canary}}"', "timeout": 5, flag: value})
                self.assertIn("foreground", result)

        with self.subTest("timeout kills credential child"):
            result = session.turn("bash", {"i": "Testing timeout", "command": "TOKEN={{sec:canary}} sleep 10", "timeout": 0.2})
            self.assertIn("timed out", result)

        with self.subTest("new session clears vault"):
            session.send("/new")
            session.wait(lambda: "sec: 0 active" in session.visible(), "new session vault reset")
            self.assertNotIn("sec:canary", session.secret({"action": "list"}))
            result = session.turn("bash", {"i": "Checking cleared reference", "command": 'printf "%s" "{{sec:canary}}"', "timeout": 5})
            self.assertTrue("not found" in result or "unknown" in result)

        with self.subTest("provider, terminal, sessions and runtime files contain no canary"):
            payload = json.dumps(server.requests)
            self.assertFalse(any(value in payload for value in forbidden), "credential leaked to provider")
            self.assertFalse(session.terminal_leaked, "credential leaked to terminal")
            session.close()  # Flush shutdown/session artifacts before examining the isolated tree.
            self.assertFalse(session.terminal_leaked, "credential leaked during terminal shutdown")
            session_files = list(root.rglob("*.jsonl"))
            self.assertTrue(session_files, "session artifact scan must not be vacuous")
            encoded = [value.encode() for value in forbidden]
            leaks = [str(path.relative_to(root)) for path in root.rglob("*")
                     if path.is_file() and contains_canary(path, encoded)]
            self.assertEqual(leaks, [], "credential persisted in isolated runtime artifacts")
            self.assertEqual(server.errors, [])
            self.assertTrue(server.plans.empty(), "every planned tool call must execute")


if __name__ == "__main__":
    unittest.main()
