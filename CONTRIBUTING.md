# Contributing

Keep changes focused on the existing portable extensions. Do not add personal provider configuration, credentials, session data, or host-specific paths.

Use OMP 18.12.6 standalone, Bun 1.4.4, Python 3.12, and npm. Follow the README setup, then run `bun run typecheck`, `bun run test`, and `bun run smoke:package`. The smoke covers the root suite and every standalone package. Commit the single `bun.lock` when dependency changes require it. Never update the supported host version without exercising its real UI integration.

Keep each feature's implementation and tests in its workspace. Cross-feature behavior belongs in `tests/integration`; reusable test-only process/configuration helpers belong in `test_support`. Do not create shared runtime packages without actual cross-feature reuse. Preserve persisted identifiers (`dotfiles/claude-context`, `dotfiles.ask-history`). Grouping state/render modules are internal helpers, not extension entry points. Do not duplicate extension registration.

Pull requests should explain the observable change, compatibility implications, and checks actually executed (including skips). Add focused regression coverage and update the changelog for user-visible changes. The TUI suite intentionally includes long-running scenarios; do not replace real-runtime assertions with mocks or shorten their behavioral boundaries.

All workspace packages and the root suite use one version and release tag. Update their manifests together, pass the full Linux/macOS matrix on `main`, then tag that exact commit. The root manifest explicitly lists feature entry points; merely adding a workspace does not make OMP load it. Validate standalone payloads as well as the suite, and document installation without implying npm publication.

Report bugs with versions, OS, the failing test or reproduction, and redacted stderr. Never include production tokens, provider endpoints, or private conversations.
