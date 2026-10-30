"""Preview the real Next-step extension: isolated offline fixtures, or explicit --live use."""
import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time

REPO = Path(__file__).resolve().parents[1]
FIXTURES = json.loads(Path(__file__).with_suffix(".fixtures.json").read_text())
MAIN_MODEL = "preview-fixture/main"
SUGGESTION_MODEL = "preview-fixture/suggestion"


def standalone_binary():
    explicit = os.environ.get("OMP_BIN")
    candidates = [shutil.which(explicit)] if explicit else [str(Path(part) / "omp") for part in os.get_exec_path()]
    for candidate in candidates:
        if not candidate or not os.access(candidate, os.X_OK) or not Path(candidate).is_file():
            continue
        with open(candidate, "rb") as binary:
            magic = binary.read(4)
        if magic in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\x7fELF"):
            return candidate
    raise SystemExit("Set OMP_BIN to the official OMP 18.13.3+ standalone binary (not a wrapper).")


def clean_env(*, offline):
    # Keep local model/auth/config environment in live mode, but never inherit an app session.
    config_keys = {"PI_CODING_AGENT_DIR", "PI_CONFIG_DIR", "PI_CONFIG_FILES", "OMP_PROFILE"}
    env = {}
    for key, value in os.environ.items():
        if key in ("NO_COLOR", "CI", "COLORFGBG"):
            continue
        if key.startswith(("SUPER_ENGINEERING_", "SUPERCONDUCTOR_", "ZMX_", "SC_")):
            continue
        if key.startswith(("PI_", "OMP_")) and (offline or key not in config_keys):
            continue
        if offline and (key.startswith("XDG_") or key == "OLLAMA_HOST"
                        or any(word in key.upper() for word in ("TOKEN", "SECRET", "API_KEY", "PASSWORD", "BASE_URL"))
                        or key.upper().endswith("_KEY")):
            continue
        env[key] = value
    env.setdefault("TERM", "xterm-256color")
    return env


def text_content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(text_content(item) for item in value)
    if isinstance(value, dict):
        return text_content(value.get("content", value.get("text", "")))
    return ""


class FixtureServer(ThreadingHTTPServer):
    """Two independent Responses models; controls apply only to suggestion requests."""
    daemon_threads = True

    def __init__(self, delay=0.3):
        super().__init__(("127.0.0.1", 0), FixtureHandler)
        self.delay = max(0, delay)
        self.requests = []
        self.controls = deque()
        self.lock = threading.Lock()
        self.current_control = ("normal", self.delay, None)
        self.request_gates = set()

    def next_suggestion(self, mode="normal", delay=None, *, gate=None):
        with self.lock:
            self.controls.append((mode, self.delay if delay is None else delay, gate))
            if gate is not None:
                self.request_gates.add(gate)

    def model_requests(self, model):
        with self.lock:
            return [request for request in self.requests if request.get("model") == model.rsplit("/", 1)[-1]]

    def start(self):
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self

    def shutdown(self):
        with self.lock:
            for gate in self.request_gates:
                gate.set()
        super().shutdown()


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        suggestion = body.get("model") == "suggestion"
        if body.get("model") not in ("main", "suggestion"):
            self.send_error(400, "Only local fixture models are allowed")
            return
        messages = body.get("input", body.get("messages", []))
        serialized = text_content(messages)
        if suggestion:
            # The real model request includes recent conversation, including the latest assistant reply.
            scene = max(FIXTURES, key=lambda key: max(serialized.rfind(FIXTURES[key]["prompt"]),
                                                     serialized.rfind(FIXTURES[key]["reply"])))
            if not any(item["prompt"] in serialized or item["reply"] in serialized for item in FIXTURES.values()):
                scene = "done"
        else:
            latest = next((item for item in reversed(messages) if isinstance(item, dict) and item.get("role") == "user"), {})
            serialized = text_content(latest)
            scene = next((key for key, item in FIXTURES.items() if item["prompt"] in serialized), "done")
        with self.server.lock:
            self.server.requests.append(body)
            if not suggestion:
                delay_match = re.search(r"\[preview:delay=([\d.]+)\]", serialized)
                mode = "invalid" if "[preview:invalid]" in serialized else "failure" if "[preview:failure]" in serialized else "normal"
                self.server.current_control = (mode, float(delay_match[1]) if delay_match else self.server.delay, None)
            mode, delay, gate = (self.server.controls.popleft() if self.server.controls else self.server.current_control) if suggestion else ("normal", 0, None)
        if gate is not None:
            gate.wait()
            with self.server.lock:
                self.server.request_gates.discard(gate)
        time.sleep(max(0, delay))
        if mode == "failure":
            data = json.dumps({"error": {"message": "Injected preview suggestion failure", "type": "invalid_request_error"}}).encode()
            try:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        text = ("not valid JSON" if mode == "invalid" else json.dumps(FIXTURES[scene]["suggestion"], ensure_ascii=False)) if suggestion else FIXTURES[scene]["reply"]
        item = {"type": "message", "id": "msg_preview", "role": "assistant", "status": "completed",
                "phase": "final_answer", "content": [{"type": "output_text", "text": text, "annotations": []}]}
        response = {"id": "resp_preview", "object": "response", "status": "completed", "output": [item],
                    "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}}
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for kind, data in [
                ("response.created", {"response": response | {"status": "in_progress", "output": []}}),
                ("response.output_item.added", {"output_index": 0, "item": item | {"content": []}}),
                ("response.output_text.delta", {"output_index": 0, "item_id": item["id"], "delta": text}),
                ("response.output_item.done", {"output_index": 0, "item": item}),
                ("response.completed", {"response": response}),
            ]:
                self.wfile.write(f"event: {kind}\ndata: {json.dumps({'type': kind, **data}, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def offline_launch(binary, root, server, *, scene=None, effort="low", extra_extensions=()):
    """Build isolated source-run arguments; shared with real TUI regression tests."""
    root = Path(root)
    home = root / "home"
    agent = home / ".omp" / "agent"
    agent.mkdir(parents=True)
    config = {
        "startup": {"setupWizard": False, "checkUpdate": False, "quiet": True},
        "providers": {"cacheWarming": "off"}, "memory": {"backend": "off"},
        "disabledProviders": ["ollama", "llama.cpp", "lm-studio", "apple", "local", "web"],
        "retry": {"enabled": False, "modelFallback": False}, "compaction": {"enabled": False},
        "completion": {"notify": "off"}, "spelling": {"enabled": False},
        "skills": {"enableSkillCommands": True, "includeSkills": ["fixture-*"]},
        "composer": {"shape": "dotfiles/claude-context"},
    }
    models = {"providers": {"preview-fixture": {
        "baseUrl": f"http://127.0.0.1:{server.server_port}/v1", "api": "openai-responses",
        "auth": "apiKey", "apiKey": "local-fixture-only", "models": [
            {"id": model, "name": f"Next Step Fixture {model}", "reasoning": False,
             "input": ["text"], "contextWindow": 100000, "maxTokens": 2048}
            for model in ("main", "suggestion")
        ],
    }}}
    for name, data in (("config.yml", config), ("models.yml", models)):
        (agent / name).write_text(json.dumps(data, ensure_ascii=False))
    env = clean_env(offline=True)
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / "config"),
               XDG_DATA_HOME=str(home / "data"), XDG_CACHE_HOME=str(home / "cache"),
               PI_CODING_AGENT_DIR=str(agent), PI_CONFIG_DIR=str(agent), TERM="xterm-256color",
               NOTIFY_DRY_RUN="1", NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
    command = [binary, "--cwd", str(root), "--model", MAIN_MODEL, "--no-tools",
               "--no-extensions", "--no-rules", "--no-lsp", "--no-title", "--thinking", "off",
               "--session-dir", str(root / "sessions"), "--system-prompt", "Local fixture session. No tools or actions."]
    for path in (*extra_extensions, REPO / "packages/composer/src/index.ts",
                 REPO / "packages/skill-completion/src/index.ts", REPO / "packages/next-step/src/index.ts",
                 Path(__file__).with_suffix(".ts")):
        command.extend(("-e", str(path)))
    command.extend(("--next-step", "--next-step-model", SUGGESTION_MODEL,
                    "--next-step-effort", effort, "--next-step-data-dir", str(root / "feedback")))
    if scene:
        command.append(FIXTURES[scene]["prompt"])
    return command, env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Use existing local auth/config in this cwd; real model costs apply")
    parser.add_argument("--model", default="@next-step", help="Live suggestion model only (default: @next-step); main model is unchanged")
    parser.add_argument("--effort", default="low", help="Suggestion reasoning effort (default: low)")
    parser.add_argument("--delay", type=float, default=0.3, help="Offline suggestion delay in seconds")
    parser.add_argument("--scene", choices=FIXTURES, default="decision", help="Initial offline fixture scene")
    args = parser.parse_args()
    binary = standalone_binary()
    version = subprocess.check_output([binary, "--version"], text=True).strip()
    match = re.fullmatch(r"omp/(\d+)\.(\d+)\.(\d+)(?:[-+].+)?", version)
    if not match or tuple(map(int, match.groups())) < (18, 13, 3):
        raise SystemExit(f"Expected OMP 18.13.3 or newer, got {version}")
    if args.live:
        command = [binary, "--cwd", str(Path.cwd()), "--no-extensions"]
        entries = json.loads((REPO / "package.json").read_text())["omp"]["extensions"]
        for entry in dict.fromkeys([*entries, "packages/next-step/src/index.ts"]):
            command.extend(("-e", str(REPO / entry)))
        command.extend(("--next-step", "--next-step-model", args.model, "--next-step-effort", args.effort))
        print(f"Live native OMP · real model costs (one {args.model} suggestion request per completed turn).", flush=True)
        print("Uses existing auth/config and configured main model. Local conversation/draft feedback is collected at Next-step's default location; /next-step data off disables collection. No upload by this preview.", flush=True)
        return subprocess.call(command, cwd=Path.cwd(), env=clean_env(offline=False))
    server = FixtureServer(args.delay).start()
    try:
        with tempfile.TemporaryDirectory(prefix="omp-next-step-preview-") as directory:
            command, env = offline_launch(binary, directory, server, scene=args.scene, effort=args.effort)
            print("Real Next-step · offline loopback models · no paid LLM calls / install / production build", flush=True)
            print("/preview: scenes, delay and failure controls. Single: Enter sends, Tab/Right fills. Choices: first focused, none checked; Up/Down wraps; multiple only: Space toggles when the editor is empty and no popup is open. Enter sends checked drafts in option order (blank-line separated), or the focused draft; Tab/Right fills without sending. Typing hides the ghost but keeps choice cards read-only; typed Enter sends only your text. Esc cancels permanently and preserves your draft; native popups dismiss first. Alt+1/2/3 or /next-step pick only fills; cancelled/restarted results never revive. No extra model call to combine drafts. Temporary sessions/feedback are deleted on exit.", flush=True)
            return subprocess.call(command, cwd=directory, env=env)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
