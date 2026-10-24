# OMP Extensions

Five portable display and input extensions for [Oh My Pi](https://github.com/can1357/oh-my-pi), packaged as `@ifwu/omp-extensions`. MIT licensed.

## Compatibility

This package targets **OMP 18.12.6**; development and CI use Bun **1.4.4**. OMP standalone supplies its own Bun runtime and host modules. The extensions import internal OMP UI components and patch existing UI behavior; compatibility with other OMP versions is not guaranteed. Re-run the real-runtime tests before changing the host version. The optional host peer dependencies document this boundary.

## Install

Install the public Git repository through OMP's plugin manager:

```sh
omp plugin install github:iFwu/omp-extensions
omp plugin doctor
```

For a tagged release, use `github:iFwu/omp-extensions#v0.1.0` once that tag exists. The npm package name is metadata, not a claim that this package has been published to npm. Start a new OMP process after installing or changing extensions.

The package does not provide or replace model catalogs, provider endpoints, credentials, shared configuration, prompts, or session-management services. It does not enable any external service. Do not register both this package and copies of its individual extensions in the same process.

## Included modules

All five entries are registered directly in `omp.extensions` and enabled when the package is enabled. `grouping-line.ts` and `grouping-state.ts` are shared helpers, not extension entries.

| Entry | Behavior |
| --- | --- |
| `claude-context.ts` | Shaded composer, session title, queued-message presentation, turn timing, and native status attachment. |
| `transcript-grouping.ts` | Groups transcript tool activity and distinguishes commentary from completed final answers. |
| `ask-history.ts` | Renders persisted ask answers using native history styling, retaining plain-text answers if styling fails. |
| `skill-completion.ts` | Adds `$`, `¥`, and `￥` skill completion through the native editor. |
| `model-switch.ts` | Rewrites `/model <selector>` and `/models <selector>` to session-only `/switch`; bare `/model` stays the native role hub. |

See [Behavior contracts](https://github.com/iFwu/omp-extensions/blob/main/docs/behavior.md) for lifecycle, completion boundaries, native-input preservation, and failure isolation.

To select the composer, set the following in your own OMP configuration:

```yaml
composer:
  shape: dotfiles/claude-context
```

The historical `dotfiles/claude-context` composer identifier and `dotfiles.ask-history` persisted message type are deliberately unchanged so existing configurations and session records remain usable. Their names do not require a dotfiles checkout. The package does not write this configuration for you; without selecting the shape, the composer registration is available but the native selected shape remains in use.

### Selecting extensions

The plugin has no optional-feature layer: OMP feature flags do not disable its base entries. Toggle the whole package with:

```sh
omp plugin disable @ifwu/omp-extensions
omp plugin enable @ifwu/omp-extensions
```

For only some entries, disable or uninstall the package registration, keep a local checkout, and add only the desired `src/*.ts` entries to your own OMP `extensions` list. Keep both grouping helper files alongside `transcript-grouping.ts`; do not register the helpers. Avoid enabling the package as well, which would load entries twice.

## Development and verification

Prerequisites: the official OMP **18.12.6 standalone binary**, Bun **1.4.4**, Python **3.12**, uv, and npm (for inspecting the packed distribution).

```sh
uv venv .venv
uv pip install --python .venv/bin/python pyte==0.8.2 PyYAML==6.0.3
bun install --frozen-lockfile
export OMP_BIN="$(command -v omp)" # point directly to the standalone binary, not a session wrapper
bun run typecheck
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/smoke-package.py
```

The tests exercise real OMP processes against loopback HTTP fixtures, including real TUI behavior. Some intentionally cross the 120-second tool/stream boundary: allow several minutes and do not shorten those waits into superficial tests. Bun-only tests cover rendering/state logic separately. A missing runtime can cause unittest skips, so check the skip summary rather than treating a green exit as evidence that TUI tests ran.

The package smoke creates and checks the npm tarball, installs its extracted public payload using the real plugin manager in a temporary HOME, runs doctor, and completes a real RPC fixture turn with plugin discovery enabled. This complements rather than replaces the TUI tests. Temporary HOME/XDG/config/session state isolates checks from personal plugins, credentials, and production configuration. `OMP_BIN` must identify the real standalone executable; wrappers that inject personal settings are outside this isolation contract.

GitHub Actions runs the same checks on Linux and macOS, downloads official release binaries, and checks them against that release's `SHA256SUMS.txt`. Required checks use no model credentials and make no live-model calls. They validate integration and deterministic behavior, **not real-model response quality**.

If a check fails, first distinguish dependency/type errors, plugin discovery or import errors, and TUI timing/rendering errors. Report the OMP/Bun/Python versions, OS, exact failing command and test, and redacted stderr. Reproduce with the isolated fixtures rather than enabling production providers. Internal UI changes are a compatibility issue, not a reason to suppress extension errors.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).
