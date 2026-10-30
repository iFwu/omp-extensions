"""Real OMP 18.13.3+ TUI + loopback models; no credentials, installs or production builds.

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
import threading
import time
import unittest

from test_support import set_next_step_time, write_next_step_clock

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


def popup_shows(session, label):
    state = session.state()
    return state.get("active") and label in "\n".join(state.get("rows", []))


class NativeSession:
    def __init__(self, testcase, persistent=None, delayed_input=False, controlled_time=False):
        self.testcase = testcase
        self.directory = tempfile.TemporaryDirectory(prefix="omp-next-step-test-")
        self.root = Path(self.directory.name)
        self.process = None
        self.master = None
        self.server = preview.FixtureServer(delay=0.05).start()
        testcase.addCleanup(self.close)
        self.snapshot = self.root / "editor.json"
        observer = self.root / "observer.ts"
        # Observe the composed native editor and actual widget renders, not terminal scrollback.
        observer.write_text('''
import { writeFileSync, renameSync } from "node:fs";
import { CustomEditor } from "@oh-my-pi/pi-tui/prompt/custom-editor";
export default function(pi) {
 let timer;
 let editor;
 let host;
 let observedUI;
 const widgets={};
 const notifications=[];
 if (''' + json.dumps(delayed_input) + ''') pi.on("input",async()=>{await new Promise(resolve=>setTimeout(resolve,80));});
 pi.on("session_start",(_event,ctx)=>{
  if(observedUI!==ctx.ui){
   observedUI=ctx.ui;
   const notify=ctx.ui.notify.bind(ctx.ui);
   ctx.ui.notify=(message,level)=>{notifications.push({message,level});return notify(message,level);};
   const setWidget=ctx.ui.setWidget.bind(ctx.ui);
   ctx.ui.setWidget=(key,content,options)=>{
    delete widgets[key];
    if(Array.isArray(content)) widgets[key]=content.map(row=>Bun.stripANSI(row));
    return setWidget(key,typeof content!=="function"?content:(tui,theme)=>{
     const component=content(tui,theme);
     const render=component.render;
     component.render=width=>{
      const rows=render.call(component,width);
      widgets[key]=rows.map(row=>Bun.stripANSI(row));
      return rows;
     };
     return component;
    },options);
   };
  }
  const previous=ctx.ui.getEditorComponent();
  ctx.ui.setEditorComponent((tui,theme,keys)=>{
   host=tui;
   return editor=previous?previous(tui,theme,keys):new CustomEditor(tui,theme,keys);
  });
  clearInterval(timer);
  timer=setInterval(()=>{
   const path=''' + json.dumps(str(self.snapshot)) + ''';
   writeFileSync(path+".tmp",JSON.stringify({text:ctx.ui.getEditorText(),expanded:editor?.getExpandedText(),active:editor?.isAutocompleteActive(),rows:editor?.render(100).map(row=>Bun.stripANSI(row)),widgets,notifications,overlay:host?.hasOverlay(),editorFocused:host?.getFocused()===editor,sessionFile:ctx.sessionManager.getSessionFile(),sessionId:ctx.sessionManager.getSessionId()}));
   renameSync(path+".tmp",path);
  },30);
 });
 pi.on("session_shutdown",()=>clearInterval(timer));
}
''')
        command, env = preview.offline_launch(OMP_BIN, self.root, self.server, extra_extensions=[observer])
        if controlled_time:
            source = str(REPO / "packages/next-step/src/index.ts")
            command[command.index(source)] = str(write_next_step_clock(self.root))
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
        self.command = command
        self.env = env
        self.start(command)
        self.wait(lambda: self.snapshot.exists(), "editor startup", timeout=30)

    def start(self, command):
        self.output = bytearray()
        self.master, slave = pty.openpty()
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 45, 110, 0, 0))
            self.process = subprocess.Popen(command, cwd=self.root, env=self.env, stdin=slave, stdout=slave,
                                            stderr=slave, start_new_session=True)
        except BaseException:
            os.close(self.master)
            self.master = None
            raise
        finally:
            os.close(slave)

    def restart(self, resume=False):
        session_file = self.state()["sessionFile"] if resume else None
        self.stop()
        self.snapshot.unlink(missing_ok=True)
        self.start(self.command + (["--session", session_file] if resume else []))
        self.wait(lambda: self.snapshot.exists(), "restarted editor startup", timeout=30)

    def state(self):
        return json.loads(self.snapshot.read_text()) if self.snapshot.exists() else {}

    def rows(self):
        return "\n".join(self.state().get("rows", []))

    def widget(self):
        return self.state().get("widgets", {}).get("ifwu.next-step", [])

    def expect_cards(self, scene, focused=0, checked=()):
        result = preview.FIXTURES[scene]["suggestion"]

        def matching_cards():
            rows = self.widget()
            rendered = "\n".join(rows)
            if result["question"] not in rendered:
                return False
            for index, action in enumerate(result["actions"]):
                title_row = next((row for row in rows if action["title"] in row), "")
                if not title_row or action["tradeoff"] not in rendered or (("›" in title_row) != (index == focused)):
                    return False
                if result["selectionMode"] == "multiple":
                    if ("[x]" if index in checked else "[ ]") not in title_row:
                        return False
            return True

        self.wait(matching_cards, f"{scene} cards, focus={focused}, checked={checked}")

    def expect_no_suggestion(self):
        self.wait(lambda: not self.widget(), "no suggestion widget")
        if self.editor() == "":
            for fixture in preview.FIXTURES.values():
                for action in fixture["suggestion"]["actions"]:
                    self.testcase.assertNotIn(action["draft"], self.rows())

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

    def set_time(self, milliseconds):
        set_next_step_time(self.root, milliseconds)
        observed = self.root / "next-step-clock-observed.json"
        self.wait(lambda: observed.exists() and json.loads(observed.read_text()) == milliseconds,
                  f"next-step clock observed {milliseconds}ms")

    def send(self, text):
        os.write(self.master, text.encode())
        self.drain(0.12)

    def editor(self):
        return self.state().get("text")

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
        if preview.FIXTURES[scene]["suggestion"]["kind"] == "choice":
            self.expect_cards(scene)
        else:
            self.wait(lambda: bool(self.widget()), "production suggestion widget")

    def clear(self):
        if self.state().get("active"):
            self.send("\x1b")
            self.wait(lambda: not self.state().get("active"), "popup dismissal")
        self.send("\x15")
        self.expect_draft("")

    def stop(self):
        try:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                deadline = time.monotonic() + 5
                while self.process.poll() is None and (remaining := deadline - time.monotonic()) > 0:
                    self.drain(min(0.08, remaining))
                if self.process.poll() is None:
                    self.process.kill()
                    self.process.wait(timeout=5)
        finally:
            if self.master is not None:
                os.close(self.master)
                self.master = None

    def close(self):
        try:
            self.stop()
        finally:
            try:
                self.server.shutdown()
            finally:
                try:
                    self.server.server_close()
                finally:
                    self.directory.cleanup()


@unittest.skipUnless(os.name == "posix" and OMP_BIN, "Native POSIX OMP 18.13.3+ binary required")
class NextStepTUITests(unittest.TestCase):
    def assert_submission_payload(self, session, scene, text):
        request = session.requests()[-1]
        messages = request.get("input", request.get("messages", []))
        users = [preview.text_content(message) for message in messages
                 if isinstance(message, dict) and message.get("role") == "user"]
        initial = session.requests()[0]
        initial_users = [preview.text_content(message) for message in initial.get("input", initial.get("messages", []))
                         if isinstance(message, dict) and message.get("role") == "user"]
        self.assertEqual(users, [*initial_users, text], "Only the submitted draft may extend native user context")
        serialized = json.dumps(request, ensure_ascii=False)
        result = preview.FIXTURES[scene]["suggestion"]
        for value in (result["reason"], result["question"]):
            if value:
                self.assertNotIn(value, serialized, "Suggestion metadata must not enter the main model context")
        for action in result["actions"]:
            if action["draft"] not in text:
                self.assertNotIn(action["draft"], serialized, "Unsubmitted drafts must not enter the main model context")

    def test_first_completion_none_single_choice(self):
        for scene, kind in (("done", "none"), ("ready", "single"), ("decision", "choice"), ("maintenance", "choice")):
            with self.subTest(scene=scene):
                session = NativeSession(self)
                session.scene(scene)
                generated = session.event("generated")
                self.assertEqual(generated["result"]["kind"], kind)
                for key in ("schema", "id", "at", "context", "model", "effort", "promptVersion", "latencyMs"):
                    self.assertIn(key, generated)
                self.assertEqual(generated["schema"], 2)
                if kind == "choice":
                    self.assertEqual(generated["result"]["selectionMode"], preview.FIXTURES[scene]["suggestion"]["selectionMode"])
                else:
                    self.assertNotIn("selectionMode", generated["result"])
                self.assertEqual(len(session.requests()), 1)
                self.assertEqual(len(session.requests(suggestion=True)), 1)
                self.assertEqual(generated["effort"], "low")
                if kind == "none":
                    session.drain(0.4)
                    self.assertEqual(session.events("displayed"), [])
                    session.expect_no_suggestion()
                else:
                    session.event("displayed")
                    session.wait(lambda: bool(session.widget()), "real production widget")
                    if kind == "choice":
                        session.expect_cards(scene)
                session.expect_draft("")
                # Stop each independent first-turn session before starting another.
                self.doCleanups()

    def test_single_ghost_tab_right_accept_and_enter_sends_once(self):
        session = NativeSession(self, delayed_input=True)
        draft = preview.FIXTURES["ready"]["suggestion"]["actions"][0]["draft"]
        for key in ("\t", "\x1b[C"):
            session.ready()
            session.wait(lambda: draft in session.rows(), "visible ghost inside native editor")
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

    def test_typing_dismisses_single_ghost_without_revival(self):
        session = NativeSession(self)
        draft = preview.FIXTURES["ready"]["suggestion"]["actions"][0]["draft"]
        session.ready()
        session.send("验证")
        session.expect_draft("验证")
        self.assertNotIn(draft, session.rows())
        session.expect_no_suggestion()
        session.clear()
        session.drain(0.2)
        session.expect_no_suggestion()
        session.send("\t")
        session.expect_draft("")
        session.send("/next-step pick\r")
        session.expect_draft("")
        session.drain(0.3)
        self.assertTrue(session.state().get("editorFocused"))
        self.assertFalse(session.state().get("overlay"))
        session.expect_no_suggestion()
        self.assertEqual(len(session.requests()), 1)
        self.assertEqual(session.events("accepted"), [])

    def test_default_first_choice_enter_sends_once_without_default_checks(self):
        for scene in ("decision", "maintenance"):
            with self.subTest(scene=scene):
                session = NativeSession(self, delayed_input=True)
                session.ready(scene)
                draft = preview.FIXTURES[scene]["suggestion"]["actions"][0]["draft"]
                session.expect_draft("")
                session.send("\r")
                accepted = session.event("accepted")
                self.assertEqual(accepted["indices"], [0])
                session.event("submitted", predicate=lambda event: event["outcome"] == "accepted" and event["text"] == draft)
                session.wait(lambda: len(session.requests()) == 2, "default first choice native submit")
                session.event("generated", after=1)
                self.assertEqual(len(session.requests()), 2, "Enter submits exactly once")
                self.assertEqual(len(session.requests(suggestion=True)), 2, "Acceptance needs no extra model call")
                self.assert_submission_payload(session, scene, draft)
                self.doCleanups()

    def test_choice_arrows_wrap_both_directions_and_focus_does_not_check(self):
        for scene in ("decision", "maintenance"):
            with self.subTest(scene=scene):
                session = NativeSession(self, delayed_input=True)
                actions = preview.FIXTURES[scene]["suggestion"]["actions"]
                session.ready(scene)
                for key, focused in (("\x1b[A", 2), ("\x1b[B", 0), ("\x1b[B", 1),
                                     ("\x1b[B", 2), ("\x1b[B", 0), ("\x1b[A", 2)):
                    session.send(key)
                    session.expect_cards(scene, focused=focused)
                    session.expect_draft("")
                self.assertEqual(session.events("accepted"), [], "Focus alone must not adopt or check")
                self.assertEqual(len(session.requests()), 1)
                session.send("\r")
                session.event("submitted", predicate=lambda event: event["outcome"] == "accepted" and event["text"] == actions[2]["draft"])
                session.wait(lambda: len(session.requests()) == 2, "focused choice native submit")
                session.event("generated", after=1)
                self.assert_submission_payload(session, scene, actions[2]["draft"])
                for key in ("\t", "\x1b[C"):
                    session.ready(scene)
                    count = len(session.requests())
                    suggestions = len(session.requests(suggestion=True))
                    session.send("\x1b[B")
                    session.expect_cards(scene, focused=1)
                    session.send(key)
                    session.expect_draft(actions[1]["draft"])
                    self.assertEqual(len(session.requests()), count, "Tab/Right only fills the focused choice")
                    self.assertEqual(len(session.requests(suggestion=True)), suggestions)
                    session.clear()
                self.doCleanups()

    def test_multiple_space_toggle_and_combined_enter_tab_right_use_option_order(self):
        actions = preview.FIXTURES["maintenance"]["suggestion"]["actions"]
        combined = "\n\n".join(actions[index]["draft"] for index in (0, 2))
        for key in ("\r", "\t", "\x1b[C"):
            with self.subTest(key=key):
                session = NativeSession(self, delayed_input=True)
                session.ready("maintenance")
                session.send(" ")
                session.expect_cards("maintenance", checked=(0,))
                session.expect_draft("")
                session.send(" ")
                session.expect_cards("maintenance")
                # Check the last option before the first, leaving focus on unchecked option 2.
                session.send("\x1b[A")
                session.send(" ")
                session.expect_cards("maintenance", focused=2, checked=(2,))
                session.send("\x1b[B")
                session.send(" ")
                session.send("\x1b[B")
                session.expect_cards("maintenance", focused=1, checked=(0, 2))
                session.expect_draft("")
                self.assertEqual(session.events("accepted"), [])
                self.assertEqual(len(session.requests()), 1)
                self.assertEqual(len(session.requests(suggestion=True)), 1)
                session.send(key)
                accepted = session.event("accepted")
                self.assertEqual(accepted["indices"], [0, 2])
                self.assertEqual(accepted["draft"], combined)
                if key == "\r":
                    session.event("submitted", predicate=lambda event: event["outcome"] == "accepted" and event["text"] == combined)
                    session.wait(lambda: len(session.requests()) == 2, "combined drafts native submit")
                    session.event("generated", after=1)
                    self.assertEqual(len(session.requests()), 2)
                    self.assertEqual(len(session.requests(suggestion=True)), 2)
                    self.assert_submission_payload(session, "maintenance", combined)
                else:
                    session.expect_draft(combined)
                    session.expect_no_suggestion()
                    self.assertEqual(len(session.requests()), 1, "Combined Tab/Right never submits")
                    self.assertEqual(len(session.requests(suggestion=True)), 1, "Combining drafts is local")
                self.doCleanups()

    def test_single_select_space_is_native_text_not_a_toggle(self):
        session = NativeSession(self)
        session.ready("decision")
        session.send(" ")
        session.expect_draft(" ")
        session.expect_cards("decision", focused=None)
        self.assertEqual(session.events("accepted"), [])
        self.assertNotIn("[x]", "\n".join(session.widget()))
        self.assertNotIn("[ ]", "\n".join(session.widget()))
        self.assertEqual(len(session.requests()), 1)

    def test_choice_cards_stay_read_only_and_typed_enter_sends_only_typed_text(self):
        session = NativeSession(self)
        session.ready("maintenance")
        session.send(" ")
        session.send("\x1b[A")
        session.send(" ")
        session.expect_cards("maintenance", focused=2, checked=(0, 2))
        text = "仅解释当前状态"
        session.send(text)
        session.expect_draft(text)
        session.expect_cards("maintenance", focused=None, checked=(0, 2))
        for action in preview.FIXTURES["maintenance"]["suggestion"]["actions"]:
            self.assertNotIn(action["draft"], session.rows())
        session.send(" ")
        session.send("\x1b[C")
        session.send("\x1b1")
        session.expect_draft(text + " ")
        session.expect_cards("maintenance", focused=None, checked=(0, 2))
        session.send("不要执行任务。")
        typed = text + " 不要执行任务。"
        session.expect_draft(typed)
        self.assertEqual(session.events("accepted"), [])
        session.send("\r")
        session.event("submitted", predicate=lambda event: event["outcome"] == "other" and event["text"] == typed)
        session.wait(lambda: len(session.requests()) == 2, "typed-only native submit")
        session.event("generated", after=1)
        self.assertEqual(len(session.requests()), 2)
        self.assert_submission_payload(session, "maintenance", typed)

    def test_alt_accept_does_not_send_and_submitted_outcomes(self):
        session = NativeSession(self)
        session.ready("decision")
        session.send("\x1b2")
        draft = preview.FIXTURES["decision"]["suggestion"]["actions"][1]["draft"]
        session.expect_draft(draft)
        accepted = session.event("accepted")
        self.assertEqual(accepted["indices"], [1])
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

    def test_esc_cancels_permanently_and_preserves_existing_draft(self):
        for draft in ("", "保留这段未发送草稿"):
            with self.subTest(draft=draft):
                session = NativeSession(self)
                session.ready("maintenance")
                session.send(" ")
                session.expect_cards("maintenance", checked=(0,))
                if draft:
                    session.send(draft)
                    session.expect_draft(draft)
                    session.expect_cards("maintenance", focused=None, checked=(0,))
                session.send("\x1b")
                session.expect_draft(draft)
                session.expect_no_suggestion()
                session.clear()
                session.drain(0.2)
                session.expect_no_suggestion()
                session.send("\x1b1")
                session.expect_draft("")
                session.send("/next-step pick\r")
                session.expect_draft("")
                session.drain(0.3)
                self.assertTrue(session.state().get("editorFocused"), "Cancelled result must not reopen a picker")
                self.assertFalse(session.state().get("overlay"))
                session.expect_no_suggestion()
                session.send("\r")
                session.drain(0.2)
                self.assertEqual(session.events("accepted"), [])
                self.assertEqual(len(session.events("displayed")), 1)
                self.assertEqual(len(session.requests()), 1)
                self.assertEqual(len(session.requests(suggestion=True)), 1)
                session.ready("decision")
                self.doCleanups()

    def test_native_completion_escape_dismisses_popup_before_cards(self):
        for text, label in (("@fixture-fi", "fixture-file.txt"), ("/next-ste", "next-step"),
                            ("$fixture-a", "skill:fixture-alpha")):
            with self.subTest(completion=text):
                session = NativeSession(self)
                session.ready("maintenance")
                session.send(" ")
                session.send(text)
                session.wait(lambda: popup_shows(session, label), "native completion popup")
                session.expect_cards("maintenance", focused=None, checked=(0,))
                dismissed = len(session.events("dismissed"))
                session.send("\x1b")
                session.wait(lambda: not session.state().get("active"), "first Escape dismisses completion")
                session.expect_draft(text)
                session.expect_cards("maintenance", focused=None, checked=(0,))
                self.assertEqual(len(session.events("dismissed")), dismissed)
                session.send("\x1b")
                session.expect_draft(text)
                session.expect_no_suggestion()
                session.clear()
                session.expect_no_suggestion()
                self.assertEqual(session.events("accepted"), [])
                self.assertEqual(len(session.requests()), 1)
                self.doCleanups()

    def test_native_selector_escape_dismisses_overlay_before_cards(self):
        for command in ("/preview\r", "\x1b/"):
            with self.subTest(command=command):
                session = NativeSession(self)
                session.ready("maintenance")
                session.send(" ")
                session.send(command)
                session.wait(lambda: session.state().get("overlay") or not session.state().get("editorFocused"),
                             "native selector")
                dismissed = len(session.events("dismissed"))
                session.send("\x1b")
                session.wait(lambda: not session.state().get("overlay") and session.state().get("editorFocused"),
                             "first Escape dismisses selector")
                session.expect_draft("")
                session.expect_cards("maintenance", checked=(0,))
                self.assertEqual(len(session.events("dismissed")), dismissed)
                session.send("\x1b")
                session.expect_no_suggestion()
                self.assertEqual(len(session.requests()), 1)
                self.doCleanups()

    def test_restart_and_resume_do_not_restore_old_cards(self):
        for resume in (False, True):
            with self.subTest(resume=resume):
                session = NativeSession(self)
                session.ready("maintenance")
                session.send(" ")
                session.expect_cards("maintenance", checked=(0,))
                previous_id = session.state()["sessionId"]
                session.restart(resume=resume)
                session.wait(lambda: session.state().get("editorFocused"), "restarted native editor focus")
                session.drain(0.4)
                if resume:
                    self.assertEqual(session.state()["sessionId"], previous_id, "Test resumes the original session")
                else:
                    self.assertNotEqual(session.state()["sessionId"], previous_id)
                session.expect_draft("")
                session.expect_no_suggestion()
                session.send("/next-step pick\r")
                session.expect_draft("")
                session.drain(0.3)
                self.assertTrue(session.state().get("editorFocused"))
                self.assertFalse(session.state().get("overlay"))
                session.expect_no_suggestion()
                self.assertEqual(len(session.requests()), 1, "Resume does not replay a main turn")
                self.assertEqual(len(session.requests(suggestion=True)), 1, "Resume does not regenerate old suggestions")
                self.assertEqual(len(session.events("displayed")), 1)
                self.assertEqual(session.events("accepted"), [])
                session.ready("decision")
                self.doCleanups()

    def test_slow_generation_survives_twenty_seconds_and_still_has_a_deadline(self):
        session = NativeSession(self, controlled_time=True)
        first_release = threading.Event()
        session.server.next_suggestion(delay=0, gate=first_release)
        session.scene("ready")
        session.wait(lambda: len(session.requests(suggestion=True)) == 1, "long-tail suggestion started")
        session.set_time(21_000)
        first_release.set()
        generated = session.event("generated")
        self.assertEqual(generated["latencyMs"], 21_000)
        session.event("displayed")
        session.send("\t")
        session.expect_draft(preview.FIXTURES["ready"]["suggestion"]["actions"][0]["draft"])
        session.clear()

        second_release = threading.Event()
        session.server.next_suggestion(delay=0, gate=second_release)
        session.scene("ready")
        session.wait(lambda: len(session.requests(suggestion=True)) == 2, "deadline suggestion started")
        requested = session.event("requested", after=1)
        session.set_time(21_000 + 59_999)
        self.assertEqual([event["type"] for event in session.events() if event["id"] == requested["id"]],
                         ["requested"], "The real provider request must remain pending before its deadline")
        session.expect_no_suggestion()

        session.set_time(21_000 + 60_000)
        failed = session.event("failed", predicate=lambda event: event["id"] == requested["id"])
        self.assertEqual(failed["reason"], "generation timeout")
        self.assertEqual(failed["latencyMs"], 60_000)
        session.expect_no_suggestion()
        self.assertEqual(len(session.events("generated")), 1)
        self.assertEqual(len(session.events("displayed")), 1)
        self.assertEqual(len(session.requests(suggestion=True)), 2, "Deadline failure must not retry")

        second_release.set()
        session.ready("decision")
        session.send("\t")
        session.expect_draft(preview.FIXTURES["decision"]["suggestion"]["actions"][0]["draft"])
        self.assertEqual(len(session.events("failed")), 1)
        self.assertEqual(len(session.requests(suggestion=True)), 3, "Recovery makes one new suggestion request")

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
        self.assertEqual(session.events("failed"), [], "Typing cancels inference without recording a failure")
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
                failure = session.event("failed", after=count)
                expected = "Injected preview suggestion failure" if mode == "failure" else "Invalid suggestion JSON"
                self.assertIn(expected, failure["error"])
                self.assertEqual(failure["stage"], "provider" if mode == "failure" else "parse")
                self.assertEqual(failure["stopReason"], "error" if mode == "failure" else "stop")
                self.assertEqual(failure["model"], preview.SUGGESTION_MODEL)
                notifications = len(session.state().get("notifications", []))
                session.send("/next-step status\r")
                status = session.wait(lambda: next((item["message"] for item in session.state().get("notifications", [])[notifications:]
                                                   if "最近失败" in item["message"]), None), "failure status")
                self.assertIn(expected, status)
                self.assertIn(failure["at"], status)
                self.assertIn(failure["model"], status)
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
        session.wait(lambda: session.state().get("overlay") or not session.state().get("editorFocused"),
                     "native next-step picker")
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
        session.wait(lambda: popup_shows(session, "fixture-file.txt"), "settled native file popup")
        session.send("\t")
        session.wait(lambda: "fixture-file.txt" in (session.editor() or ""), "native file Tab completion")
        session.clear()
        session.send("/next-ste")
        session.wait(lambda: popup_shows(session, "next-step"), "settled native slash popup")
        session.send("\t")
        session.wait(lambda: (session.editor() or "").startswith("/next-step"), "native slash Tab completion")
        session.clear()
        session.send("$fixture-a")
        session.wait(lambda: popup_shows(session, "skill:fixture-alpha"), "settled skill popup")
        session.send("\t")
        session.wait(lambda: session.state().get("expanded") == "/skill:fixture-alpha ", "expanded native skill draft")
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
                session.expect_cards("decision")
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
