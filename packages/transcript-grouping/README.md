# Transcript Grouping

`@ifwu/omp-transcript-grouping` · OMP 18.12.6 · MIT

Display-only transcript gaps, tool counts, foreground tool-wait timing, and completed-final separators. Copying, provider messages, and tool execution stay native.

## Install this package only

From a checkout of a released tag, run at the repository root:

```sh
omp plugin install ./packages/transcript-grouping
omp plugin doctor
```

This creates a persistent local link. Keep the checkout at that revision and start a new OMP process; for upgrades, install from a new release checkout. A `main` checkout is suitable for development, not a pinned installation. Do not enable this package together with `@ifwu/omp-extensions` or register its entry file twice. The package name does not imply npm publication.

## Behavior

Grouping is on by default. Use `/grouping` or `Ctrl+S` to toggle it independently of tool visibility. Resolve any existing `Ctrl+S` keybinding conflict in your own configuration. State is process-local and does not rewrite historical sessions.

See the [behavior contracts](https://github.com/iFwu/omp-extensions/blob/main/docs/behavior.md) for boundaries, cleanup, and failure isolation.

## Source and tests

`src/index.ts` owns host integration and restoration; `state.ts` tracks timing and boundaries, and `render.ts` formats grouping labels.

After the repository's [development setup](https://github.com/iFwu/omp-extensions#development-and-verification), run from its root:

```sh
bun run --filter @ifwu/omp-transcript-grouping test
```

Tests live in this package's `tests/` directory and use the shared test-only fixtures. The root `bun run smoke:package` additionally packs and installs this package in isolation. It requires no live-model credentials. All workspace packages share the root release version and tag.
