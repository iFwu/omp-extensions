# Behavior contracts

These contracts apply to the ordinary terminal TUI on OMP 18.13.3 or newer, not a separate native application surface. Display enhancements never change provider context, submitted text, tool execution, or the native message queue.

## Composer and queue

Select `composer.shape: dotfiles/claude-context` to use the shaded composer. Its single-line input has a blank row above and below, two columns of horizontal padding, and the native status line immediately below. It grows with multiline text and reduces padding on short terminals. Padding is visual only: it adds no whitespace to drafts or history. The session title occupies a separate right-aligned line above the input.

The native model, Git, cost, context, and stop controls remain authoritative. Context budgets and compaction thresholds are not recomputed by this package. Set `statusLine.contextLine: embedded` to retain native context details; configure status-line contents and transparency in your own OMP settings.

Queued messages use `STEERING` and `FOLLOW-UP` headings, retain native order and numbering, and appear exactly once whether tools are visible or hidden. Native queue delivery, cancellation, and take-back editing remain unchanged. Long messages keep native truncation and newline indicators. Queue rendering does not depend on selecting the shaded composer.

Working text keeps the native tool-intent message. After one minute it can append elapsed time; a new intent yields precedence for at least 30 seconds. Automatic continuations and background-result waits marked `willContinue` keep the same timing origin, including the wait, without showing a completion. At terminal turn end, a display-only `Worked for …` line shows total duration and local completion time. A new user task submitted while idle starts a fresh span; extension-originated continuation input does not. Switching sessions or shutting down cancels the timer. The package writes none of this text to conversation history or model context.

## Transcript grouping

Grouping is on by default. `Ctrl+S` or `/grouping` toggles it independently of tool/thinking visibility. If your keymap already assigns `Ctrl+S` to `app.session.observe`, unbind that action in your own keybindings to avoid a conflict. `Ctrl+Y` retains native Yank behavior.

Grouping inserts gap statistics and completed-final separators without changing assistant text, copying behavior, or provider context:

- A gap shorter than 10 seconds, with fewer than three tools and no failure, gets no marker. No gap marker precedes the first commentary segment.
- Other gaps show elapsed time, tool count, and failure count. Tools are deduplicated by call ID.
- Gaps of at least 120 seconds use emphasis. A tool-blocked interval of at least one second adds a separate tool-wait duration.
- A normal final answer with total turn time of at least 120 seconds gets a `Done` separator. Crossing the boundary while streaming updates the marker at normal completion.
- Errors, aborted or length-limited replies, and explicit commentary are not promoted to completed final answers. Responses phase metadata may identify a final answer earlier; without it, the final segment is confirmed only after the turn completes normally.

Tool-wait duration is the union of foreground tool execution intervals overlapping the gap. Parallel tools are not double-counted. A background job stops counting when it is handed off; a later explicit wait counts only its own blocked interval. Model inference, provider queues, and output generation are not tool wait.

Gap timing freezes when its next text begins. Final timing covers the complete turn, including streamed output. Narrow layouts drop optional statistics before failure and completion markers; below 12 columns they fall back to native display. Theme colors are reused without painting backgrounds.

Only blocks still in the live viewport can change. Already committed scrollback is not rewritten. Grouping state is process-local, creates no session entries, and resets on session/branch changes or restart. Old historical `dotfiles.grouping` entries are left untouched and ignored.

## Ask history

When tool activity is hidden, Ask questions, options, selected/custom answers, and feedback remain visible through native Ask result rendering. When tool activity is shown, the extra display yields to the native result, so answers appear once. Records persist across session resume under the historical `dotfiles.ask-history` type; that display record is excluded from model context, while the actual tool result remains native.

Old sessions without these records are not rewritten. Use the native tool-visibility toggle to inspect their original tool results.

## Skill completion

After a whitespace boundary, `$`, `¥`, or `￥` opens the native skill candidates. Lowercase skill names filter them; arrows select, Tab or Enter accepts, and Escape closes while retaining the original text. Accepting writes the native `/skill:<name>` form without submitting it. Surrounding text and parameters remain intact. Native discovery and the `skills.enableSkillCommands` setting remain authoritative.

Typing a digit after a currency symbol dismisses the list and keeps amounts such as `¥100` unchanged. Environment-variable forms, shell substitutions, escaped symbols, backtick code, and drafts beginning with `/`, `!`, or `%` do not trigger skill lookup. Markdown blockquotes are normal prose: a leading `>` does not suppress skill lookup in the quoted draft or subsequent paragraphs. Selecting a skill after a quote preserves the quote and surrounding newlines. Unselected tokens are not rewritten on submission. Native slash, file, and inline completion retain their behavior.

## Session model switching

`/model <selector>` and `/models <selector>` use native `/switch` semantics: only the current session changes. Bare `/model` and `/models` keep the native management UI. The package does not change model roles, providers, service tiers, or credentials.

## Optional next-step

Next-step is opt-in and runs only in the main TUI. One detached native model request follows a normal completed turn; generation never runs a tool, appends an assistant/user message, or sends a draft. No JEV gate is used. The result is no UI, one ghost-text recommendation, or 2–3 cards with explicit single/multiple selection. Generation uses bounded recent text, not tool logs or thinking; candidates come from the latest answer while earlier turns preserve constraints.

Only an empty, focused composer without a popup can adopt suggestions. Cards default focus to the first action without checking it; arrows wrap, and Space toggles checks only for combinable tasks. Enter submits checked actions in option order (otherwise the focused action), joined with blank lines; Tab/Right fills without sending. Typing removes ghost text but leaves choice cards visible as read-only reference; typed Enter sends only the input, never hidden checks or suggestion context. Escape preserves the draft and permanently cancels the result, after native popups/selectors have handled their own Escape. Cancellation cannot be undone by delete-to-empty or the picker, and restart/resume never restores old cards. Pending inference is cancelled on input. New turns, session/branch changes, compaction and disabling the feature clear results. Full keyboard and lifecycle details are maintained in [next-step](../packages/next-step/README.md).

Private local feedback is separate from native conversation history. It preserves `none`, display, draft adoption, actual submission (unchanged/edited/other), cancellations, failures, and neutral session endings. Mere draft adoption is not final acceptance; exiting is not rejection, and missing shutdown after a crash is unknown. Collection can be disabled independently; no automatic upload or JEV training occurs. See [next-step settings and dataset](../packages/next-step/README.md).

Generation failures permit later turns to try again. Dataset write failures disable collection without blocking input or suggestions. Unexpected UI failures follow the process-lifetime disablement below.

## Optional session secrets

Secret handling is disabled by default: the suite setting is `secret: false`, and the standalone package setting is `enabled: false`. Disabled loading registers no secret tool, `/sec` command, or prompt hint. Enable the installed package with native `omp plugin config set` and start a fresh process, or explicitly pass `--secret` for a source-based run. CLI selection takes precedence over standalone settings, then suite settings; do not load both entry points. No OMP CLI/IPC implementation or 1Password integration is changed.

When enabled with native Bash available, exactly one discoverable agent tool, `secret`, has the actions `request` and `list`. The model reads `xd://secret` for the schema and writes JSON to that URI when needed. The prompt contains only a short discovery hint, not the entire schema. `request` uses masked input and requires at least eight characters with no NUL; cancellation and timeout do not store a value. Tool schemas and results carry names and `{{sec:name}}` references, never raw credentials. `/sec` retains manual management. This feature does not provide credentials to other sessions or persist them for restart/resume: each session owns its in-memory values, and a newly opened session must request them again.

Credential input uses OMP's native `ui.input` with `secret: true` and the request's abort signal. Entry remains TUI-only. Reference names match `[A-Za-z_][A-Za-z0-9_-]{0,63}` and preserve case: `TOKEN` and `token` address separate entries. Manual management, tool requests, completion and Bash consumption use the same naming rules.

Only reference-bearing foreground Bash commands receive values through an isolated child environment. Raw credentials are not substituted into OMP's execution arguments or temporary output artifacts. Only exact occurrences of explicitly stored credentials are redacted from that command's captured output before return; no token-shape detection or encoded-value matching runs. Such commands cannot use PTY, background jobs, services, or native persistent shell state. Bash commands without references delegate unchanged to the native tool, including streaming. With Bash unavailable, secret execution is unavailable rather than bypassing the user's tool selection.

Ordinary input, other tool calls/results, history, transcript, and provider payloads are untouched. There is no automatic capture, conversation scan, historical replacement, file import, or file write-back. Codex encrypted content and thinking signatures remain opaque. Credentials enter the vault only through the masked input requested by `/sec add NAME` or the `secret` tool; typing a password into normal chat is not protected.

This is disclosure reduction, **not a sandbox or a production-security guarantee**. A child program receives the real credential and can disclose it, use it in its own subprocess arguments, or write it elsewhere. Other code in the process and sufficiently privileged local observers can inspect memory or child environments. Redaction is not proof against transformations, encodings, or malicious programs. Never submit raw credentials in conversation text or tool arguments, and do not treat the extension as a substitute for provider-side least privilege, credential rotation, or a credential manager. The port retains pi-secret's MIT attribution at commit `dbafa882a72c168198a2417ea6c6215b85c26fe1`; see [secret usage and limits](../packages/secret/README.md).

## Failure isolation and compatibility

Input, tool execution, conversation text, answers, and history take priority over optional styling. Each added deferred render, timer, listener, or microtask has its own error boundary. A failed enhancement rolls back what it owns, reports once, and stays disabled for the remainder of the process. Repainting, toggling, or switching sessions must not revive it. Restarting OMP is required to reload the code.

Cleanup is idempotent and must not overwrite a later extension's replacement. Native operations and their errors are not swallowed. A successful native render is retained on optional-decoration failure rather than invoked twice.

Some adapters depend on internal OMP component shapes. Their `shortcut:` comments identify version limits and replacement triggers. They patch component instances rather than the OMP binary or global prototypes. Host upgrades require real-runtime verification, including fault injection and a second successful conversation in the same process.
