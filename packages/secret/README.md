# Session secrets

Opt-in, session-local credential input for OMP 18.12.6 on macOS and Linux. Only
explicit `/sec add NAME` or a model `secret` request opens masked input and stores
a credential. The model receives a reference, not the entered value. This is
accidental-disclosure protection, not an OS sandbox or credential broker.

## Enable

The suite and standalone package default to **off**. Install one, not both:

```sh
# Suite
omp plugin config set @ifwu/omp-extensions secret true

# Or standalone
omp plugin config set @ifwu/omp-secret enabled true
```

Start a new OMP process after enabling. Existing sessions are not restarted or
hot-patched. Explicit `--secret` is available for source-based verification.
CLI selection takes precedence over standalone `enabled`, then suite `secret`.
A missing native Bash tool, another Bash override, or a subagent session prevents
activation; the extension does not restore tools deliberately excluded by the host.

## On-demand interface

The extension code stays loaded locally. Its full tool schema does not appear in
the default provider tool list: `secret` uses `loadMode: "discoverable"`. A short
system-prompt hint points to `xd://secret`; the model reads that URI when needed,
then invokes it by writing JSON to the same URI:

```json
{"action":"request","name":"deploy_token","reason":"Authenticate the requested deployment"}
```

The terminal shows the name, purpose and a masked input. A successful result is:

```json
{"status":"stored","ref":"{{sec:deploy_token}}"}
```

`{"action":"list"}` returns references only, without previews, fingerprints,
lengths or values. An existing name returns `available` without another dialog or
an overwrite. Cancellation, headless use, invalid input and a busy dialog return
explicit statuses. Pending input is discarded when the session changes, the call
is aborted or the feature is disabled. Subagents cannot access the main vault.

This uses OMP's existing `read`/`write` tool devices, not disk files, a standalone
CLI, or an IPC service. The separate `agent-credentials` 1Password workflow is not
modified. Once read, schema text remains ordinary conversation history until
normal context management removes it. Explicit `--tools secret` forces top-level
schema exposure and should not be used to enable normal operation.

## Manual input and management

- `/sec add NAME`: masked input; values require at least eight characters, no NUL,
  and at most 1 MiB.
- `/sec` or `/sec list`: list names/references and show management help.
- `/sec rename OLD NEW`, `/sec remove NAME`, `/sec clear`: manage memory-only entries.
- `/sec off` clears the session vault and disables credential entry/consumption;
  `/sec on` enables it again within the loaded extension.
- Tab completes `{{sec:NAME}}` references. No automatic reference-trigger popup.

No persistent status badge is displayed, including when credentials are present or
the feature is disabled. Use `/sec list` to inspect the current session on demand.

There is no file import, clipboard restore, plaintext-chat capture, or automatic
credential detection. Ordinary passwords and token-looking strings entered into
chat remain ordinary text, not protected secrets.

Input is an inline TUI component, not a separate macOS window. The model-facing
request never falls back to asking for a plaintext chat message.

## Command execution

Use a reference only in a foreground Bash command:

```sh
curl -H "Authorization: Bearer {{sec:deploy_token}}" https://authorized.example/api
```

The model-visible argument retains the reference. Execution replaces it with a
per-child environment variable inside an isolated `/bin/bash`, without placing the
value into OMP's persistent shell or rewriting the persisted `tool_call` input.
The child inherits OMP's filtered shell environment plus the requested credentials;
parent environment values are not mutated.

Commands without references still delegate to native Bash. Credential commands
use a new non-interactive shell: provide explicit `cwd`, combine dependent steps,
and do not rely on variables/functions left in the native persistent shell.
PTY, async jobs, named services and readiness gates are refused for credential
commands. Other tools remain native: a reference in a file write is just literal
text, not a substitution request, and file reads receive no secret filtering.

Credential-command output is buffered in memory. Only exact, explicitly entered
credential values are replaced with a redaction marker before OMP receives that output.
Unrelated token-looking strings and encoded/transformed values are unchanged:
there is no shape matching, substring guessing, or encoded-value redaction.
There is no raw-output temp artifact. Output exceeding 8 MiB stops the process and
withholds all output, avoiding a leaked prefix at a truncation boundary. Timeout
and cancellation terminate the process group. Shell quoting guards reject contexts
where a reference cannot be safely expanded, including unsafe nested-shell use.

The vault is memory-only. `/new`, resume/fork/branch transitions and shutdown clear
the previous vault; reload/restart is not credential persistence. Re-enter values
when references are unavailable. Session files retain references only for the
verified secure-input/credential-command path.

## Boundaries and limits

There are no automatic capture/scanning hooks, history filters, transcript edits,
context rewrites, or provider-payload transforms. Ordinary chat, tool arguments,
native tool output, and stored conversation history are unchanged. Signed or
encrypted provider history stays opaque; even a later explicit credential entry
does not retroactively rewrite it. No extra flags enable the removed automatic
scanning, file import, clipboard restore, or encoded-redaction behavior.

- Enter credentials only through masked input. Pasting a credential into chat or
  ordinary tools can send it to the provider and persist it unchanged.
- Arbitrary same-user code can read process environments, transform credentials,
  write files or transmit them. This feature does not stop a malicious model.
- Base64, URL encoding, hex, partial values, and other transformations are not
  redacted. Exact-output replacement is not a data-loss-prevention system.
- Existing files, native tool artifacts, logs, screenshots, memory plugins and
  external tools are outside the explicit credential-command output boundary.
- Images and binary payloads are not pixel-redacted. Never capture a screenshot
  showing a revealed value.
- Explicit credential-file writes and the receiving service can retain values;
  output redaction does not undo those effects or securely erase process memory.
- Tests use synthetic credentials and local providers only, never real accounts.

## Verification

From the repository root, with the documented Python environment and `OMP_BIN`
pointing to the standalone binary:

```sh
bun run typecheck
bun test packages/secret/tests
python3 -m unittest discover -s packages/secret/tests -v
bun run smoke:package
```

The real PTY/provider fixture covers schema discovery, manual and model-triggered
masked input, reuse/listing, short-input rejection/cancellation, exact delivery of
punctuation-bearing fake credentials to a loopback endpoint, and exact-only echoed
output redaction. It also covers unchanged ordinary `confirm_password_ref`, CSS
selectors, `password=` and token-shaped text in provider requests and persisted
transcripts; native tools, literal non-Bash references, no automatic vault capture,
encoded output, foreground-only guards, unknown references, timeout and session
clearing. A separate local `openai-codex-responses` SSE regression checks opaque
reasoning/signature persistence and encrypted history replay after explicit entry.
Bun regressions cover input, request lifecycle, shell expansion, vault isolation,
exact redaction and child-process cancellation/concurrency. Package smoke verifies
default-off installation and persisted opt-in observed by a new OMP process.

## Attribution

Adapted from [kslamph/pi-secret](https://github.com/kslamph/pi-secret), version 0.5.0,
commit `dbafa882a72c168198a2417ea6c6215b85c26fe1`. The upstream MIT license is retained
in `LICENSE`. The OMP execution bridge, native plugin activation, discoverable
request/list tool and runtime tests are maintained here; no Pi compatibility shim
or second credential store is introduced.
