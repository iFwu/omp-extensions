# Session secrets

Opt-in, session-local credential input for OMP 18.12.6 on macOS and Linux. The
model requests a masked dialog and receives a reference, not the credential value.
This is accidental-disclosure protection, not an OS sandbox or credential broker.

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

- `/sec add NAME`: masked input; values require at least eight characters and no
  NUL. Shorter values cannot be reliably scrubbed and are refused.
- `/sec`: management menu; `/sec list`, `rename`, `remove`, `off`, `on` are also
  available. `off` clears the session vault after confirmation.
- `/sec add-from-file`: explicitly selected dotenv import, names shown for selection.
- `/sec restore NAME`: user-requested copy to clipboard. This is not available to
  the model as a reveal tool; the clipboard is outside the no-value-return boundary.
- Tab completes `{{sec:NAME}}` references. OMP 18.12.6 does not support Pi's
  automatic reference-trigger popup.

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
commands. Other tool calls requiring secret substitution are refused before
execution, rather than writing a reference string or persisting expanded arguments.

Credential output is buffered in memory and redacted before OMP receives it.
There is no raw-output temp artifact. Output exceeding 8 MiB stops the process and
withholds all output, avoiding a leaked prefix at a truncation boundary. Timeout
and cancellation terminate the process group. Shell quoting guards reject contexts
where a reference cannot be safely expanded, including unsafe nested-shell use.

The vault is memory-only. `/new`, resume/fork/branch transitions and shutdown clear
the previous vault; reload/restart is not credential persistence. Re-enter values
when references are unavailable. Session files retain references only for the
verified secure-input/credential-command path.

## Backstops and limits

The port retains upstream accidental-paste capture, known-value/shape scrubbing,
file-output masking and provider-context hooks as defense in depth. Shape-only
paste guesses ask for confirmation; they are not a substitute for masked input.
`--sec-file-reads=false` and `--sec-confirm-guess=false` retain upstream explicit
controls. A diagnostic failure does not bypass the scrubber's redacted fallback.

- Arbitrary same-user code can read process environments, transform credentials,
  write files or transmit them. This feature does not stop a malicious model.
- Provider payload hooks are transport-dependent. OMP does not make every
  transform-hook timeout/error universally fail-closed.
- Native tools and other extensions can persist their own raw artifacts before
  result hooks. Global scrubbing is not a guarantee for arbitrary existing files,
  logs, screenshots, memory plugins or external tools.
- Images and binary payloads are not pixel-redacted. Never capture a screenshot
  showing a revealed value.
- Explicit credential-file writes and the receiving service can retain values;
  output masking does not undo those effects or securely erase process memory.
- Clipboard and every management-menu path are not covered by the end-to-end
  acceptance test. No real account credentials are used in tests.

## Verification

From the repository root, with the documented Python environment and `OMP_BIN`
pointing to the standalone binary:

```sh
bun run typecheck
bun test packages/secret/tests
python3 -m unittest discover -s packages/secret/tests -v
bun run smoke:package
```

The real PTY/provider fixture covers schema discovery, model-triggered masked
input, reuse/listing, manual short/cancel, exact delivery of punctuation-bearing
fake credentials to a loopback endpoint, echoed-output redaction, native shell
persistence, foreground-only guards, unknown references, timeout, session clearing,
and provider/terminal/runtime-file canary sweeps. Bun regressions cover input,
request lifecycle, shell expansion, vault isolation, redaction and child-process
cancellation/concurrency. Package smoke verifies default-off installation and
persisted opt-in observed by a new OMP process.

## Attribution

Adapted from [kslamph/pi-secret](https://github.com/kslamph/pi-secret), version 0.5.0,
commit `dbafa882a72c168198a2417ea6c6215b85c26fe1`. The upstream MIT license is retained
in `LICENSE`. The OMP execution bridge, native plugin activation, discoverable
request/list tool and runtime tests are maintained here; no Pi compatibility shim
or second credential store is introduced.
