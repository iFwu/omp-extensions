"""Real OMP 18.12.6 TUI + loopback models; no credentials, installs or production builds.

Run: python3 -m unittest discover -s packages/next-step/tests -v
Set OMP_BIN to a native OMP binary if it is not discoverable on PATH.
"""
import importlib.util
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import tempfile
import time
import unittest

if os.name == "posix":
    import fcntl
    import pty
    import termios

REPO = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("next_step_preview", REPO / "scripts/preview-next-action.py")
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)
try:
    OMP_BIN = preview.standalone_binary()
except SystemExit:
    OMP_BIN = None
# The suite and the standalone package persist the same settings under different names.
PERSISTENT = {
    "standalone": (REPO / "packages/next-step", "@ifwu/omp-next-step", (("enabled", "true"), ("collect", "false"))),
    "suite": (REPO, "@ifwu/omp-extensions", (("next-step", "true"), ("next-step-collect", "false"))),
}


class NativeSession:
    def __init__(self, testcase, persistent=None, delayed_input=False):
        self.testcase = testcase
        self.directory = tempfile.TemporaryDirectory(prefix="omp-next-step-test-")
        self.root = Path(self.directory.name)
        self.server = preview.FixtureServer(delay=0.05).start()
        self.snapshot = self.root / "editor.json"
        observer = self.root / "observer.ts"
        # Compose with the native editor to observe expanded text behind collapsed skill tokens.
        observer.write_text('''
import { writeFileSync, renameSync } from "node:fs";
import { CustomEditor } from "@oh-my-pi/pi-tui/prompt/custom-editor";
export default function(pi) {
 let timer;
 let editor;
 if (''' + json.dumps(delayed_input) + ''') pi.on("input",async()=>{await new Promise(resolve=>setTimeout(resolve,80));});
 pi.on("session_start",(_event,ctx)=>{
  const previous=ctx.ui.getEditorComponent();
  ctx.ui.setEditorComponent((tui,theme,keys)=>editor=previous?previous(tui,theme,keys):new CustomEditor(tui,theme,keys));
  clearInterval(timer);
  timer=setInterval(()=>{
   const path=''' + json.dumps(str(self.snapshot)) + ''';
   writeFileSync(path+".tmp",JSON.stringify({text:ctx.ui.getEditorText(),expanded:editor?.getExpandedText(),active:editor?.isAutocompleteActive(),rows:editor?.render(100).map(row=>Bun.stripANSI(row))}));
   renameSync(path+".tmp",path);
  },30);
 });
 pi.on("session_shutdown",()=>clearInterval(timer));
}
''')
        command, env = preview.offline_launch(OMP_BIN, self.root, self.server, extra_extensions=[observer])
        if persistent:
            package, name, settings = PERSISTENT[persistent]
            command.remove("--next-step")
            subprocess.run([OMP_BIN, "plugin", "install", str(package)],
                           cwd=self.root, env=env, check=True, capture_output=True, text=True)
            for key, value in settings:
                subprocess.run([OMP_BIN, "plugin", "config", "set", name, key, value],
                               cwd=self.root, env=env, check=True, capture_output=True, text=True)
        skills = self.root / "home/.omp/agent/skills/fixture-alpha"
        skills.mkdir(parents=True)
        (skills / "SKILL.md").write_text("---\nname: fixture-alpha\ndescription: Fixture completion\n---\nOnly a local skill fixture.\n")
        (self.root / "fixture-file.txt").write_text("Local file fixture\n")
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 45, 110, 0, 0))
        self.process = subprocess.Popen(command, cwd=self.root, env=env, stdin=slave, stdout=slave,
                                        stderr=slave, start_new_session=True)
        os.close(slave)
        self.output = bytearray()
        testcase.addCleanup(self.close)
        self.wait(lambda: self.snapshot.exists(), "editor startup", timeout=30)

    def drain(self, seconds=0.08):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if select.select([self.master], [], [], max(0, deadline - time.monotonic()))[0]:
                try:
                    data = os.read(self.master, 65536)
                except OSError:
                    return
                if not data:
                    return
                self.output.extend(data)

    def wait(self, predicate, description, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self.process.poll() is None:
            value = predicate()
            if value:
                return value
            self.drain()
        self.testcase.fail(f"Timed out: {description}\n{self.output[-8000:].decode(errors='replace')}")

    def send(self, text):
        os.write(self.master, text.encode())
        self.drain(0.12)

    def editor(self):
        return json.loads(self.snapshot.read_text())["text"] if self.snapshot.exists() else None

    def expect_draft(self, text):
        self.wait(lambda: self.editor() == text, f"draft {text!r}")

    def events(self, kind=None):
        events = []
        for path in sorted((self.root / "feedback").glob("*.jsonl")):
            for line in path.read_text().splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue  # A writer may still be completing the last line.
                if kind is None or event["type"] == kind:
                    events.append(event)
        return events

    def event(self, kind, after=0, predicate=lambda event: True):
        return self.wait(lambda: next((event for event in self.events(kind)[after:] if predicate(event)), None),
                         f"{kind} event after {after}")

    def requests(self, suggestion=False):
        return self.server.model_requests(preview.SUGGESTION_MODEL if suggestion else preview.MAIN_MODEL)

    def scene(self, scene):
        count = len(self.requests())
        self.send(f"/preview scene {scene}\r")
        self.wait(lambda: len(self.requests()) == count + 1, f"main request for {scene}")
        self.expect_draft("")

    def ready(self, scene="ready"):
        count = len(self.events("displayed"))
        self.scene(scene)
        self.event("displayed", after=count)
        self.wait(lambda: "Esc 忽略".encode() in self.output, "production suggestion widget")

    def clear(self):
        if json.loads(self.snapshot.read_text()).get("active"):
            self.send("\x1b")
            self.wait(lambda: not json.loads(self.snapshot.read_text()).get("active"), "popup dismissal")
        self.send("\x15")
        self.expect_draft("")

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        os.close(self.master)
        self.server.shutdown()
        self.server.server_close()
        self.directory.cleanup()


@unittest.skipUnless(os.name == "posix" and OMP_BIN, "Native POSIX OMP 18.12.6 binary required")
class NextStepTUITests(unittest.TestCase):
    def test_first_completion_none_single_choice(self):
        for scene, kind in (("done", "none"), ("ready", "single"), ("decision", "choice")):
            with self.subTest(kind=kind):
                session = NativeSession(self)
                session.scene(scene)
                generated = session.event("generated")
                self.assertEqual(generated["result"]["kind"], kind)
                for key in ("schema", "id", "at", "context", "model", "effort", "promptVersion", "latencyMs"):
                    self.assertIn(key, generated)
                self.assertEqual(generated["schema"], 1)
                self.assertEqual(len(session.requests()), 1)
                self.assertEqual(len(session.requests(suggestion=True)), 1)
                self.assertEqual(generated["effort"], "low")
                if kind == "none":
                    session.drain(0.4)
                    self.assertEqual(session.events("displayed"), [])
                    self.assertNotIn("Esc 忽略".encode(), session.output)
                else:
                    session.event("displayed")
                    session.wait(lambda: "Esc 忽略".encode() in session.output, "real production widget")
                session.expect_draft("")
                # Stop each independent first-turn session before starting another.
                self.doCleanups()

    def test_single_ghost_tab_right_accept_and_enter_sends_once(self):
        session = NativeSession(self, delayed_input=True)
        draft = preview.FIXTURES["ready"]["suggestion"]["actions"][0]["draft"]
        for key in ("\t", "\x1b[C"):
            session.ready()
            session.wait(lambda: draft in "\n".join(json.loads(session.snapshot.read_text())["rows"]), "visible ghost inside native editor")
            session.expect_draft("")
            count = len(session.requests())
            session.send(key)
            session.expect_draft(draft)
            self.assertEqual(len(session.requests()), count, "Tab/Right only adopts the ghost")
            session.clear()
        session.ready()
        count = len(session.requests())
        session.send("\r")
        session.event("submitted", predicate=lambda event: event["outcome"] == "accepted" and event["text"] == draft)
        session.wait(lambda: len(session.requests()) == count + 1, "Enter sends ghost through native submit")
        self.assertIn(draft, json.dumps(session.requests()[-1], ensure_ascii=False))
        session.event("generated", after=3)
        self.assertEqual(len(session.requests()), count + 1, "Ghost Enter submits exactly once")

    def test_typing_dismisses_ghost_without_reviving_and_choices_have_no_default(self):
        session = NativeSession(self)
        draft = preview.FIXTURES["ready"]["suggestion"]["actions"][0]["draft"]
        session.ready()
        session.send("验证")
        session.expect_draft("验证")
        self.assertNotIn(draft, "\n".join(json.loads(session.snapshot.read_text())["rows"]))
        session.clear()
        session.drain(0.2)
        self.assertNotIn(draft, "\n".join(json.loads(session.snapshot.read_text())["rows"]))
        session.ready("decision")
        editor_rows = "\n".join(json.loads(session.snapshot.read_text())["rows"])
        for action in preview.FIXTURES["decision"]["suggestion"]["actions"]:
            self.assertNotIn(action["draft"], editor_rows)
        count = len(session.requests())
        session.send("\r")
        session.drain(0.2)
        self.assertEqual(len(session.requests()), count, "Enter must not pick a choice implicitly")
        self.assertEqual(session.events("accepted"), [])

    def test_arrow_selected_choice_enter_sends_and_tab_fills(self):
        session = NativeSession(self, delayed_input=True)
        actions = preview.FIXTURES["decision"]["suggestion"]["actions"]
        session.ready("decision")
        count = len(session.requests())
        for key in ("\x1b[B", "\x1b[A", "\x1b[A"):
            session.send(key)
        session.wait(lambda: actions[1]["draft"] in "\n".join(json.loads(session.snapshot.read_text())["rows"]),
                     "selected choice previewed in native editor")
        session.expect_draft("")
        self.assertEqual(session.events("accepted"), [], "arrow selection alone must not adopt")
        self.assertEqual(len(session.requests()), count, "arrow selection must not send")
        session.send("\r")
        session.event("submitted", predicate=lambda event: event["outcome"] == "accepted" and event["text"] == actions[1]["draft"])
        session.wait(lambda: len(session.requests()) == count + 1, "Enter sends selected choice once")
        self.assertIn(actions[1]["draft"], json.dumps(session.requests()[-1], ensure_ascii=False))
        session.event("generated", after=1)
        session.ready("decision")
        count = len(session.requests())
        session.send("\x1b[A")
        session.send("\x1b[B")
        session.send("\t")
        session.expect_draft(actions[0]["draft"])
        self.assertEqual(len(session.requests()), count, "Tab only fills the selected choice")

    def test_alt_accept_does_not_send_and_submitted_outcomes(self):
        session = NativeSession(self)
        session.ready("decision")
        session.send("\x1b2")
        draft = preview.FIXTURES["decision"]["suggestion"]["actions"][1]["draft"]
        session.expect_draft(draft)
        accepted = session.event("accepted")
        self.assertEqual(accepted["index"], 1)
        self.assertEqual(accepted["draft"], draft)
        self.assertEqual(len(session.requests()), 1, "Alt acceptance must not send to main model")
        session.send("\r")
        session.event("submitted", predicate=lambda event: event["outcome"] == "accepted" and event["text"] == draft)
        session.wait(lambda: len(session.requests()) == 2, "explicit Enter main request")
        session.event("generated", after=1)
        session.ready()
        session.send("\x1b1")
        draft = preview.FIXTURES["ready"]["suggestion"]["actions"][0]["draft"]
        session.expect_draft(draft)
        count = len(session.requests())
        session.send(" 只检查本地。")
        edited = draft + " 只检查本地。"
        session.expect_draft(edited)
        self.assertEqual(len(session.requests()), count)
        session.send("\r")
        session.event("submitted", predicate=lambda event: event["outcome"] == "edited" and event["text"] == edited)

    def test_own_draft_is_preserved_and_records_other_submission(self):
        session = NativeSession(self)
        session.ready()
        session.send("这是我自己的草稿")
        session.send("\x1b1")
        session.expect_draft("这是我自己的草稿")
        self.assertEqual(session.events("accepted"), [])
        self.assertEqual(len(session.requests()), 1)
        session.send("\r")
        session.event("submitted", predicate=lambda event: event["outcome"] == "other" and event["text"] == "这是我自己的草稿")

    def test_delayed_result_stays_cancelled_after_typing_and_delete_to_empty(self):
        session = NativeSession(self)
        session.server.next_suggestion(delay=1.5)
        session.scene("ready")
        session.wait(lambda: len(session.requests(suggestion=True)) == 1, "delayed suggestion started")
        session.send("temporary draft")
        session.send("\x15")
        session.expect_draft("")
        session.event("cancelled")
        session.drain(1.8)
        self.assertEqual(session.events("displayed"), [], "Deleting typed text must not revive stale results")
        session.send("\x1b1")
        session.expect_draft("")
        self.assertEqual(len(session.requests()), 1)
        session.ready("decision")

    def test_new_and_off_cancel_inflight_and_allow_recovery(self):
        session = NativeSession(self)
        for command in ("/new", "/next-step off"):
            with self.subTest(command=command):
                displayed = len(session.events("displayed"))
                cancelled = len(session.events("cancelled"))
                suggestions = len(session.requests(suggestion=True))
                session.server.next_suggestion(delay=1.5)
                session.scene("ready")
                session.wait(lambda: len(session.requests(suggestion=True)) > suggestions, "delayed request")
                session.send(command + "\r")
                session.expect_draft("")
                session.event("cancelled", after=cancelled)
                if command == "/new":
                    session.event("ended")
                session.drain(1.8)
                self.assertEqual(len(session.events("displayed")), displayed)
                session.send("\x1b1")
                session.expect_draft("")
                if command.endswith("off"):
                    count = len(session.requests(suggestion=True))
                    session.scene("ready")
                    session.drain(0.6)
                    self.assertEqual(len(session.requests(suggestion=True)), count)
                    session.send("/next-step on\r")
        session.ready("decision")

    def test_provider_and_invalid_json_failures_do_not_poison_later_turns(self):
        session = NativeSession(self)
        for mode in ("failure", "invalid"):
            with self.subTest(mode=mode):
                count = len(session.events("failed"))
                shown = len(session.events("displayed"))
                session.server.next_suggestion(mode)
                session.scene("ready")
                session.event("failed", after=count)
                self.assertEqual(len(session.events("displayed")), shown)
                session.expect_draft("")
                session.ready("decision")
                session.send("\x1b3")
                session.expect_draft(preview.FIXTURES["decision"]["suggestion"]["actions"][2]["draft"])
                session.clear()

    def test_real_pick_command_fills_draft_without_submitting(self):
        session = NativeSession(self)
        session.ready("decision")
        count = len(session.requests())
        session.send("/next-step pick\r")
        session.drain(0.3)
        session.send("\r")
        draft = preview.FIXTURES["decision"]["suggestion"]["actions"][0]["draft"]
        session.expect_draft(draft)
        session.event("accepted")
        self.assertEqual(len(session.requests()), count, "Picker acceptance must not submit the draft")

    def test_native_file_slash_and_skill_tab_completion(self):
        session = NativeSession(self)
        session.ready()
        count = len(session.requests())
        session.send("@fixture-fi")
        session.send("\t")
        session.wait(lambda: "fixture-file.txt" in (session.editor() or ""), "native file Tab completion")
        session.clear()
        session.send("/next-ste")
        session.send("\t")
        session.wait(lambda: (session.editor() or "").startswith("/next-step"), "native slash Tab completion")
        session.clear()
        session.send("$fixture-a")
        session.wait(lambda: json.loads(session.snapshot.read_text()).get("active") and "skill:fixture-alpha" in "\n".join(json.loads(session.snapshot.read_text()).get("rows", [])), "settled skill popup")
        session.send("\t")
        session.wait(lambda: json.loads(session.snapshot.read_text()).get("expanded") == "/skill:fixture-alpha ", "expanded native skill draft")
        self.assertEqual(len(session.requests()), count, "Tab completion must not submit or accept next-step")
        self.assertEqual(session.events("accepted"), [])

    def test_cleared_acceptance_is_other_and_shutdown_is_not_rejection(self):
        session = NativeSession(self)
        session.ready()
        session.send("\x1b1")
        session.event("accepted")
        session.clear()
        session.send("换个话题，说明当前状态。\r")
        session.event("submitted", predicate=lambda event: event["outcome"] == "other")
        session.event("generated", after=1)
        session.ready("decision")
        session.send("\x03")
        session.send("\x03")
        session.drain(0.5)
        ended = next((event for event in session.events("ended") if event["reason"] == "session shutdown"), None)
        self.assertIsNotNone(ended)
        self.assertTrue(ended["displayed"])
        self.assertFalse(ended["accepted"])

    def test_native_persistent_enable_and_collection_false(self):
        for persistent in PERSISTENT:
            with self.subTest(persistent):
                session = NativeSession(self, persistent=persistent)
                session.scene("decision")
                session.wait(lambda: "Esc 忽略".encode() in session.output, "persistently enabled widget")
                session.send("\x1b1")
                session.expect_draft(preview.FIXTURES["decision"]["suggestion"]["actions"][0]["draft"])
                self.assertEqual(session.events(), [])
                self.assertEqual(len(session.requests()), 1)

    def test_data_off_stops_local_collection(self):
        session = NativeSession(self)
        session.ready()
        session.send("/next-step data off\r")
        session.drain(0.2)
        count = len(session.events())
        requests = len(session.requests(suggestion=True))
        session.scene("decision")
        session.wait(lambda: len(session.requests(suggestion=True)) > requests, "suggestion with collection disabled")
        session.drain(0.5)
        session.send("\x1b1")
        session.expect_draft(preview.FIXTURES["decision"]["suggestion"]["actions"][0]["draft"])
        self.assertEqual(len(session.events()), count)


if __name__ == "__main__":
    unittest.main()
