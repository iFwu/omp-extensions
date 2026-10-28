# Changelog

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
