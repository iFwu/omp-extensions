"""Dollar skill selection through the installed OMP editor and invocation pipeline."""
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

from support import OMP_BIN, SRC, isolated_env, write_yaml

if os.name == "posix":
    import fcntl
    import pty
    import termios


@unittest.skipUnless(os.name == "posix" and OMP_BIN, "POSIX OMP TUI required")
class SkillCompletionTests(unittest.TestCase):
    def test_dollar_popup_selection_and_native_invocation(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                text = f"SKILL_REPLY_{len(requests)}"
                item = {"type": "message", "id": "msg", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]}
                response = {"id": "resp", "object": "response", "status": "completed", "output": [item],
                            "usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}}
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for kind, data in [
                    ("response.created", {"response": response | {"status": "in_progress", "output": []}}),
                    ("response.output_item.added", {"output_index": 0, "item": item | {"content": []}}),
                    ("response.output_text.delta", {"output_index": 0, "item_id": "msg", "delta": text}),
                    ("response.output_item.done", {"output_index": 0, "item": item}),
                    ("response.completed", {"response": response}),
                ]:
                    self.wfile.write(f"event: {kind}\ndata: {json.dumps({'type': kind} | data)}\n\n".encode())
                    self.wfile.flush()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory(prefix="omp-skill-completion-") as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            fault = root / "fault"
            for name in ("fixture-alpha", "fixture-beta"):
                skill = root / "skills" / name / "SKILL.md"
                skill.parent.mkdir(parents=True)
                skill.write_text(f"---\nname: {name}\ndescription: Choose {name}\n---\nSKILL_BODY_{name}\n")
            (root / "fixture-file.txt").write_text("File completion fixture\n")
            observer = root / "observer.ts"
            observer.write_text('''
import { CustomEditor } from "@oh-my-pi/pi-tui/prompt/custom-editor";
import { writeFileSync, existsSync, unlinkSync } from "node:fs";
export default function(pi) {
 let editor;
 pi.on("session_start",(_event,ctx)=>{
  ctx.ui.addAutocompleteProvider(current=>({
   getSuggestions:async(...args)=>{
    const result=await current.getSuggestions(...args);
    if(existsSync(''' + json.dumps(str(fault)) + ''') && args[0][0].startsWith("/skill:")) {
     unlinkSync(''' + json.dumps(str(fault)) + ''');
     return {get items(){throw new Error("Injected dollar result failure");}};
    }
    return result;
   },
   applyCompletion:current.applyCompletion.bind(current),
   getForceFileSuggestions:current.getForceFileSuggestions?.bind(current),
   shouldTriggerFileCompletion:current.shouldTriggerFileCompletion?.bind(current),
   getInlineHint:current.getInlineHint?.bind(current),
   trySyncSlashCompletion:current.trySyncSlashCompletion?.bind(current),
   trySyncInlineReplace:current.trySyncInlineReplace?.bind(current),
  }));
  ctx.ui.setEditorComponent((tui,theme,keys)=>editor=new CustomEditor(tui,theme,keys));
 });
 pi.registerShortcut("ctrl+alt+s",{description:"Snapshot fixture editor",handler:(_ctx)=>{
  writeFileSync(''' + json.dumps(str(snapshot)) + ''',JSON.stringify({
   text:editor.getExpandedText(),cursor:editor.getCursor(),active:editor.isShowingAutocomplete(),
   rows:editor.render(80).map(row=>Bun.stripANSI(row)),
   narrow:editor.render(40).map(row=>Bun.stripANSI(row)),
  }));
 }});
}
''')
            write_yaml(root / "models.yml", {"providers": {"skills-test": {
                "baseUrl": f"http://127.0.0.1:{server.server_port}/v1", "api": "openai-responses",
                "auth": "apiKey", "apiKey": "test-only", "models": [{"id": "fixture", "name": "Skill Fixture",
                "reasoning": False, "input": ["text"], "contextWindow": 100000, "maxTokens": 1024}],
            }}})
            write_yaml(root / "config.yml", {
                "startup": {"setupWizard": False, "checkUpdate": False, "quiet": True},
                "providers": {"cacheWarming": "off"}, "retry": {"enabled": False, "modelFallback": False},
                "compaction": {"enabled": False}, "completion": {"notify": "off"},
                "skills": {"enableSkillCommands": True, "includeSkills": ["fixture-*"]}, "spelling": {"enabled": False},
            })
            env = isolated_env(directory)
            env.update(PI_CODING_AGENT_DIR=directory, TERM="xterm-256color", NOTIFY_DRY_RUN="1")
            env.pop("PI_CONFIG_FILES", None)
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 80, 0, 0))
            process = subprocess.Popen([
                OMP_BIN, "--cwd", directory, "--model", "skills-test/fixture", "--tools", "read",
                "--no-extensions", "-e", str(observer), "-e", str(SRC / "skill-completion.ts"),
                "--no-rules", "--no-lsp", "--no-title", "--thinking", "off", "--session-dir", str(root / "sessions"),
            ], env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
            os.close(slave)
            output = bytearray()

            def drain(seconds=0.15):
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

            def wait_for(text):
                deadline = time.monotonic() + 30
                while text.encode() not in output and time.monotonic() < deadline and process.poll() is None:
                    drain()
                self.assertIn(text.encode(), output, output[-6000:].decode(errors="replace"))

            def send(text):
                os.write(master, text.encode())
                drain(0.3)

            def capture():
                snapshot.unlink(missing_ok=True)
                send("\x1b\x13")
                deadline = time.monotonic() + 5
                while not snapshot.exists() and time.monotonic() < deadline:
                    drain()
                self.assertTrue(snapshot.exists(), output[-6000:].decode(errors="replace"))
                return json.loads(snapshot.read_text())

            def clear():
                send("\x1b")
                send("\x15")

            try:
                wait_for("Skill Fixture")
                send("$")
                state = capture()
                self.assertEqual(state["text"], "$")
                self.assertTrue(state["active"], state)
                self.assertIn("fixture-alpha", "\n".join(state["rows"]))
                self.assertIn("fixture-beta", "\n".join(state["narrow"]))
                send("fixture-b")
                state = capture()
                self.assertIn("fixture-beta", "\n".join(state["rows"]))
                self.assertNotIn("fixture-alpha", "\n".join(state["rows"]))
                send("\t")
                self.assertEqual(capture()["text"], "/skill:fixture-beta ")
                send("requested argument\r")
                wait_for("SKILL_REPLY_1")
                serialized = json.dumps(requests[0])
                self.assertIn("SKILL_BODY_fixture-beta", serialized)
                self.assertIn("requested argument", serialized)

                send("Please $fixture-a suffix")
                send("\x1b[D" * len(" suffix"))
                send("\t")
                send("\r")
                self.assertEqual(capture()["text"], "Please /skill:fixture-alpha  suffix")
                self.assertEqual(len(requests), 1, "Accepting a skill must not submit the draft")
                send("\r")
                wait_for("SKILL_REPLY_2")
                self.assertIn("SKILL_BODY_fixture-alpha", json.dumps(requests[-1]))
                self.assertIn("Please", json.dumps(requests[-1]))
                self.assertIn("suffix", json.dumps(requests[-1]))
                send("$")
                send("\x1b")
                state = capture()
                self.assertEqual(state["text"], "$")
                self.assertFalse(state["active"])
                clear()

                for literal in ("$HOME", "${HOME}", "$(pwd)", "\\$fixture", "!echo $fixture", "`$fixture", "$99", "$unknown"):
                    with self.subTest(literal=literal):
                        send(literal)
                        state = capture()
                        self.assertEqual(state["text"], literal)
                        self.assertFalse(state["active"], state)
                        clear()
                send("/skill:fixture-a")
                send("\t")
                self.assertEqual(capture()["text"], "/skill:fixture-alpha ")
                clear()
                send("@fixture-file")
                send("\t")
                self.assertEqual(capture()["text"], "@fixture-file.txt ")
                clear()
                for sigil, prose in (("¥", ""), ("￥", "检查 ")):
                    with self.subTest(sigil=sigil):
                        send(prose)
                        send(sigil)
                        state = capture()
                        self.assertEqual(state["text"], prose + sigil)
                        self.assertTrue(state["active"], state)
                        self.assertIn("fixture-alpha", "\n".join(state["rows"]))
                        send("100")
                        state = capture()
                        self.assertEqual(state["text"], prose + sigil + "100")
                        self.assertFalse(state["active"], state)
                        clear()
                        send(prose)
                        send(sigil)
                        send("fixture-b")
                        state = capture()
                        self.assertIn("fixture-beta", "\n".join(state["rows"]))
                        self.assertNotIn("fixture-alpha", "\n".join(state["rows"]))
                        send("\r")
                        self.assertEqual(capture()["text"], prose + "/skill:fixture-beta ")
                        next_reply = len(requests) + 1
                        send("yuan argument\r")
                        wait_for(f"SKILL_REPLY_{next_reply}")
                        self.assertIn("SKILL_BODY_fixture-beta", json.dumps(requests[-1]))
                        self.assertIn("yuan argument", json.dumps(requests[-1]))
                        if prose:
                            self.assertIn(prose.strip(), json.dumps(requests[-1], ensure_ascii=False))

                fault.write_text("inject once")
                send("$")
                self.assertFalse(fault.exists(), "Fault injection did not reach the completion path")
                state = capture()
                self.assertEqual(state["text"], "$")
                self.assertFalse(state["active"])
                clear()
                next_reply = len(requests) + 1
                send("Still works after failure\r")
                wait_for(f"SKILL_REPLY_{next_reply}")
                self.assertIn("Still works after failure", json.dumps(requests[-1]))
                send("/new\r")
                drain(1)
                send("$")
                self.assertFalse(capture()["active"])
                clear()
                send("/skill:fixture-a")
                send("\t")
                self.assertEqual(capture()["text"], "/skill:fixture-alpha ")
                print("Real OMP: dollar popup, filtering, selection, native skill body/args, draft suffix, shell exclusions, native file/slash completion and failure recovery passed")
            finally:
                if process.poll() is None:
                    os.write(master, b"\x03\x03")
                    drain(1)
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=10)
                os.close(master)


if __name__ == "__main__":
    unittest.main()
