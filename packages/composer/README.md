# Composer

`@ifwu/omp-composer` · OMP 18.12.6 · MIT

Shaded native input, a separate session title, queue headings, and Working/Worked duration display. Native drafts, queue delivery, status controls, and provider context remain unchanged.

## Install this package only

From a checkout of a released tag, run at the repository root:

```sh
omp plugin install ./packages/composer
omp plugin doctor
```

This creates a persistent local link. Keep the checkout at that revision and start a new OMP process; for upgrades, install from a new release checkout. A `main` checkout is suitable for development, not a pinned installation. Do not enable this package together with `@ifwu/omp-extensions` or register its entry file twice. The package name does not imply npm publication.

## Behavior

Select the historical composer shape in your own OMP configuration:

```yaml
composer:
  shape: dotfiles/claude-context
```

Queue and activity enhancements do not require selecting that shape. This package does not write your configuration.

See the [behavior contracts](https://github.com/iFwu/omp-extensions/blob/main/docs/behavior.md) for boundaries, cleanup, and failure isolation.

## Source and tests

`src/index.ts` coordinates registration and lifecycle. `composer.ts` owns input rendering, `queue.ts` owns queue decoration and rollback, and `activity.ts` owns working intent and timing.

After the repository's [development setup](https://github.com/iFwu/omp-extensions#development-and-verification), run from its root:

```sh
bun run --filter @ifwu/omp-composer test
```

Tests live in this package's `tests/` directory and use the shared test-only fixtures. The root `bun run smoke:package` additionally packs and installs this package in isolation. It requires no live-model credentials. All workspace packages share the root release version and tag.
