# Contributing

Keep changes focused on the existing portable extensions. Do not add personal provider configuration, credentials, session data, or host-specific paths.

Use OMP 18.12.6 standalone, Bun 1.4.4, Python 3.12, and npm. Install dependencies and run the commands in the README, including all unittest cases, typechecking, and the packed-package smoke. Commit `bun.lock` when dependency changes require it. Never update the supported host version without exercising its real UI integration.

Preserve persisted identifiers (`dotfiles/claude-context`, `dotfiles.ask-history`) and plain-text failure behavior. Shared grouping modules are helpers, not extension entry points. Do not duplicate extension registration.

Pull requests should explain the observable change, compatibility implications, and checks actually executed (including skips). Add focused regression coverage and update the changelog for user-visible changes. The TUI suite intentionally includes long-running scenarios; do not replace real-runtime assertions with mocks or shorten their behavioral boundaries.

Report bugs with versions, OS, the failing test or reproduction, and redacted stderr. Never include production tokens, provider endpoints, or private conversations.
