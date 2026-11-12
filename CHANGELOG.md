# Changelog

## 0.11.4

- Support OMP 18.19.0: align the extension SDK, peer dependencies, and CI host.
- Prepare and cache the pinned official OMP host once per platform, then share verified artifacts across the CI matrix. Recheck release checksums on every restore and use bounded retries for cold downloads.

## 0.11.3

- Support OMP 18.18.3. CI and the source preview select the runtime from the root SDK pin.
- Verify native HTML-form Ask submission, field-by-field RPC answers, and persisted answer rendering after resume. Pre-form history remains readable through the native text fallback.
- Freeze credential-command process groups before forced termination on timeout, cancellation, or excessive output, preventing waiting shells from continuing when their children stop. Shell cleanup traps do not run on these forced stops.
- Retry interrupted CI downloads of the pinned OMP release and its checksum before verifying the binary.
- Synchronize editor reset in the skill-completion TUI checks and submit next-step fixture prompts directly through the editor.
- Check composer queue headings against OMP's native handoff: claimed messages leave the queue while requests are still being prepared.

## 0.11.2

- Keep the text of a single next-step recommendation visible above the composer while typing. Enter still submits only the text in the composer.

## 0.11.1

- Expose the independent next-step request payload through a synchronous public extension event so host provider routing can apply the same wire-model namespace rules as ordinary turns. Standalone use without a routing listener keeps its original payload.

## 0.11.0

- Render a single next-step recommendation as a card above the composer, like choices, instead of editor ghost text. Next-step no longer writes into the editor's prediction slot. Cards preview up to three lines of the draft Enter would send, stay visible as read-only reference while typing, and accept keys again once the composer is empty.

## 0.10.0

- Keep a single next-step ghost draft while typing: it hides, the hint line says so, and deleting back to an empty composer shows it again. Only Escape, submission, or a turn/session boundary discards it.
- Add Ctrl+Enter to the `Alt+/` and `/next-step pick` selector: it fills the highlighted draft and submits it once through the native input path. Enter still only fills.
- Correct the behavior contract that still said no JEV gate is used.

## 0.9.0

- Gate next-step generation on the native `judge` role (for example `typesafe/jev-1.14.0`) when it resolves to a native judgment API: generation runs only when the judge gives at least 0.4 probability that the user will approve or pick something the latest answer proposed. Gate errors and its 5-second deadline fail open; a `gated` feedback event records each decision. Without a native judge, behavior is unchanged.
- Revise the suggestion prompt (`next-step-5`) toward short approvals of what the assistant offered, recommended, or diagnosed. Options the answer lists stay a choice with the recommended option first.
- Move the canonical repository, Git installation examples, package metadata, contributions, and issue tracker to [Forgejo](https://git.nice.do/fwu/omp-extensions). Keep version `0.8.0` and existing release tags unchanged. GitHub remains a downstream mirror.
- Document the retained GitHub verification workflow and the separate Forgejo runner/workflow setup required for equivalent Linux/macOS automation.

## 0.8.0

- Restore next-step ghost text with OMP 18.16.0's native `predictions()` list API. Single recommendations, choice previews, native-completion fallback, and send/fill controls keep their existing behavior.
- Pin the SDK and CI host to OMP 18.16.0. Support and test only the current pinned OMP release, without older-host compatibility branches or tests.

## 0.7.2

- Render all grouping statistics, including failure counts, in the theme's `borderMuted` color on light themes; dark themes keep `dim` because `borderMuted` nearly matches their background. `Done` labels and rules are unchanged.

## 0.7.1

- Render the elapsed time of gaps of at least 120 seconds in the same muted color as other gap statistics; the following blank line still separates longer phases. `Done` separators are unchanged.

## 0.7.0

- Remove the `dotfiles/claude-context` shaded composer shape and its session-title row; the input editor and status line are native OMP. Configurations that still select that shape should reset `composer.shape`. Queue headings, Working/Worked timing, and the other extensions are unchanged.

## 0.6.0

- Allow uppercase and mixed-case session-secret names and leading underscores across masked requests, `/sec` management, reference parsing and Tab completion. Preserve case-sensitive identity, existing lowercase/hyphenated names and the 64-character limit; credential isolation and exact-output redaction are unchanged.
- Require OMP 18.13.3 or newer and replace the custom secret-input component with native `ctx.ui.input(..., { secret: true, signal })`. Remove the private keystroke parser and its component tests; retain real TUI masking, cancellation, transport and persistence checks. Move the development SDK and CI host to 18.13.3.

## 0.5.3

- Drain next-step fixture PTY output while waiting for SIGTERM shutdown, avoiding blocked terminal writes and repeated five-second waits before forced termination.
- Replace real 21-second/60-second suggestion timing waits with an extension-scoped clock and deadline signal. Keep real provider requests, input acceptance, cancellation, timeout classification, and later-turn recovery under test. Production deadlines, global clocks, and native scheduling remain unchanged.

## 0.5.2

- Replace the remaining two 121-second grouping fixture waits with a controllable clock injected only into the real grouping extension. Keep native OMP events, stream completion, rendered labels, foreground-tool accounting, toggles, and session transitions under test; host clocks, timeouts, and production thresholds remain unchanged.
- Advance the provider-only gap on the same simulated timeline instead of sleeping for 12 seconds. Assert exact simulated durations without mocking state or rendering results. Full cross-platform CI remains asynchronous.

## 0.5.1

- Remove persistent secret status badges at startup, after credential input, and after management commands. Use `/sec list` on demand; credential entry and execution are unchanged.
- Split Linux/macOS verification into independent workspace, integration, and typecheck/package-smoke slices. Full CI runs asynchronously without blocking publication after affected local tests and smoke pass; failures remain visible and superseded runs are cancelled.
- Add targeted package smoke selection with `--workspace`. Remove the redundant 121-second delayed-final streaming case, duplicate standalone Ask factory-failure case, and incidental ultra-wide/long-prose display checks. Retain real-TUI threshold-crossing, gap-streaming, failure-isolation, normal/narrow rendering, and credential safety coverage.

## 0.5.0

- Allow next-step generation up to 60 seconds for long-tail provider latency while preserving immediate input cancellation and one extension request per completed turn.
- Preserve next-step provider and parse failure diagnostics in `/next-step status` and private local feedback, including model, time, stop reason, and a bounded sanitized summary. Keep cancellation, warning frequency, timeout, and retry behavior unchanged.
- Add the opt-in `@ifwu/omp-secret` workspace and suite entry, default-off publicly, with one on-demand `secret` request/list tool and explicit `/sec` masked input/management. Only explicit masked entry stores credentials in session memory; only `{{sec:NAME}}` in foreground Bash consumes them, using an isolated child environment and exact-value output redaction. Ordinary inputs/tools and signed/encrypted provider history remain unchanged. Remove automatic capture/scanning, history/transcript/context/provider rewriting, file import, clipboard restore, and shape/encoded-value redaction. Cover unchanged token-looking text, explicit entry/consumption, real TUI masking, and opaque Codex Responses history with local synthetic runtime regressions. This is not a sandbox or a persistent credential store.
- Preserve the MIT-licensed pi-secret source attribution from commit `dbafa882a72c168198a2417ea6c6215b85c26fe1`. Include standalone source/license payloads and package smoke coverage for default-off installation and explicit opt-in persisted/read back in fresh processes. Release the suite and all seven standalone packages together at `0.5.0` through the repository tag; no npm publication.

## 0.4.0

- Require `selectionMode` on choice suggestions. Focus the first action by default, use Space to check combinable tasks, and join checked drafts in option order for Enter submission or Tab/Right filling.
- Keep full choice cards visible while editing without intercepting native input. Typed submissions include only the typed draft, with no hidden option/context injection. Escape cancels suggestions permanently while preserving text and respecting native popup priority; restart/resume does not restore old cards.
- Refine next-step generation around latest-answer follow-ups, user-to-assistant requests, and explicit safety prerequisites; avoid redundant verification, invented user preferences/results, extra planning gates, and implementation-detail dumps. Record choice modes and accepted index arrays in local feedback schema 2.

## 0.3.0

- Add opt-in next-step generation through native model/auth APIs: one asynchronous request per completed main TUI turn, no JEV prefilter, and mutually exclusive single ghost-text recommendations or action cards. In an empty composer, Tab/Right adopts a single ghost without sending; explicit Enter adopts and submits once. Choice cards start unselected: Up/Down select and preview one, wrapping at either end, Enter submits it once, and Tab/Right fill it without sending. User typing immediately restores native completion, and choices never have an implicit Enter default.
- Include next-step in the suite. Persist it under `@ifwu/omp-extensions` with flag-style keys (`next-step`, `next-step-model`, `next-step-effort`, `next-step-collect`, `next-step-data-dir`); the standalone package keeps its own namespace and takes precedence when both are set.
- Show choice cards as a compact aligned list: the question appears once, tradeoffs sit beside titles when they fit and wrap below them otherwise, and only the selected card is highlighted.
- Prompt next-step drafts to read like what a person would type next, leaving methods and parameters to the main agent, with soft length targets for card text. Every draft must ask the assistant for something; the user's own offline actions produce no suggestion.
- Record private local next-step inputs, outputs, latency, display/adoption/submission outcomes, and neutral session endings separately from conversation history; collection can be disabled.
- Replace preview-only UI state with a one-command source preview of the real feature, using isolated loopback models by default and explicit live mode for existing model configuration.

## 0.2.1

- Preserve cumulative Working duration across automatic continuations and background-result waits instead of showing a premature Worked completion and restarting the timer. Reset for a new idle user task and release activity timers on shutdown.

## 0.2.0

- Organize composer, transcript grouping, Ask history, skill completion, and model switching as independent Bun workspace packages with package-local tests and documentation.
- Keep the root package as the complete suite, with explicit feature entry points and directly included sources; use one version, lockfile, and release tag.
- Separate composer registration, input rendering, queue decoration, and activity timing without changing historical configuration or session identifiers.
- Run workspace tests through Bun and retain cross-feature failure isolation under integration tests, including combined operation after an Ask styling failure.
- Verify the root tarball and all five standalone tarballs with isolated native installation and RPC smoke, without live-model inference.
- Await observable skill-completion menu state under controlled asynchronous filtering instead of assuming a fixed input delay means filtering has finished.
- Fail the verification matrix fast when a platform fails, while requiring both platforms to pass before release.
- Allow skill completion in multiline Markdown prompts that start with a blockquote, preserving quoted context, line breaks, and inline skill arguments.

## 0.1.0

- Extract the existing composer, transcript grouping, ask-history rendering, skill completion, and session-only model switching into a standalone MIT-licensed OMP plugin package.
- Preserve the `dotfiles/claude-context` composer shape and existing persisted message identifiers.
- Keep provider catalogs, credentials, personal configuration, model prompts, and session-management integrations outside the package.
- Include isolated real-OMP fixture tests and Linux/macOS verification targeting OMP 18.12.6.
