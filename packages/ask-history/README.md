# Ask History

`@ifwu/omp-ask-history` · OMP 18.13.3+ · MIT

Keep native Ask questions and answers readable when tool activity is hidden, and retain them across session resume without adding display records to model context.

## Install this package only

From a checkout of a released tag, run at the repository root:

```sh
omp plugin install ./packages/ask-history
omp plugin doctor
```

This creates a persistent local link. Keep the checkout at that revision and start a new OMP process; for upgrades, install from a new release checkout. A `main` checkout is suitable for development, not a pinned installation. Do not enable this package together with `@ifwu/omp-extensions` or register its entry file twice. The package name does not imply npm publication.

## Behavior

The historical `dotfiles.ask-history` message type remains unchanged. When native tool results are visible, the extra display yields to them to avoid duplicates. Old sessions without these records are not rewritten.

See the [behavior contracts](https://github.com/iFwu/omp-extensions/blob/main/docs/behavior.md) for boundaries, cleanup, and failure isolation.

## Source and tests

The single `src/index.ts` implements recording, native rendering, and plain-text fallback.

After the repository's [development setup](https://github.com/iFwu/omp-extensions#development-and-verification), run from its root:

```sh
bun run --filter @ifwu/omp-ask-history test
```

Tests live in this package's `tests/` directory and use the shared test-only fixtures. The root `bun run smoke:package` additionally packs and installs this package in isolation. It requires no live-model credentials. All workspace packages share the root release version and tag.
