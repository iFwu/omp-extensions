# Session Model Switching

`@ifwu/omp-model-switch` · OMP 18.12.6 · MIT

Make `/model <selector>` and `/models <selector>` use native session-only `/switch` semantics.

## Install this package only

From a checkout of a released tag, run at the repository root:

```sh
omp plugin install ./packages/model-switch
omp plugin doctor
```

This creates a persistent local link. Keep the checkout at that revision and start a new OMP process; for upgrades, install from a new release checkout. A `main` checkout is suitable for development, not a pinned installation. Do not enable this package together with `@ifwu/omp-extensions` or register its entry file twice. The package name does not imply npm publication.

## Behavior

Bare `/model` and `/models` retain the native management UI. Model roles, provider configuration, service tiers, and credentials are not changed.

See the [behavior contracts](https://github.com/iFwu/omp-extensions/blob/main/docs/behavior.md) for boundaries, cleanup, and failure isolation.

## Source and tests

The single `src/index.ts` normalizes the input command and registers the input transform.

After the repository's [development setup](https://github.com/iFwu/omp-extensions#development-and-verification), run from its root:

```sh
bun run --filter @ifwu/omp-model-switch test
```

Tests live in this package's `tests/` directory and use the shared test-only fixtures. The root `bun run smoke:package` additionally packs and installs this package in isolation. It requires no live-model credentials. All workspace packages share the root release version and tag.
