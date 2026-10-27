# OMP Extensions

Seven portable display, input, optional next-step, and session-secret extensions for [Oh My Pi](https://github.com/can1357/oh-my-pi), maintained as a Bun workspace monorepo. The root `@ifwu/omp-extensions` package installs the complete suite; each feature also has its own package, source, tests, and README. MIT licensed. The secret extension is currently **Unreleased**; the existing `v0.4.0` tag does not contain it.

## Compatibility

This package targets **OMP 18.12.6**; development and CI use Bun **1.4.4**. OMP standalone supplies its own Bun runtime and host modules. The extensions import internal OMP UI components and patch existing UI behavior; compatibility with other OMP versions is not guaranteed. Re-run the real-runtime tests before changing the host version. The optional host peer dependencies document this boundary.

## Install

Install the public Git repository through OMP's plugin manager:

```sh
omp plugin install github:iFwu/omp-extensions#v0.4.0
omp plugin doctor
```

All packages share one version and repository-wide release tag. Package names are metadata, not a claim that the suite or individual packages have been published to npm. Start a new OMP process after installing or changing extensions.

Since `v0.3.0` the suite includes next-step. Uninstall a standalone next-step package before installing the suite so the extension is not registered twice; this removes the standalone settings, so set them again under the suite name as described in [next-step](packages/next-step/README.md).

The package does not provide or replace model catalogs, provider endpoints, credential stores, shared configuration, or session-management services. Optional next-step inference and session-secret handling are disabled until explicitly enabled. They add only their own feature-specific prompt context. Do not load the same extension both through the suite and standalone.

## Included modules

The root manifest explicitly registers each workspace's `src/index.ts`. Workspaces are a development boundary, not automatic OMP discovery. Internal helpers are not registered as extensions.

| Package | Behavior |
| --- | --- |
| [composer](packages/composer/README.md) | Shaded composer, session title, queued-message presentation, turn timing, and native status attachment. |
| [transcript-grouping](packages/transcript-grouping/README.md) | Groups transcript tool activity and distinguishes commentary from completed final answers. |
| [ask-history](packages/ask-history/README.md) | Renders persisted Ask answers using native history styling, retaining plain-text answers if styling fails. |
| [skill-completion](packages/skill-completion/README.md) | Adds `$`, `¥`, and `￥` skill completion through the native editor. |
| [model-switch](packages/model-switch/README.md) | Rewrites `/model <selector>` and `/models <selector>` to session-only `/switch`; bare `/model` stays the native role hub. |
| [next-step](packages/next-step/README.md) | Optional ghost drafts and single/multiple choice cards, explicit send/fill controls, and private local feedback; disabled until configured. |
| [secret](packages/secret/README.md) | On-demand masked credential requests, session-memory references, and foreground Bash injection; disabled until configured (Unreleased). |

See [Behavior contracts](https://github.com/iFwu/omp-extensions/blob/main/docs/behavior.md) for lifecycle, completion boundaries, native-input preservation, and failure isolation.

To select the composer, set the following in your own OMP configuration:

```yaml
composer:
  shape: dotfiles/claude-context
```

The historical `dotfiles/claude-context` composer identifier and `dotfiles.ask-history` persisted message type are deliberately unchanged so existing configurations and session records remain usable. Their names do not require a dotfiles checkout. The package does not write this configuration for you; without selecting the shape, the composer registration is available but the native selected shape remains in use.

### Selecting extensions

The current source suite registers all seven entries; next-step generation and secret handling are separately opt-in. Toggle the suite as a unit with:

```sh
omp plugin disable @ifwu/omp-extensions
omp plugin enable @ifwu/omp-extensions
```

For one feature, install its package from a release checkout instead of enabling the suite:

```sh
git clone --branch v0.4.0 --single-branch https://github.com/iFwu/omp-extensions.git omp-extensions-v0.4.0
omp plugin install ./omp-extensions-v0.4.0/packages/skill-completion
omp plugin doctor
```

OMP keeps a local link to that package directory: retain the checkout and keep its revision fixed. To upgrade, install from a new release checkout; native upgrade does not update local links. Linking a `main` checkout is a development workflow, not a pinned release installation. Disable or uninstall the suite before enabling individual packages, and do not also register their source files manually.

### Session-secret opt-in (Unreleased)

Use a checkout containing the Unreleased changes, rather than the existing `v0.4.0` tag. Install **either** the suite **or** the standalone package from that retained checkout:

```sh
# Suite
omp plugin install ./omp-extensions
omp plugin config set @ifwu/omp-extensions secret true
omp plugin config get @ifwu/omp-extensions secret --json

# Alternatively, standalone (do not install alongside the suite)
omp plugin install ./omp-extensions/packages/secret
omp plugin config set @ifwu/omp-secret enabled true
omp plugin config get @ifwu/omp-secret enabled --json
```

Both manifest settings default to `false`. Start a new OMP process to load the extension; changing settings does not retrofit an already-running session. Explicit source-based runs may enable it with `--secret`. Startup precedence is the CLI flag, then standalone `enabled`, then suite `secret`; use only one installation. Uninstalling a package removes its settings. Set the corresponding setting to `false` and start a new process to disable registration entirely.

When enabled, one discoverable agent tool, `secret`, supports `request` and `list`: the model reads `xd://secret` on demand and writes JSON to that URI. Only a short discovery hint is added to the prompt, not the full schema. Requests collect at least eight characters without NUL through masked input; tool schemas/results expose names and references, never credential values. Existing `/sec` manual management remains available. Values stay in the current session's memory, not a persisted credential store; reopening a session requires supplying them again.

Use `{{sec:name}}` references only with foreground Bash. Reference-bearing commands run in an isolated child environment, without raw credentials in the shell command/argv or temporary output artifacts; results are redacted before returning to the model. Ordinary Bash commands retain native behavior. Reference execution does not support PTY, background jobs, services, or persistent shell state. This is **not a sandbox or production-security guarantee**: child programs and privileged local observers can read the environment, commands can deliberately disclose values, and transformed/encoded secrets may evade redaction. Do not put credentials directly in model-visible text or command arguments. No OMP CLI/IPC implementation or 1Password integration is changed; this is a source-loaded extension with session-local state. See [secret](packages/secret/README.md) for management and limitations.

## Development and verification

Prerequisites: the official OMP **18.12.6 standalone binary**, Bun **1.4.4**, Python **3.12**, uv, and npm (for inspecting the packed distribution).

```sh
uv venv .venv
uv pip install --python .venv/bin/python pyte==0.8.2 PyYAML==6.0.3 pexpect==4.9.0
source .venv/bin/activate
bun install --frozen-lockfile
export OMP_BIN="$(command -v omp)" # point directly to the standalone binary, not a session wrapper
bun run typecheck
bun run test
bun run smoke:package
```

The tests exercise real OMP processes against loopback HTTP fixtures, including real TUI behavior. Some intentionally cross the 120-second tool/stream boundary: allow several minutes and do not shorten those waits into superficial tests. Bun-only tests cover rendering/state logic separately. A missing runtime can cause unittest skips, so check the skip summary rather than treating a green exit as evidence that TUI tests ran.

The package smoke checks and installs the root tarball and every standalone workspace tarball in separate temporary environments, runs native doctor, and completes an RPC fixture turn for each. It verifies that declared entry files and licenses ship and tests, development tooling, and dependencies do not leak into the payload. For the suite and secret package it also checks default-off configuration, persists explicit opt-in through native plugin configuration, reads it back in a separate process, and observes the short discovery hint in a fresh fixture turn. It uses no real credentials. This complements rather than replaces the TUI tests. Temporary HOME/XDG/config/session state isolates checks from personal plugins, credentials, and production configuration. `OMP_BIN` must identify the real standalone executable; wrappers that inject personal settings are outside this isolation contract.

For Git transport verification, run `python3 scripts/smoke-package.py --git-source github:iFwu/omp-extensions#<ref>` with the exact commit matching the checkout. This installs the suite through Git instead of a local link, checks that only the suite package is enabled, and omits the separate workspace smokes.

GitHub Actions runs the same checks for pull requests and `main` pushes on Linux and macOS, downloads official release binaries, and checks them against that release's `SHA256SUMS.txt`. Release tags point to commits that already passed this matrix, rather than duplicating it on tag pushes. Required checks use no model credentials and make no live-model calls. They validate integration and deterministic behavior, **not real-model response quality**.

If a check fails, first distinguish dependency/type errors, plugin discovery or import errors, and TUI timing/rendering errors. Report the OMP/Bun/Python versions, OS, exact failing command and test, and redacted stderr. Reproduce with the isolated fixtures rather than enabling production providers. Internal UI changes are a compatibility issue, not a reason to suppress extension errors.

### Next-step source preview

Run the actual next-step extension without installing or building a package:

```sh
python3 ~/omp-extensions/scripts/preview-next-action.py
```

`bun run preview:next-action` is equivalent. Python 3 uses only its stdlib; OMP must be the native 18.12.6 standalone executable (`OMP_BIN` can select it). Offline mode uses separate loopback main/suggestion models in a temporary HOME, configuration, session and feedback directory. It makes no paid model calls and cleans temporary data on exit.

`/preview` selects single/choice/multiple/none scenarios or controlled delays and failures. Single ghost drafts disappear on typing; choice cards remain visible while editing. Empty-editor cards focus the first action, Up/Down wraps, Space checks combinable tasks, Enter submits the checked/focused drafts, and Tab/Right only fills. Escape cancels without deleting editor text, after native popups close. `Alt+1/2/3` and the full-text picker remain draft-only. No parallel prototype UI or hidden main-agent suggestion context is used.

For an explicitly live source session, use `--live --model @next-step --effort low` (configure that role first). It retains the configured main model and existing credentials, loads source suite entries instead of installed extensions, and makes real model calls. It installs nothing. Daily installed use, persistent settings, model/effort selection and private local feedback are documented in [next-step](packages/next-step/README.md).


### Workspace boundaries and releases

Feature implementation and its tests live in `packages/<feature>/src` and `packages/<feature>/tests`. Cross-feature lifecycle and failure-isolation scenarios live in `tests/integration`; reusable Python process/configuration fixtures live in `test_support`. The native Bun workspace runner executes package suites in parallel, then runs integration checks.

Composer separates input rendering, queue decoration, and activity timing. Grouping owns its state and label renderer. Small single-purpose extensions stay in one implementation file; no shared runtime framework or cross-package source imports are required.

Keep the root and all workspace versions aligned, commit the single `bun.lock`, and publish one repository-wide tag only after the complete matrix passes. The root tarball contains the feature sources directly, without workspace dependency links or a separate build step. Independent npm publication is a separate distribution action, not implied by the workspace layout.


## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).
