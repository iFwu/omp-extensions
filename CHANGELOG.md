# Changelog

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
