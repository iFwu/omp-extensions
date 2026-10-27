# Next-step

Optional post-answer drafts for OMP 18.12.6. One independent model request after a completed main-agent turn returns `none`, one ghost-text recommendation in the empty composer, or 2–3 action cards above it. No JEV prefilter, periodic polling, tool execution, or extra main-session message from generation. An unresolved Ask remains the main agent's responsibility.

The feature is **off by default**. Installing the suite alone does not start model calls. Use `/next-step on` for the current process or persist plugin settings. The default selector is `@smol`, with `low` effort; configure a dedicated role to avoid coupling this feature to other background tasks. Role resolution selects the base model; effort is passed separately by this extension.

Persist settings through the native manifest schema of whichever package is installed. With the suite:

```sh
omp plugin config set @ifwu/omp-extensions next-step true
omp plugin config set @ifwu/omp-extensions next-step-model @next-step
omp plugin config set @ifwu/omp-extensions next-step-effort low
omp plugin config set @ifwu/omp-extensions next-step-collect true
```

The suite's keys mirror the startup flags: `next-step`, `next-step-model`, `next-step-effort`, `next-step-collect`, and `next-step-data-dir`. The standalone package uses `@ifwu/omp-next-step` with `enabled`, `model`, `effort`, `collect`, and `dataDir`; when both names have a value, the standalone one wins. Native `plugin config` commands need the named package installed, and uninstalling a package removes its settings, so set them again after switching between suite and standalone. Global settings merge with native project plugin overrides. CLI flags override settings: `--next-step`, `--next-step-model`, `--next-step-effort`, `--next-step-data-dir`. Configuration is read when the extension starts; start a new OMP process after changing persistent settings. Commands change only the current process:

- `/next-step on|off|status`
- `/next-step model <provider/model|@role|current>`
- `/next-step effort minimal|low|medium|high|xhigh`
- `/next-step data on|off`
- `/next-step pick`

With a single recommendation and an empty composer, Next-step takes priority in the native ghost-text slot. Tab or Right adopts the complete draft without sending; **Enter adopts and submits it once through the native input path**. Typing removes the ghost immediately, even when the typed text matches its prefix; deleting back to empty does not revive it.

Choice cards start with **focus on the first action and no checked actions**. In an empty, focused composer without a popup, Up/Down wraps focus. Choices declare `selectionMode: single` for alternatives or uncertain compatibility, and `multiple` for combinable tasks. Only multiple-mode cards use Space to toggle a check. Enter submits the checked actions, or the focused action when no checks exist; Tab/Right only fills the same draft. Combined drafts retain option order and are joined with a blank line, without another model call or implied parallel execution.

Typing removes the ghost preview but leaves the full choice cards and checks visible as read-only reference. With any text present, arrows, Space, Tab and Enter belong to the native editor; Enter sends **only that text**, not the checked actions. To add constraints to a selection, use Tab to fill its full draft first, then edit and send. No suggestion metadata or numbered-option context is injected into the main conversation; manually typed `1` or `1+2` is not expanded.

Escape cancels the current suggestion and checks without deleting editor text. Native completion popups and selectors handle Escape first; after they close, another Escape cancels the cards. Cancellation is permanent for that result: delete-to-empty and `/next-step pick` cannot revive it, and restarting or resuming does not restore old cards. It does not disable generation for later turns. `Alt+1/2/3` fills one draft without sending; `Alt+/` or `/next-step pick` opens a native full-text selector that also only fills. Neither can overwrite a nonempty draft.

Cards show the question once, then each title and a brief tradeoff. Tradeoffs align beside titles when they fit and wrap below otherwise. The focus marker is distinct from multiple-mode checkboxes; the footer identifies the Enter target or explains that typed text will be sent unchanged.

## Generation and lifecycle

Generation runs only in the main interactive TUI, after a normal completed answer with no continuation, queued messages, pending plan review, occupied editor, or competing UI focus. The handler schedules background work rather than waiting for inference before returning. It is at most once per run, bounded to 60 seconds and 2,048 requested output tokens. No extension-level retry is added; the native transport may retry independently. Input still cancels pending generation immediately, and cancellation does not guarantee the provider has incurred no cost.

The model sees up to two recent real user requests and related completed assistant answers, text only, bounded to 16,000 UTF-16 code units with explicit truncation markers. The latest goal and final answer receive priority. Thinking, tool logs, synthetic users, and custom messages are excluded. This context is sent to the chosen provider; it is not a secret store. The complete generation prompt and its version live in `src/suggestion.ts`.

Only useful optional follow-ups in the latest answer are candidates; earlier turns supply restrictions rather than extra tasks. Completed work, repeated verification, a pause, missing user test results, or unfinished already-requested work should produce `none`. Independent tasks may be combined; ordered steps of one task stay together. Drafts are short requests from the user to the assistant, not instructions for the human, invented user results/preferences, extra planning gates, or detailed implementation briefs. Explicit restrictions and safety prerequisites must survive shortening. These are generation instructions, not semantic phrase filters; the parser enforces structural limits and strict `selectionMode` fields, not factual correctness or the prompt's soft length targets.

Input invalidates pending inference, so late responses cannot overwrite drafts or reappear after delete-to-empty. Already-visible choices survive editing until submission, explicit cancellation, or a session/turn boundary. New turns, switching/branching sessions, compaction, disabling the feature, or changing its model clear current results. Provider errors, timeouts, and invalid JSON leave the main conversation usable and permit a later successful turn. Unexpected UI errors disable the enhancement for the rest of the process.

`/next-step status` includes the current session's most recent failure in this process: timestamp, resolved model/effort, provider or parse stage, provider stop reason when available, and a bounded error summary. It remains available after later successful turns and with collection disabled; it is not restored on restart. The warning stays brief and rate-limited. Summaries retain actionable provider errors while removing URLs, common credential forms, quoted details, embedded structured bodies, subsequent lines, and terminal controls; JSON syntax errors never include response excerpts. Error objects, headers, and response content are not serialized into diagnostics. Treat summaries as private data, since arbitrary provider prose is not guaranteed secret-free. User cancellation is not a failure, and no new retries are added.

## Private local feedback

Collection is enabled when the feature is enabled unless `collect: false` or `/next-step data off` is set. Nothing is uploaded by collection. Files contain user/assistant text and should be treated as private conversation data, not committed or automatically submitted for evaluation.

The default location is `<session-directory>/next-step/<session-id>.jsonl`, alongside but **outside** the native session JSONL. `dataDir` or `--next-step-data-dir` overrides the directory. Ephemeral sessions without a session file do not collect unless a directory is explicitly configured. New directories use mode 0700; new files use 0600, with append-only writes and final-path symlink refusal. Existing filesystem ACLs remain authoritative. A write failure disables collection and reports it once without disabling suggestions.

Each event has `schema`, `id`, `at`, and `type`; `id` correlates one generation attempt with its eventual outcome. New records use schema 2: choices require `selectionMode`, and acceptance records contain an `indices` array (zero-based, in option order). Historical schema-1 records are not rewritten or replayed.

| Event | Meaning |
| --- | --- |
| `requested` | Frozen text context, resolved model, effort, and prompt version. |
| `generated` | Same evaluation metadata, parsed result (including `none`), and end-to-end generation latency. |
| `displayed` | The result was actually placed in the visible UI, not merely generated. |
| `accepted` | The actions named by `indices` were copied to the draft; **not** a final acceptance label. |
| `submitted` | The next interactive non-command input: unchanged accepted draft (`accepted`), changed accepted draft (`edited`), or independently entered text (`other`). Clearing an accepted draft resets that attribution. Submitted text is capped at 16,000 code units and marked when truncated. |
| `ended` | Session/turn/feature boundary before a classified submission, with displayed/accepted flags. Normal shutdown is neutral, not rejection. |
| `cancelled`, `dismissed`, `skipped` | Distinguish interrupted inference, user dismissal, and undisplayed results. |
| `failed` | Failure category (`reason`), resolved `model` and `effort`, `stage` (`provider` or `parse`), optional `stopReason`, sanitized `error` summary, and `latencyMs`. Older records may contain only `reason`. |

A crash/forced kill can leave an open sample without `submitted` or `ended`; treat it as unknown, not a negative. Model outputs of `none` and candidates never shown remain in the dataset so future evaluation can distinguish missed opportunities from rejected suggestions. Slash commands are not classified as independent user feedback. This is observational data, not an automatic quality score or automatic upload pipeline.

## Preview and verification

```sh
python3 ~/omp-extensions/scripts/preview-next-action.py
```

The offline default runs this actual extension against two separate loopback models in a temporary HOME, with fixture replies and strict JSON suggestions. `/preview` changes scenarios or injects delay/failure. It makes no paid model calls. `--live --model @next-step --effort low` explicitly starts a real source-loaded session using existing credentials and configured main model, incurring normal model costs; it installs nothing. Use ordinary `omp` after native plugin installation instead of the source preview for daily use.

Run `bun test packages/next-step/tests/suggestion.test.ts` and `python3 -m unittest discover -s packages/next-step/tests -v` from the checkout. Python TUI checks require the native standalone OMP binary (`OMP_BIN` may select it), not an app session wrapper.
