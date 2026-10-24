"""Exercise pending-message visibility and native queue editing through the installed OMP TUI."""

import codecs
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

try:
    import pyte
except ImportError:
    pyte = None


@unittest.skipUnless(os.name == "posix" and OMP_BIN and pyte, "POSIX OMP TUI and pyte required")
class PendingMessageTests(unittest.TestCase):
    def test_pending_indicator_follows_native_queue_without_resending_input(self):
        for appearance in ("light", "dark"):
            gates = [threading.Event() for _ in range(6)]
            requests = []
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args): pass
                def do_POST(self):
                    index = len(requests)
                    requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.end_headers()
                    def event(kind, **data):
                        self.wfile.write((f'event: {kind}\ndata: ' + json.dumps({'type': kind, **data}) + '\n\n').encode())
                        self.wfile.flush()
                    response = {'id': f'resp_{index}', 'object': 'response', 'status': 'in_progress', 'output': []}
                    try:
                        event('response.created', response=response)
                        gates[min(index, len(gates) - 1)].wait(30)
                        message = {'id': f'msg_{index}', 'type': 'message', 'role': 'assistant', 'status': 'completed',
                                   'content': [{'type': 'output_text', 'text': f'REPLY_{index}', 'annotations': []}]}
                        event('response.output_item.added', output_index=0, item=message | {'content': []})
                        event('response.output_text.delta', item_id=message['id'], output_index=0, delta=f'REPLY_{index}')
                        event('response.output_item.done', output_index=0, item=message)
                        event('response.completed', response=response | {'status': 'completed', 'output': [message],
                              'usage': {'input_tokens': 100, 'output_tokens': 10, 'total_tokens': 110}})
                    except (BrokenPipeError, ConnectionResetError): pass
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            with tempfile.TemporaryDirectory(prefix='omp-pending-') as directory:
                root = Path(directory)
                second_steering = 'Queued second ' + 'detail ' * 30
                dequeue_key = b'\x1bj' if appearance == 'light' else b'\x1b[1;3A'
                write_yaml(root / 'keybindings.yml', {
                    'app.tools.toggleVisibility': 'Ctrl+O',
                    'app.message.dequeue': 'Alt+J' if appearance == 'light' else 'Alt+Up',
                })
                preparing = root / 'preparing'
                release_preparation = root / 'release-preparation'
                preparation_gate = root / 'preparation-gate.ts'
                preparation_gate.write_text('''
import { existsSync, writeFileSync } from "node:fs";
export default function(pi) {
  pi.on("context", async ({ messages }, ctx) => {
    if (!messages.some(message => message.role === "user" &&
        JSON.stringify(message.content).includes("Queued "))) return;
    writeFileSync(new URL("./preparing", import.meta.url), "");
    await new Promise(resolve => {
      const timer = ctx.setInterval(() => {
        if (!existsSync(new URL("./release-preparation", import.meta.url))) return;
        ctx.clearTimer(timer);
        resolve();
      }, 20);
    });
  });
}
''')
                write_yaml(root / 'models.yml', {'providers': {'ui-test': {
                    'baseUrl': f'http://127.0.0.1:{server.server_port}/v1', 'api': 'openai-responses',
                    'auth': 'apiKey', 'apiKey': 'test-only-key', 'models': [{'id': 'ui-model', 'name': 'UI Model',
                    'reasoning': False, 'input': ['text'], 'contextWindow': 100000, 'maxTokens': 1024}]}}})
                write_yaml(root / 'config.yml', {
                    'composer': {'shape': 'dotfiles/claude-context'}, 'symbolPreset': 'unicode',
                    'theme': {'dark': appearance, 'light': appearance},
                    'startup': {'setupWizard': False, 'checkUpdate': False, 'quiet': True},
                    'retry': {'enabled': False, 'modelFallback': False}, 'providers': {'cacheWarming': 'off'},
                    'compaction': {'enabled': False}, 'display': {'hideToolActivity': True},
                })
                overlay = root / 'shared.yml'
                write_yaml(overlay, {'display': {'hideToolActivity': True}})
                master, slave = pty.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 32, 100, 0, 0))
                env = isolated_env(directory)
                env.update(PI_CODING_AGENT_DIR=directory, TERM='xterm-256color', COLORTERM='truecolor', NOTIFY_DRY_RUN='1',
                           COLORFGBG='0;15' if appearance == 'light' else '15;0')
                env['PI_CONFIG_FILES'] = str(overlay)
                process = subprocess.Popen([OMP_BIN, '--cwd', directory, '--model', 'ui-test/ui-model',
                    '--no-tools', '--no-extensions', '-e', str(SRC / 'claude-context.ts'), '--no-skills',
                    '-e', str(preparation_gate),
                    '--no-rules', '--no-lsp', '--no-title', '--no-session', '--thinking', 'off'],
                    env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
                os.close(slave)
                screen = pyte.Screen(100, 32)
                stream = pyte.Stream(screen)
                decoder = codecs.getincrementaldecoder('utf-8')('replace')
                raw = ''
                def view(): return '\n'.join(screen.display)
                def until(predicate, label, timeout=15):
                    nonlocal raw
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        if select.select([master], [], [], 0.05)[0]:
                            try: chunk = os.read(master, 65536)
                            except OSError: break
                            if not chunk: break
                            text = decoder.decode(chunk)
                            raw += text
                            stream.feed(text)
                        if predicate(): return
                    raise AssertionError(f'{appearance}: {label}\n{view()}\nRAW: {raw[-3000:]!r}')
                def banner(): return '▌ STEERING' in view() or '▌ FOLLOW-UP' in view()
                try:
                    until(lambda: 'UI Model' in view(), 'startup')
                    assert not banner(), view()
                    os.write(master, b'Initial request.\r')
                    until(lambda: len(requests) == 1, 'initial provider request')
                    os.write(master, b'Queued steering.\r')
                    until(banner, 'pending banner')
                    assert 'Steering' not in view() and view().count('Queued steering.') == 1, view()
                    row = next(i for i, line in enumerate(screen.display) if '▌ STEERING' in line)
                    cell = next(cell for cell in screen.buffer[row].values() if cell.data == 'S')
                    assert cell.bold and cell.fg != 'default' and cell.bg == 'default', cell
                    for mode in ('visible', 'hidden'):
                        before_toggle = len(raw)
                        os.write(master, b'\x0f')
                        until(lambda: len(raw) > before_toggle and banner(), f'custom queue with tools {mode}')
                        assert 'Steering' not in view() and view().count('Queued steering.') == 1, view()
                        row = next(i for i, line in enumerate(screen.display) if '▌ STEERING' in line)
                        cell = next(cell for cell in screen.buffer[row].values() if cell.data == 'S')
                        assert cell.bold and cell.fg != 'default' and cell.bg == 'default', cell
                    os.write(master, dequeue_key)
                    until(lambda: not banner() and 'Queued steering.' in view(), 'dequeue removes banner')
                    assert len(requests) == 1, requests
                    os.write(master, b'\r')
                    until(banner, 'resubmit restores banner')
                    os.write(master, (second_steering + '\r').encode())
                    os.write(master, b'Queued after yield.\x11')
                    until(lambda: banner() and '▌ FOLLOW-UP' in view() and 'second detail' in view(),
                          'multiple steering and follow-up messages')
                    assert view().count('Queued steering.') == 1, view()
                    assert view().count('Queued after yield.') == 1, view()
                    steering_row = next(row for row in screen.display if '▌ STEERING' in row)
                    assert '2' in steering_row, steering_row
                    before_toggle = len(raw)
                    os.write(master, b'\x0f')
                    until(lambda: len(raw) > before_toggle and '▌ STEERING' in view() and '▌ FOLLOW-UP' in view(),
                          'mixed custom queue with tools visible')
                    assert 'Steering' not in view() and 'After yield' not in view(), view()
                    assert view().count('Queued steering.') == view().count('Queued after yield.') == 1, view()
                    before_resize = len(raw)
                    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', 32, 40, 0, 0))
                    screen.resize(lines=32, columns=40)
                    until(lambda: len(raw) > before_resize and banner(), 'narrow banner')
                    gates[0].set()
                    until(preparing.exists, 'queued message preparing')
                    held_at = time.monotonic()
                    until(lambda: time.monotonic() - held_at >= 0.6, 'held preparation')
                    assert banner() and 'Queued steering.' in view(), view()
                    release_preparation.touch()
                    until(lambda: len(requests) == 2 and '▌ STEERING' in view(), 'first steering delivered')
                    assert 'second detail' in view() and '▌ FOLLOW-UP' in view(), view()
                    gates[1].set()
                    until(lambda: len(requests) == 3 and '▌ STEERING' not in view() and '▌ FOLLOW-UP' in view(),
                          'second steering delivered with follow-up visible')
                    gates[2].set()
                    until(lambda: len(requests) == 4 and not banner(), 'follow-up delivered')
                    user_texts = [part['text'] for item in requests[3]['input'] if item.get('role') == 'user'
                                  for part in item['content'] if part.get('type') == 'input_text']
                    for submitted in ('Queued steering.', second_steering.rstrip(), 'Queued after yield.'):
                        assert sum(text.count(submitted) for text in user_texts) == 1, user_texts
                    assert all('▌ STEERING' not in text and '▌ FOLLOW-UP' not in text for text in user_texts), user_texts
                    gates[3].set()
                    until(lambda: 'Worked for' in view(), 'turn completion')
                    os.write(master, b'/new\r')
                    until(lambda: 'Worked for' not in view() and 'REPLY_1' not in view(), 'new session')
                    assert not banner(), view()
                    preparing.unlink()
                    release_preparation.unlink()
                    os.write(master, b'New session request.\r')
                    until(lambda: len(requests) == 5, 'new session provider request')
                    os.write(master, b'Queued follow-up.\x11')
                    until(lambda: '▌ FOLLOW-UP' in view() and 'After yield' not in view(), 'new session follow-up')
                    gates[4].set()
                    until(preparing.exists, 'follow-up preparing')
                    held_at = time.monotonic()
                    until(lambda: time.monotonic() - held_at >= 0.6, 'held follow-up preparation')
                    assert '▌ FOLLOW-UP' in view() and 'Queued follow-up.' in view(), view()
                    release_preparation.touch()
                    until(lambda: len(requests) == 6 and not banner(), 'follow-up delivery')
                    gates[5].set()
                    until(lambda: 'Worked for' in view(), 'new session completion')
                    print(f'{appearance}: PASS idle, enqueue, edit/dequeue, resubmit, resize, delivery, no duplicate/model-context pollution, new session')
                finally:
                    release_preparation.touch()
                    for gate in gates: gate.set()
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=5)
                    os.close(master)


if __name__ == "__main__":
    unittest.main()
