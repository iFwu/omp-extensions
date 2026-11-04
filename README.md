# OMP Extensions

Seven portable display, input, optional next-step, and session-secret extensions for [Oh My Pi](https://github.com/can1357/oh-my-pi), maintained as a Bun workspace monorepo. The root `@ifwu/omp-extensions` package installs the complete suite; each feature also has its own package, source, tests, and README. MIT licensed. The optional secret extension is included since `v0.5.0`.

The canonical source, contributions, and [issue tracker](https://git.nice.do/fwu/omp-extensions/issues) are hosted on [Forgejo](https://git.nice.do/fwu/omp-extensions). GitHub is a downstream Git mirror, synchronized by Forgejo every 24 hours with sync-on-commit disabled. Development, installation, and deployment do not wait for that mirror. The mirror uses a repository-scoped write-enabled deploy key, not a personal account key or token; Git mirroring does not copy issues or release metadata back to GitHub.

## Compatibility

This package requires **OMP 18.16.0**; development and CI use the **18.16.0 SDK** and Bun **1.4.4**. Only the current pinned OMP release is supported and tested; older-host compatibility is not maintained. OMP standalone supplies its own Bun runtime and host modules. The extensions import internal OMP UI components and patch existing UI behavior; re-run the real-runtime tests before changing the host version. Session secrets use the native masked-input API introduced in 18.13.3.

## Install

Install the public Git repository through OMP's plugin manager:

```sh
omp plugin install git+https://git.nice.do/fwu/omp-extensions.git@v0.8.0
omp plugin doctor
```

The Forgejo instance requires Git authentication even for this public repository. Reuse your existing host-scoped Git credential helper for `git.nice.do`; the installation process must inherit access to that helper, including when using an isolated HOME. Keep tokens out of installation URLs and package manifests. Enter `@v0.8.0` in the CLI so OMP recognizes the pinned ref; OMP converts it to Bun's `#v0.8.0` form, which may appear in the installed plugin's `package.json`.

All packages share one version and repository-wide release tag. Package names are metadata, not a claim that the suite or individual packages have been published to npm. Start a new OMP process after installing or changing extensions.

Since `v0.3.0` the suite includes next-step. Uninstall a standalone next-step package before installing the suite so the extension is not registered twice; this removes the standalone settings, so set them again under the suite name as described in [next-step](packages/next-step/README.md).

The package does not provide or replace model catalogs, provider endpoints, credential stores, shared configuration, or session-management services. Optional next-step inference and session-secret handling are disabled until explicitly enabled. They add only their own feature-specific prompt context. Do not load the same extension both through the suite and standalone.

## Included modules

The root manifest explicitly registers each workspace's `src/index.ts`. Workspaces are a development boundary, not automatic OMP discovery. Internal helpers are not registered as extensions.

| Package | Behavior |
| --- | --- |
| [composer](packages/composer/README.md) | Queued-message headings and Working/Worked turn timing; the input editor stays native. |
| [transcript-grouping](packages/transcript-grouping/README.md) | Groups transcript tool activity and distinguishes commentary from completed final answers. |
| [ask-history](packages/ask-history/README.md) | Renders persisted Ask answers using native history styling, retaining plain-text answers if styling fails. |
| [skill-completion](packages/skill-completion/README.md) | Adds `$`, `¥`, and `￥` skill completion through the native editor. |
| [model-switch](packages/model-switch/README.md) | Rewrites `/model <selector>` and `/models <selector>` to session-only `/switch`; bare `/model` stays the native role hub. |
| [next-step](packages/next-step/README.md) | Optional ghost drafts and single/multiple choice cards, explicit send/fill controls, and private local feedback; disabled until configured. |
| [secret](packages/secret/README.md) | On-demand masked credential requests, session-memory references, and foreground Bash injection; disabled until configured. |

See [Behavior contracts](https://git.nice.do/fwu/omp-extensions/src/branch/main/docs/behavior.md) for lifecycle, completion boundaries, native-input preservation, and failure isolation.

### Selecting extensions

The current source suite registers all seven entries; next-step generation and secret handling are separately opt-in. Toggle the suite as a unit with:

```sh
omp plugin disable @ifwu/omp-extensions
omp plugin enable @ifwu/omp-extensions
```

For one feature, install its package from a release checkout instead of enabling the suite:

```sh
git clone --branch v0.8.0 --single-branch https://git.nice.do/fwu/omp-extensions.git omp-extensions-v0.8.0
omp plugin install ./omp-extensions-v0.8.0/packages/skill-completion
omp plugin doctor
```

OMP keeps a local link to that package directory: retain the checkout and keep its revision fixed. To upgrade, install from a new release checkout; native upgrade does not update local links. Linking a `main` checkout is a development workflow, not a pinned release installation. Disable or uninstall the suite before enabling individual packages, and do not also register their source files manually.

### Session-secret opt-in

Install **either** the suite **or** the standalone package. For the standalone option, retain the `v0.8.0` checkout created above:

```sh
# Suite
omp plugin install git+https://git.nice.do/fwu/omp-extensions.git@v0.8.0
omp plugin config set @ifwu/omp-extensions secret true
omp plugin config get @ifwu/omp-extensions secret --json

# Alternatively, standalone (do not install alongside the suite)
omp plugin install ./omp-extensions-v0.8.0/packages/secret
omp plugin config set @ifwu/omp-secret enabled true
omp plugin config get @ifwu/omp-secret enabled --json
```

Both manifest settings default to `false`. Start a new OMP process to load the extension; changing settings does not retrofit an already-running session. Explicit source-based runs may enable it with `--secret`. Startup precedence is the CLI flag, then standalone `enabled`, then suite `secret`; use only one installation. Uninstalling a package removes its settings. Set the corresponding setting to `false` and start a new process to disable registration entirely.

When enabled, one discoverable agent tool, `secret`, supports `request` and `list`: the model reads `xd://secret` on demand and writes JSON to that URI. Only a short discovery hint is added to the prompt, not the full schema. Only an explicit request or `/sec add NAME` stores a credential through masked input (at least eight characters, no NUL); tool schemas/results expose names and references, never entered values. `/sec` lists references and management commands. Values stay in the current session's memory, not a persisted credential store; reopening a session requires supplying them again. There is no automatic capture/scanning, file import, clipboard restore, or history/transcript/context/provider rewriting. Ordinary text, including passwords, CSS selectors and token-looking strings, remains unchanged and is not protected by this feature.

Use `{{sec:name}}` references only with foreground Bash. Reference-bearing commands run in an isolated child environment, without raw credentials in the shell command/argv or temporary output artifacts; only exact explicitly entered values are redacted from that command's output. Unrelated token-looking output and encoded/transformed values remain unchanged. Ordinary Bash and all other tools retain native behavior; references outside Bash are literal text. Reference execution does not support PTY, background jobs, services, or persistent shell state. This is **not a sandbox or production-security guarantee**: child programs and privileged local observers can read the environment, and commands can deliberately disclose values. Do not put credentials directly in model-visible text or command arguments. No OMP CLI/IPC implementation or 1Password integration is changed. See [secret](packages/secret/README.md) for management and limitations.

## Development and verification

Prerequisites: the official OMP **18.16.0 standalone binary**, Bun **1.4.4**, Python **3.12**, uv, and npm (for inspecting the packed distribution).

Select a candidate host with `OMP_BIN`. Skill-completion fixtures give background skill-description compression its own `smol` model so the foreground request-count assertions still detect duplicate submissions.

```sh
uv venv .venv
uv pip install --python .venv/bin/python pyte==0.8.2 PyYAML==6.0.3 pexpect==4.9.0
source .venv/bin/activate
bun install --frozen-lockfile
export OMP_BIN="$(command -v omp)" # point directly to the standalone binary, not a session wrapper
bun run typecheck
# Example: verify a secret-only change locally before publishing.
bun run --filter @ifwu/omp-secret test
bun run smoke:package --workspace secret
```

Run each affected workspace's existing test script with `bun run --filter @ifwu/omp-<feature> test`. Add `bun run test:integration` when cross-feature lifecycle, shared fixtures, or registration behavior changes. Repeat `--workspace` to smoke multiple changed standalone packages; the root suite is always included. For dependency, packaging, or changes spanning the suite, run `bun run test:workspaces`, `bun run test:integration`, and `bun run smoke:package` without a selector. `bun run test` remains the complete local workspace-plus-integration suite. Local checks must cover the affected behavior and relevant package payload before publishing; a workflow-only change needs workflow syntax/command-contract validation and relevant smoke, not a local rerun of every runtime scenario.

The tests exercise real OMP processes against loopback HTTP fixtures, including real TUI behavior. Some intentionally cross the 120-second tool/stream boundary: allow several minutes and do not shorten those waits into superficial tests. Bun-only tests cover rendering/state logic separately. A missing runtime can cause unittest skips, so check the skip summary rather than treating a green exit as evidence that TUI tests ran.

The package smoke checks and installs the root tarball and every standalone workspace tarball in separate temporary environments, runs native doctor, and completes an RPC fixture turn for each. It verifies that declared entry files and licenses ship and tests, development tooling, and dependencies do not leak into the payload. For the suite and secret package it also checks default-off configuration, persists explicit opt-in through native plugin configuration, reads it back in a separate process, and observes the short discovery hint in a fresh fixture turn. It uses no real credentials. This complements rather than replaces the TUI tests. Temporary HOME/XDG/config/session state isolates checks from personal plugins, credentials, and production configuration. `OMP_BIN` must identify the real standalone executable; wrappers that inject personal settings are outside this isolation contract.

For Git transport verification, run `python3 scripts/smoke-package.py --git-source git+https://git.nice.do/fwu/omp-extensions.git@<ref>` with the exact commit matching the checkout. This installs the suite through Git instead of a local link, checks that only the suite package is enabled, and omits the separate workspace smokes. Use `@<ref>` for this generic Git host so OMP records the installation as pinned; the installer converts it to Bun's Git ref syntax.

The retained `.github/workflows/verify.yml` runs against the delayed GitHub mirror: Linux and macOS, with independent workspace, integration, and typecheck/package-smoke slices. It downloads official OMP binaries from upstream GitHub and verifies their release checksums. Forgejo pushes and pull requests do not start that workflow; this repository does not declare an active Forgejo CI workflow. Run the relevant local checks before tagging or publishing and review asynchronous mirror CI failures when available.

If a check fails, first distinguish dependency/type errors, plugin discovery or import errors, and TUI timing/rendering errors. Report the OMP/Bun/Python versions, OS, exact failing command and test, and redacted stderr. Reproduce with the isolated fixtures rather than enabling production providers. Internal UI changes are a compatibility issue, not a reason to suppress extension errors.

### Next-step source preview

Run the actual next-step extension without installing or building a package:

```sh
python3 ~/omp-extensions/scripts/preview-next-action.py
```

`bun run preview:next-action` is equivalent. Python 3 uses only its stdlib; OMP must be the native 18.16.0 standalone executable (`OMP_BIN` can select it). Offline mode uses separate loopback main/suggestion models in a temporary HOME, configuration, session and feedback directory. It makes no paid model calls and cleans temporary data on exit.

`/preview` selects single/choice/multiple/none scenarios or controlled delays and failures. Single ghost drafts disappear on typing; choice cards remain visible while editing. Empty-editor cards focus the first action, Up/Down wraps, Space checks combinable tasks, Enter submits the checked/focused drafts, and Tab/Right only fills. Escape cancels without deleting editor text, after native popups close. `Alt+1/2/3` and the full-text picker remain draft-only. No parallel prototype UI or hidden main-agent suggestion context is used.

For an explicitly live source session, use `--live --model @next-step --effort low` (configure that role first). It retains the configured main model and existing credentials, loads source suite entries instead of installed extensions, and makes real model calls. It installs nothing. Daily installed use, persistent settings, model/effort selection and private local feedback are documented in [next-step](packages/next-step/README.md).


### Workspace boundaries and releases

Feature implementation and its tests live in `packages/<feature>/src` and `packages/<feature>/tests`. Cross-feature lifecycle and failure-isolation scenarios live in `tests/integration`; reusable Python process/configuration fixtures live in `test_support`. The native Bun workspace runner executes package suites in parallel, then runs integration checks.

Composer separates input rendering, queue decoration, and activity timing. Grouping owns its state and label renderer. Small single-purpose extensions stay in one implementation file; no shared runtime framework or cross-package source imports are required.

Keep the root and all workspace versions aligned, commit the single `bun.lock`, and publish one repository-wide tag at the exact commit whose affected local tests, typecheck, and relevant package smoke passed. Push the commit and tag to the canonical [Forgejo repository](https://git.nice.do/fwu/omp-extensions). Keep existing release tags unchanged; the hosting migration retains version `0.8.0`. Full CI is not a prerequisite for tagging or publishing after affected local checks pass. Keep available CI failures visible for investigation. The root tarball contains the feature sources directly, without workspace dependency links or a separate build step. Independent npm publication is a separate distribution action, not implied by the workspace layout.


## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).
