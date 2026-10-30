# Skill Completion

`@ifwu/omp-skill-completion` · OMP 18.13.3+ · MIT

Use `$`, `¥`, or `￥` after a whitespace boundary to discover and select native OMP skills. Selection inserts `/skill:<name>` without submitting the draft.

## Install this package only

From a checkout of a released tag, run at the repository root:

```sh
omp plugin install ./packages/skill-completion
omp plugin doctor
```

This creates a persistent local link. Keep the checkout at that revision and start a new OMP process; for upgrades, install from a new release checkout. A `main` checkout is suitable for development, not a pinned installation. Do not enable this package together with `@ifwu/omp-extensions` or register its entry file twice. The package name does not imply npm publication.

## Behavior

Native skill discovery and `skills.enableSkillCommands` remain authoritative. Currency amounts such as `￥100`, environment-variable forms, shell substitutions, escaped tokens, and command drafts are not rewritten.

Markdown quotes do not put the draft in command mode. `$`, `¥`, and `￥` can open and filter skills after a quote followed by a blank line; selection preserves the quoted context, line breaks, and arguments.

See the [behavior contracts](https://github.com/iFwu/omp-extensions/blob/main/docs/behavior.md) for boundaries, cleanup, and failure isolation.

## Source and tests

The single `src/index.ts` contains token detection and the native autocomplete adapter.

After the repository's [development setup](https://github.com/iFwu/omp-extensions#development-and-verification), run from its root:

```sh
bun run --filter @ifwu/omp-skill-completion test
```

Tests live in this package's `tests/` directory and use the shared test-only fixtures. The root `bun run smoke:package` additionally packs and installs this package in isolation. It requires no live-model credentials. All workspace packages share the root release version and tag.
