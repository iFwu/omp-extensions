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

With a single recommendation and an empty composer, Next-step takes priority in the native ghost-text slot. Tab or Right adopts the complete draft without sending; **Enter adopts and submits it once through the native input path**. A multiline draft is shown as a single-line ghost preview but adopted unchanged. Typing clears the suggestion immediately, including when the typed text matches its prefix; native completion then takes over. Deleting back to empty does not revive it. Choice cards never implicitly select their first action on Enter.

Choice cards start with nothing selected, so Enter alone never picks one. With an empty composer, Up/Down selects a card and previews its draft as ghost text; selection wraps from the last card to the first and back. **Enter then submits that draft once**, while Tab or Right fills it into the composer without sending. While cards are visible, Up/Down select cards instead of recalling input history; Escape dismisses the cards and restores native history navigation. `Alt+1/2/3` still fills the corresponding draft without sending. `Alt+/` opens the native selector with full draft text; Enter there fills without submitting. If the terminal does not send Option/Alt as Meta, use `/next-step pick`. File/slash/skill completion keeps native Tab behavior when the user has entered text or a popup is open. An explicit `pick` can revisit the current result until the next turn or session change.

Cards show the decision question once, then each title with a one-clause tradeoff. Tradeoffs sit beside the titles in an aligned column when every one fits; narrow terminals wrap them below their titles instead of cutting them off. The selected card gets an accent marker and title; the footer switches from selection hints to Enter/Tab hints once something is selected.

## Generation and lifecycle

Generation runs only in the main interactive TUI, after a normal completed answer with no continuation, queued messages, pending plan review, occupied editor, or competing UI focus. The handler schedules background work rather than waiting for inference before returning. It is at most once per run, bounded to 20 seconds and 2,048 requested output tokens. The native transport may retry independently; cancellation does not guarantee the provider has incurred no cost.

The model sees up to two recent real user requests and related completed assistant answers, text only, bounded to 16,000 UTF-16 code units with explicit truncation markers. The latest goal and final answer receive priority. Thinking, tool logs, synthetic users, and custom messages are excluded. This context is sent to the chosen provider; it is not a secret store. The complete generation prompt and its version live in `src/suggestion.ts`.

Unclear next steps, too many branches, a completed factual answer, explicit pause, unfinished requested work, or a blocking question should produce `none`. Cards organize real alternatives already discussed; ordered work is not a choice set. Drafts read as what the person would type next: the intent plus constraints the user already stated, usually one short sentence. Methods, parameters, commands, and step lists stay with the main agent unless the user already chose them. Every draft asks the assistant to act, decide, explain, check, or continue; announcements of the user's own offline actions (“我去测一下，回头告诉你”) are not drafts, and when that is the obvious next move the result is `none`. Drafts may use natural first-person completed-operation language such as “我试过了，还是不行，继续排查。”, because it asks the assistant to continue. The prompt also sets soft length targets for questions, titles, and tradeoffs so cards stay scannable; the parser's hard limits are unchanged.

Input, a new turn, switching/branching sessions, compaction, disabling the feature, or changing its model invalidates pending results. Late responses cannot overwrite drafts or reappear after delete-to-empty. A result is displayed only while the composer owns focus and has no popup/overlay competing with it. Provider errors, timeouts, and invalid JSON leave the main conversation usable and permit a later successful turn. Unexpected UI errors disable the enhancement for the rest of the process.

## Private local feedback

Collection is enabled when the feature is enabled unless `collect: false` or `/next-step data off` is set. Nothing is uploaded by collection. Files contain user/assistant text and should be treated as private conversation data, not committed or automatically submitted for evaluation.

The default location is `<session-directory>/next-step/<session-id>.jsonl`, alongside but **outside** the native session JSONL. `dataDir` or `--next-step-data-dir` overrides the directory. Ephemeral sessions without a session file do not collect unless a directory is explicitly configured. New directories use mode 0700; new files use 0600, with append-only writes and final-path symlink refusal. Existing filesystem ACLs remain authoritative. A write failure disables collection and reports it once without disabling suggestions.

Each event has `schema`, `id`, `at`, and `type`; `id` correlates one generation attempt with its eventual outcome:

| Event | Meaning |
| --- | --- |
| `requested` | Frozen text context, resolved model, effort, and prompt version. |
| `generated` | Same evaluation metadata, parsed result (including `none`), and end-to-end generation latency. |
| `displayed` | The result was actually placed in the visible UI, not merely generated. |
| `accepted` | An action was copied to the draft; **not** a final acceptance label. |
| `submitted` | The next interactive non-command input: unchanged accepted draft (`accepted`), changed accepted draft (`edited`), or independently entered text (`other`). Clearing an accepted draft resets that attribution. Submitted text is capped at 16,000 code units and marked when truncated. |
| `ended` | Session/turn/feature boundary before a classified submission, with displayed/accepted flags. Normal shutdown is neutral, not rejection. |
| `cancelled`, `dismissed`, `skipped`, `failed` | Distinguish interrupted inference, user dismissal, undisplayed results, and generation failure. |

A crash/forced kill can leave an open sample without `submitted` or `ended`; treat it as unknown, not a negative. Model outputs of `none` and candidates never shown remain in the dataset so future evaluation can distinguish missed opportunities from rejected suggestions. Slash commands are not classified as independent user feedback. This is observational data, not an automatic quality score or automatic upload pipeline.

## Preview and verification

```sh
python3 ~/omp-extensions/scripts/preview-next-action.py
```

The offline default runs this actual extension against two separate loopback models in a temporary HOME, with fixture replies and strict JSON suggestions. `/preview` changes scenarios or injects delay/failure. It makes no paid model calls. `--live --model @next-step --effort low` explicitly starts a real source-loaded session using existing credentials and configured main model, incurring normal model costs; it installs nothing. Use ordinary `omp` after native plugin installation instead of the source preview for daily use.

Run `bun test packages/next-step/tests/suggestion.test.ts` and `python3 -m unittest discover -s packages/next-step/tests -v` from the checkout. Python TUI checks require the native standalone OMP binary (`OMP_BIN` may select it), not an app session wrapper.
