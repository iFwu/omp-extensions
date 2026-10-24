# Changelog

## 0.1.0

- Extract the existing composer, transcript grouping, ask-history rendering, skill completion, and session-only model switching into a standalone MIT-licensed OMP plugin package.
- Preserve the `dotfiles/claude-context` composer shape and existing persisted message identifiers.
- Keep provider catalogs, credentials, personal configuration, model prompts, and session-management integrations outside the package.
- Include isolated real-OMP fixture tests and Linux/macOS verification targeting OMP 18.12.6.
