# Composer

`@ifwu/omp-composer` · OMP 18.18.6 · MIT

Queue headings and Working/Worked duration display. The input editor, drafts, queue delivery, status controls, and provider context remain native.

## Install this package only

From a checkout of a released tag, run at the repository root:

```sh
omp plugin install ./packages/composer
omp plugin doctor
```

This creates a persistent local link. Keep the checkout at that revision and start a new OMP process; for upgrades, install from a new release checkout. A `main` checkout is suitable for development, not a pinned installation. Do not enable this package together with `@ifwu/omp-extensions` or register its entry file twice. The package name does not imply npm publication.

## Behavior

The input editor and status line are native OMP; this package registers no composer shape and writes no configuration. See the [behavior contracts](https://git.nice.do/fwu/omp-extensions/src/branch/main/docs/behavior.md) for boundaries, cleanup, and failure isolation.

## Source and tests

`src/index.ts` coordinates registration and lifecycle. `queue.ts` owns queue decoration and rollback, and `activity.ts` owns working intent and timing.

After the repository's [development setup](https://git.nice.do/fwu/omp-extensions#development-and-verification), run from its root:

```sh
bun run --filter @ifwu/omp-composer test
```

Tests live in this package's `tests/` directory and use the shared test-only fixtures. The root `bun run smoke:package` additionally packs and installs this package in isolation. It requires no live-model credentials. All workspace packages share the root release version and tag.
