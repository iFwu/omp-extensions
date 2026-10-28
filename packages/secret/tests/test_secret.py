"""Real standalone OMP PTY + deterministic loopback provider; synthetic credentials only.

Run from the repository root with its Python environment:
  python3 -m unittest discover -s packages/secret/tests -v
Set OMP_BIN to the native standalone OMP executable. Requires pexpect, pyte and curl.
No real provider or credential is used. Synthetic session artifacts stay in a temporary tree.
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
    """Speak local Chat Completions or Codex Responses with synthetic traffic only."""
    daemon_threads = True

    def __init__(self, credential, api="openai-completions"):
        super().__init__(("127.0.0.1", 0), FixtureHandler)
        self.credential = credential
        self.api = api
        self.reasoning_item = None
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
        if self.server.api == "openai-codex-responses":
            self.respond_codex(body)
            return
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

    def respond_codex(self, body):
        inputs = body.get("input", [])
        result = inputs[-1] if inputs else {}
        turn = len(self.server.requests)
        if result.get("type") == "function_call_output":
            self.server.tool_results.append(result["output"])
            output = [{"type": "message", "id": f"msg_{turn}", "role": "assistant", "status": "completed",
                       "phase": "final_answer", "content": [{"type": "output_text", "annotations": [],
                       "text": f"SECRET_DONE_{len(self.server.tool_results)}"}]}]
        else:
            try:
                tool, args = self.server.plans.get_nowait()
            except Empty:
                self.server.errors.append("Unexpected Codex request without a planned tool")
                self.send_error(500)
                return
            output = [{"type": "function_call", "id": f"fc_{turn}", "call_id": f"call_{turn}",
                       "status": "completed", "name": tool, "arguments": json.dumps(args)}]
            if turn == 1 and self.server.reasoning_item:
                output.insert(0, self.server.reasoning_item)
        response = {"id": f"resp_{turn}", "object": "response", "status": "completed", "output": output,
                    "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20}}
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
                    event("response.reasoning_summary_part.added", output_index=index, item_id=item["id"],
                          summary_index=0, part={"type": "summary_text", "text": ""})
                    event("response.reasoning_summary_text.delta", output_index=index, item_id=item["id"],
                          summary_index=0, delta=item["summary"][0]["text"])
                elif item["type"] == "message":
                    event("response.output_text.delta", output_index=index, item_id=item["id"],
                          delta=item["content"][0]["text"])
                else:
                    event("response.function_call_arguments.delta", output_index=index, item_id=item["id"],
                          delta=item["arguments"])
                event("response.output_item.done", output_index=index, item=item)
            event("response.completed", response=response)
        except (BrokenPipeError, ConnectionResetError):
            self.server.errors.append("Codex provider stream closed before completion")


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
            "baseUrl": f"http://127.0.0.1:{server.server_port}/v1", "api": server.api,
            "auth": "apiKey", "apiKey": "fake-fixture-key", "models": [{
                "id": "fixture", "name": "Fixture", "reasoning": server.api == "openai-codex-responses", "input": ["text"],
                "contextWindow": 128000, "maxTokens": 2048,
            }],
        }}})
        env = isolated_env(root)
        tmp = root / "tmp"
        tmp.mkdir()
        env.update(PI_CODING_AGENT_DIR=str(agent), TERM="xterm-256color", NOTIFY_DRY_RUN="1",
                   TMPDIR=str(tmp), TMP=str(tmp), TEMP=str(tmp), PI_CODEX_WEBSOCKET="0")
        # --tools secret would force top-level exposure and invalidate discovery coverage.
        args = ["--profile", "default", "--cwd", str(root), "--no-extensions",
                "-e", str(extension_path("secret")), "--secret", "--no-skills", "--no-rules",
                "--no-lsp", "--no-title", "--thinking", "low" if server.api == "openai-codex-responses" else "off", "--model", "fixture/fixture",
                "--approval-mode", "yolo",
                "--system-prompt", "Synthetic credential transport fixture. Use the supplied tools."]
        self.child = pexpect.spawn(OMP_BIN, args, cwd=str(root), env=env, encoding="utf-8",
                                   dimensions=(42, 130), timeout=30)
        testcase.addCleanup(self.close)
        self.screen = pyte.Screen(130, 42)
        self.output_tail = ""
        self.stream = pyte.Stream(self.screen)
        self.wait(lambda: "fixture" in self.visible().lower(), "native editor startup", timeout=40)
        self.send("/sec list")
        self.wait(lambda: "no secrets in this session" in self.visible(), "explicit credential listing")
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
        self.testcase.assertNotRegex(self.visible(), r"(?:sec|secret): \d+ active|secret: off",
                                     "credentials must not add a persistent status badge")

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

    def start_turn(self, tool, args, prompt="Run the next synthetic check."):
        previous = len(self.server.tool_results)
        self.server.plans.put((tool, args))
        self.send(prompt)
        return previous

    def finish_turn(self, previous):
        self.wait(lambda: len(self.server.tool_results) > previous, "tool round trip")
        self.wait(lambda: f"SECRET_DONE_{previous + 1}" in self.visible(), "assistant completion")
        self.pump(0.2)
        result = self.server.tool_results[-1]
        return result if isinstance(result, str) else json.dumps(result)

    def turn(self, tool, args, prompt="Run the next synthetic check."):
        return self.finish_turn(self.start_turn(tool, args, prompt))

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


def text_values(value):
    """Inspect decoded wire/session strings without reserializing their contents."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from text_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from text_values(item)


def session_entries(root):
    return [json.loads(line) for path in root.rglob("*.jsonl")
            for line in path.read_text().splitlines() if line.strip()]


@unittest.skipUnless(os.name == "posix" and OMP_BIN and pexpect and pyte and shutil.which("curl"),
                     "POSIX standalone OMP, pexpect, pyte and curl required")
class SecretRuntimeTests(unittest.TestCase):
    def test_discovery_masked_request_transport_guards_and_session_lifetime(self):
        canary = "test-" + secrets.token_hex(20) + "'\"$; $(printf injected) space"
        manual = "manual-" + secrets.token_hex(16)
        # Only exact raw values are protected; encoded transformations are intentionally ordinary output.
        forbidden = [canary, canary[:45], manual, "synthetic-cancelled-value"]
        ordinary = ('Keep confirm_password_ref and input[name="password"] unchanged; password=ordinary-value '
                    'token=sk-' + secrets.token_hex(24) + ' ghp_' + secrets.token_hex(20))
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

        with self.subTest("ordinary text and tool output never enter the vault"):
            result = session.turn("bash", {"i": "Checking ordinary output", "command": "printf '%s' '" + ordinary + "'",
                                           "timeout": 5}, prompt=ordinary)
            self.assertIn(ordinary, result)
            user_messages = [message for body in server.requests for message in body.get("messages", [])
                             if message.get("role") == "user"]
            self.assertTrue(any(ordinary.encode() in text.encode() for text in text_values(user_messages)),
                            "ordinary user input must reach the provider byte-for-byte")
            self.assertRegex(session.secret({"action": "list"}), r'"refs"\s*:\s*\[\s*\]')
            session.turn("write", {"i": "Writing ordinary text", "path": "ordinary.txt", "content": ordinary})
            self.assertEqual((root / "ordinary.txt").read_bytes(), ordinary.encode())
            self.assertIn(ordinary, session.turn("read", {"i": "Reading ordinary text", "path": "ordinary.txt"}))
            self.assertRegex(session.secret({"action": "list"}), r'"refs"\s*:\s*\[\s*\]')

        with self.subTest("manual entry is masked and explicitly stored"):
            session.send("/sec add manual")
            session.wait(lambda: "paste is fine" in session.visible(), "manual credential dialog")
            session.child.send("\x1b[200~" + manual + "\x1b[201~")
            session.pump(0.3)
            self.assertIn("••••", session.visible())
            self.assertFalse(session.terminal_leaked, "manual credential reached terminal")
            session.child.send("\r")
            session.wait(lambda: "paste is fine" not in session.visible(), "manual dialog dismissal")
            self.assertIn("{{sec:manual}}", session.secret({"action": "list"}))
            result = session.turn("bash", {"i": "Consuming manual reference", "command": 'printf "%s" "{{sec:manual}}"', "timeout": 5})
            self.assertNotIn(manual, result)

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
            self.assertFalse(any(value in result for value in forbidden), "credential leaked in tool result")

        with self.subTest("credential output redacts exact values only"):
            result = session.turn("bash", {"i": "Checking exact redaction",
                "command": 'printf "%s\\n" "{{sec:canary}}"; printf \'%s\' \'' + ordinary + "'", "timeout": 5})
            self.assertIn(ordinary, result, "unrelated credential-shaped output must remain unchanged")
            self.assertNotIn(canary, result)
            result = session.turn("bash", {"i": "Checking encoded output boundary",
                "command": 'printf "%s" "{{sec:canary}}" | base64 | tr -d \'\\n\'', "timeout": 5})
            self.assertIn(base64.b64encode(canary.encode()).decode(), result,
                          "encoded values are not guessed or rewritten")
            listed = session.secret({"action": "list"})
            self.assertEqual(listed.count("{{sec:"), 2, "only the two explicitly entered credentials may be stored")

        with self.subTest("native persistent shell remains native"):
            result = session.turn("bash", {"i": "Testing native shell", "command": "export SECRET_FIXTURE_PERSIST=kept; printf native_ok", "timeout": 5})
            self.assertIn("native_ok", result)
            result = session.turn("bash", {"i": "Testing persistent shell", "command": 'printf "$SECRET_FIXTURE_PERSIST"', "timeout": 5})
            self.assertIn("kept", result)

        with self.subTest("unsupported execution and missing references"):
            result = session.turn("bash", {"i": "Testing missing reference", "command": 'printf "%s" "{{sec:missing}}"', "timeout": 5})
            self.assertIn("missing", result)
            self.assertTrue("not found" in result or "unknown" in result)
            session.turn("write", {"i": "Preserving literal reference", "path": "reference.txt", "content": "{{sec:canary}}"})
            self.assertEqual((root / "reference.txt").read_text(), "{{sec:canary}}",
                             "non-Bash tools must not interpret or block reference strings")
            for flag, value in (("pty", True), ("async", True), ("name", "secret-fixture-service"),
                                ("ready", {"log": "READY"})):
                result = session.turn("bash", {"i": "Testing foreground restriction", "command": 'printf "%s" "{{sec:canary}}"', "timeout": 5, flag: value})
                self.assertIn("foreground", result)

        with self.subTest("timeout kills credential child"):
            result = session.turn("bash", {"i": "Testing timeout", "command": "TOKEN={{sec:canary}} sleep 10", "timeout": 0.2})
            self.assertIn("timed out", result)

        with self.subTest("new session clears vault"):
            session.send("/new")
            session.wait(lambda: "fixture" in session.visible().lower()
                         and f"SECRET_DONE_{len(server.tool_results)}" not in session.visible(), "new session editor")
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
            self.assertTrue(any(ordinary.encode() in text.encode() for text in text_values(session_entries(root))),
                            "ordinary text must remain byte-identical in the persisted transcript")
            encoded = [value.encode() for value in forbidden]
            leaks = [str(path.relative_to(root)) for path in root.rglob("*")
                     if path.is_file() and contains_canary(path, encoded)]
            self.assertEqual(leaks, [], "credential persisted in isolated runtime artifacts")
            self.assertEqual(server.errors, [])
            self.assertTrue(server.plans.empty(), "every planned tool call must execute")

    def test_codex_responses_preserves_opaque_history_after_explicit_entry(self):
        canary = "opaque-fixture-" + secrets.token_hex(16)
        ordinary = 'confirm_password_ref input[name="password"] password=plain sk-' + secrets.token_hex(24)
        directory = tempfile.TemporaryDirectory(prefix="omp-secret-codex-")
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        server = FixtureServer(canary, api="openai-codex-responses")
        # Synthetic opaque bytes, never a real signature or encrypted account history.
        # Embedding the later-entered value catches forbidden known-value history scrubbing too.
        server.reasoning_item = {"type": "reasoning", "id": "rs_opaque_fixture",
            "summary": [{"type": "summary_text", "text": "Synthetic opaque history check"}],
            "encrypted_content": "gAAAAA_fixture_password=" + canary + "_sk-" + secrets.token_hex(24)}
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        session = NativeSession(self, root, server, [canary])

        result = session.turn("bash", {"i": "Checking Codex ordinary output", "command": "printf '%s' '" + ordinary + "'",
                                       "timeout": 5}, prompt=ordinary)
        self.assertIn(ordinary, result)
        self.assertRegex(session.secret({"action": "list"}), r'"refs"\s*:\s*\[\s*\]')
        session.send("/sec add opaque")
        session.wait(lambda: "paste is fine" in session.visible(), "Codex masked input")
        session.child.send(canary)
        session.pump(0.3)
        self.assertIn("••••", session.visible())
        self.assertFalse(session.terminal_leaked)
        session.child.send("\r")
        session.wait(lambda: "paste is fine" not in session.visible(), "Codex dialog dismissal")
        before = len(server.requests)
        result = session.turn("bash", {"i": "Checking Codex credential output",
                                       "command": 'printf "%s" "{{sec:opaque}}"', "timeout": 5})
        self.assertNotIn(canary, result)
        for body in server.requests[before:]:
            history = [item for item in body.get("input", []) if item.get("type") == "reasoning"]
            self.assertTrue(any(item.get("encrypted_content") == server.reasoning_item["encrypted_content"]
                                and item.get("summary") == server.reasoning_item["summary"] for item in history),
                            "Codex opaque ciphertext and reasoning text must remain unchanged")
        user_messages = [item for body in server.requests for item in body.get("input", []) if item.get("role") == "user"]
        self.assertTrue(any(ordinary.encode() in text.encode() for text in text_values(user_messages)))
        session.close()
        entries = session_entries(root)
        self.assertTrue(entries, "persisted Codex transcript check must not be vacuous")
        self.assertTrue(any(ordinary.encode() in text.encode() for text in text_values(entries)))
        signatures = []
        for entry in entries:
            signatures.extend(item for item in entry.get("message", {}).get("providerPayload", {}).get("items", [])
                              if item.get("type") == "reasoning")
            for block in entry.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("thinkingSignature"):
                    signatures.append(json.loads(block["thinkingSignature"]))
        self.assertIn(server.reasoning_item, signatures, "persisted Codex reasoning signature must not be rewritten")
        self.assertFalse(session.terminal_leaked)
        self.assertEqual(server.errors, [])
        self.assertTrue(server.plans.empty())


if __name__ == "__main__":
    unittest.main()
