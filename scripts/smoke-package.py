"""Pack the public payload, install it with OMP, and complete an isolated RPC turn."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tarfile
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_support import isolated_env, write_yaml

REPO = Path(__file__).resolve().parents[1]
TEXT = "PACKAGE_SMOKE_OK"


def smoke_package(package_directory, install_source=None):
    binary = shutil.which(os.environ.get("OMP_BIN", "omp"))
    if not binary:
        raise RuntimeError("Set OMP_BIN to the official OMP 18.12.6 standalone binary")
    with tempfile.TemporaryDirectory(prefix="omp-package-") as directory:
        root = Path(directory)
        home = root / "home"
        home.mkdir()
        agent = home / ".omp" / "agent"
        agent.mkdir(parents=True)
        env = isolated_env(root)
        env.update(PI_CODING_AGENT_DIR=str(agent), PI_CONFIG_DIR=str(agent), PI_NO_TITLE="1")
        packed = subprocess.run(["npm", "pack", "--json", "--ignore-scripts", "--pack-destination", str(root)],
                                cwd=package_directory, env=env, check=True, capture_output=True, text=True)
        archive = root / json.loads(packed.stdout)[0]["filename"]
        with tarfile.open(archive) as package:
            for member in package.getmembers():
                assert not {".git", ".venv", "node_modules", "tests", "test_support", "scripts"}.intersection(Path(member.name).parts), member.name
            package.extractall(root, filter="data")
        manifest = json.loads((root / "package/package.json").read_text())
        payload = root / "package"
        for entry in manifest["omp"]["extensions"]:
            target = (payload / entry).resolve()
            assert target.is_relative_to(payload.resolve()) and target.is_file(), entry
        source = install_source or str(root / "package")
        for args in (["plugin", "install", source], ["plugin", "doctor"], ["plugin", "list", "--json"]):
            result = subprocess.run([binary, *args], cwd=root, env=env, check=True,
                                    capture_output=True, text=True, timeout=120)
            print(result.stdout)
            if args[1] == "list":
                plugins = json.loads(result.stdout)["npm"]
                enabled = [plugin for plugin in plugins if plugin["enabled"]]
                assert len(enabled) == 1 and enabled[0]["name"] == manifest["name"], enabled
                assert enabled[0]["version"] == manifest["version"], enabled

        class Handler(BaseHTTPRequestHandler):
            calls = 0

            def log_message(self, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                Handler.calls += 1
                item = {"type": "message", "id": "msg_smoke", "role": "assistant", "status": "completed",
                        "phase": "final_answer", "content": [{"type": "output_text", "text": TEXT, "annotations": []}]}
                response = {"id": "resp_smoke", "object": "response", "status": "completed", "output": [item],
                            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for kind, data in [
                    ("response.created", {"response": response | {"status": "in_progress", "output": []}}),
                    ("response.output_item.added", {"output_index": 0, "item": item | {"content": []}}),
                    ("response.output_text.delta", {"output_index": 0, "item_id": item["id"], "delta": TEXT}),
                    ("response.output_item.done", {"output_index": 0, "item": item}),
                    ("response.completed", {"response": response}),
                ]:
                    self.wfile.write((f"event: {kind}\ndata: " + json.dumps({"type": kind, **data}) + "\n\n").encode())
                    self.wfile.flush()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        config = {"startup": {"setupWizard": False, "checkUpdate": False, "quiet": True},
                  "providers": {"cacheWarming": "off"},
                  "retry": {"enabled": False, "modelFallback": False}, "compaction": {"enabled": False},
                  "memory": {"backend": "off"}, "completion": {"notify": "off"}}
        if manifest["name"] in {"@ifwu/omp-extensions", "@ifwu/omp-composer"}:
            config["composer"] = {"shape": "dotfiles/claude-context"}
        models = {"providers": {"package-fixture": {"baseUrl": f"http://127.0.0.1:{server.server_port}/v1",
                  "api": "openai-responses", "auth": "apiKey", "apiKey": "fixture-only",
                  "models": [{"id": "fixture", "name": "Package Fixture", "input": ["text"],
                              "contextWindow": 100000, "maxTokens": 1024}]}}}
        for name, value in (("config.yml", config), ("models.yml", models)):
            write_yaml(agent / name, value)
        frames = queue.Queue()
        with (root / "stderr.log").open("w+") as stderr:
            process = subprocess.Popen([binary, "--mode", "rpc-ui", "--no-tools", "--no-skills", "--no-rules",
                                        "--no-title", "--provider", "package-fixture", "--model", "fixture"],
                                       cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=stderr, text=True)
            def collect():
                for line in process.stdout:
                    frames.put(json.loads(line))
                frames.put(None)
            threading.Thread(target=collect, daemon=True).start()
            transcript = []
            def receive(predicate):
                deadline = time.monotonic() + 90
                while True:
                    frame = frames.get(timeout=max(0.01, deadline - time.monotonic()))
                    if frame is None:
                        raise AssertionError("OMP exited before smoke completed")
                    transcript.append(frame)
                    assert frame.get("type") != "extension_error", frame
                    assert not (frame.get("type") == "response" and frame.get("success") is False), frame
                    if predicate(frame):
                        return frame
            def send(value):
                process.stdin.write(json.dumps(value) + "\n")
                process.stdin.flush()
            try:
                receive(lambda frame: frame.get("type") == "ready")
                send({"id": "state", "type": "get_state"})
                receive(lambda frame: frame.get("id") == "state")
                send({"id": "smoke", "type": "prompt", "message": "Reply with the package fixture marker."})
                result = receive(lambda frame: frame.get("type") == "prompt_result" and frame.get("id") == "smoke")
                assert result["status"] == "completed", result
                send({"id": "messages", "type": "get_messages"})
                messages = receive(lambda frame: frame.get("id") == "messages")
                assert TEXT in json.dumps(messages), messages
                assert Handler.calls == 1, Handler.calls
                process.stdin.close()
                process.wait(timeout=30)
                assert process.returncode == 0, process.returncode
                stderr.seek(0)
                errors = stderr.read()
                assert not any(word in errors.lower() for word in ("failed to load extension", "[skill-completion]", "[claude-context]", "[transcript-grouping]", "[ask-history]")), errors
            except BaseException:
                stderr.seek(0)
                print(stderr.read())
                print(json.dumps(transcript, indent=2))
                raise
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                server.shutdown()
                server.server_close()
        print(f'{manifest["name"]}@{manifest["version"]}: packed payload, plugin install/doctor, and isolated RPC reply completed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git-source", help="Smoke only the suite using an exact Git ref matching this checkout")
    args = parser.parse_args()
    smoke_package(REPO, args.git_source)
    if not args.git_source:
        for manifest in sorted(REPO.glob("packages/*/package.json")):
            smoke_package(manifest.parent)


if __name__ == "__main__":
    main()
