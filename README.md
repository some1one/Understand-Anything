# Understand Anything — Rust-first fork

This repository is a substantially diverged fork of
[Egonex-AI/Understand-Anything](https://github.com/Egonex-AI/Understand-Anything).
It retains the codebase knowledge-graph concept and plugin identity, with major
changes to the analysis engine, installation, graph handling, and agent workflows.
Use this fork's documentation and build commands when working with this checkout;
upstream instructions and patches may need adaptation.

Analyze a codebase into a local knowledge graph, ask questions about its components,
and explore its architecture in an interactive dashboard. The plugin supports
Claude Code and Codex through shared skills and host-specific manifests.

## What differs in this fork

- **Native Rust engine:** scanning, import and structure extraction, batching,
  incremental updates, graph queries, and other deterministic pipeline steps run
  through `understand-anything-plugin/packages/rust/run.sh`. The host model still
  supplies the analysis narrative. See the [engine reference](understand-anything-plugin/packages/rust/README.md).
- **Installation and packaging:** source builds, platform binaries, a prebuilt
  dashboard, Debian packaging, and native-plugin or standalone-skill installation
  are coordinated by Make and the installers. Packages own their dependencies;
  Python remains in installation and workflow helpers, and Node powers the dashboard.
- **Project data and exclusions:** new graphs and partitions live under `.ua/`,
  with `.uaignore` analysis rules and compatibility for existing
  `.understand-anything/` projects. Freshness checks respect analysis exclusions
  and distinguish saved snapshots from current source.
- **Focused agent exploration:** shared skills support bounded graph queries,
  component explanations, selected-part loading, and context reuse. The
  `understand-agent-instructions` skill prints this guidance or integrates it
  into a project's `AGENTS.md`.
- **Dictionary-backed queries and native benchmarks:** query normalization uses
  configured local dictionaries, with setup separated from offline graph work.
  The opt-in [benchmark harness](docs/benchmarks/large-monorepo.md) measures native
  pipeline stages with isolated artifacts and its own report contract.

Upstream changes are integrated selectively and adapted to this implementation.
The shared plugin name and version do not establish feature or runtime parity.

## Install and use

From this checkout on Linux or macOS:

```bash
./install.sh claude
# Or:
./install.sh codex
```

The installer prefers the host's native plugin CLI and registers
`understand-anything-plugin/` as the marketplace. Both catalogs live inside that
folder: `.claude-plugin/marketplace.json` for Claude and Junie CLI, and
`.agents/plugins/marketplace.json` for Codex. Each points to `./`, so the marketplace
and plugin share that directory. No separate installed marketplace is generated.
If native installation is unavailable or fails, the installer links
standalone skills and reports that hooks are unavailable. Set `UA_NO_NATIVE=1`
to choose skills-only installation explicitly.

To register the marketplace directly after cloning this repo, target the plugin
subdirectory, not the repository root:

```bash
claude plugin marketplace add /absolute/path/to/Understand-Anything/understand-anything-plugin
codex plugin marketplace add /absolute/path/to/Understand-Anything/understand-anything-plugin
```

In Junie CLI, use `/extensions marketplace add` with that same directory.
Archives and Debian packages include these same catalogs inside the plugin
payload. Native session-start hooks run a bounded, fast-forward-only `git pull`
on the plugin's own clean checkout. Cached or packaged copies can identify the
source checkout with `UA_PLUGIN_REPO=/absolute/path/to/Understand-Anything`.
They never pull the project being analyzed. See [hook behavior](understand-anything-plugin/HOSTS.md#hooks).

## Marketplace runtime setup

The source installer prepares the runtime before its native marketplace install.
For a direct marketplace install, Codex exposes `understand-setup` as its setup
workflow; the first trusted session-start hook also prepares a missing or stale
runtime. Native marketplaces do not share a general post-install shell event,
so downloading a plugin alone does not guarantee compilation has already run.

Setup compiles the Rust engine and its Cargo dependencies when no current binary
is available, fetches all 15 supported parser libraries, and configures missing
dictionaries. For a local marketplace it defaults to the plugin source directory:

- Parser libraries: `understand-anything-plugin/packages/rust/parsers/`
- Dictionary data: `understand-anything-plugin/packages/rust/dictionaries/`

Cached Codex/Claude installs resolve the registered local marketplace source so
these downloads stay with that source repository, not the analyzed project or
an unrelated working directory. Saved dictionary choices and environment overrides
remain authoritative. Engine calls reuse the recorded parser cache; an explicit
`--parser-cache-dir` still overrides it.

To run or retry setup explicitly:

```bash
make setup-runtime
# Or, from another directory:
python3 /path/to/understand-anything-plugin/scripts/setup_runtime.py --plugin-root /path/to/understand-anything-plugin
```

A successful setup is reused until its inputs or assets change. Source builds
need stable Rust/Cargo and network access for missing crates and language data.
Hooks need the host's normal trust/permissions; `UA_SKIP_RUNTIME_SETUP=1` disables
session-start preparation when managing runtime dependencies explicitly.

Junie and JetBrains AI Assistant have separate skills-only targets:

```bash
make install-junie                       # User skills: ~/.junie/skills
make install-junie LOCAL=/absolute/path/to/project  # Project .junie/skills
make install-jetbrains LOCAL=/absolute/path/to/project  # Project .agents/skills
```

The `jetbrains` target requires `LOCAL` because IDE-wide storage depends on the
IDE product and version. It previously targeted Junie's directory; use `junie`
for that layout now. The same targets work with `./install.sh <target> --local
<project>` or the Debian `understand-anything <target> --local <project>` command.
These install shared skills without native plugin hooks or named plugin agents.
The corresponding `make uninstall-junie` and `make uninstall-jetbrains` targets
accept the same `LOCAL` selection.

See [Junie's skill locations](https://junie.jetbrains.com/docs/agent-skills.html)
and [JetBrains AI Assistant skill installation](https://www.jetbrains.com/help/ai-assistant/agent-skills.html).
AI Assistant currently documents skills for Claude Agent and Codex; select a
supported agent and check the IDE's Skills page after installation.

For a project-local skills installation:

```bash
./install.sh codex --local /absolute/path/to/project
```

Claude supports native project scope; Codex uses standalone project skills for
`--local`. Standalone skills share the bundled workflows, but do not register
native hooks or named plugin agents.

Start a new host session after installation. For first-run guidance, invoke
`/understand-anything:understand-help` in Claude Code or `$understand-help` in Codex.
To analyze a project in Claude Code, run
`/understand-anything:understand`; in Codex, select `$understand`.
Then use the dashboard skill to open the generated graph. See the
[plugin guide](understand-anything-plugin/README.md) for all skills, options,
hook behavior, and troubleshooting.

## Help your agent choose when to use the plugin

General `understand-help` prints the [recommended repository instructions](understand-anything-plugin/README.md#recommended-repository-instructions).
Use `understand-agent-instructions <project-path> --write` to integrate them as
a separate section in an existing `AGENTS.md`, or copy the printed guidance into
`CLAUDE.md`. They recommend graph-based discovery for unfamiliar components and
cross-file relationships, direct reads for known single-file tasks, and no
retrieval for generic questions or relevant context already loaded. The graph
helps navigation; current source remains the evidence for behavior.

## Requirements

- Packaged installs include the native Rust engine. Source checkouts need stable
  Rust and Cargo to build it. Installation, packaging, and workflow helpers need
  Python 3.
- Git for commit-based incremental updates.
- Node.js 22 or newer for the dashboard. Source dashboard development also uses
  the pnpm version pinned in its `package.json`; prebuilt dashboards need only Node.

The analysis model is provided by the host. Graph artifacts are saved under the
analyzed project's `.ua/` directory. Source content and summaries
are processed by the host model; see the host's settings for its data handling.

## Build and install from this checkout

Run these commands at the root of the branch you want to install:

```bash
make build
make install-codex
```

Use `make install-claude` for Claude Code. The install targets run `make build`
automatically, so `make install-codex` or `make install-claude` alone is enough
when you want to build and install in one step. They use this checkout as the
plugin source; `make package` creates release archives and is not required for
a local install. Start a new host session after installing.

## Development

There is no root Python or Node project. Each package owns its dependencies.

The Rust engine GitHub Actions workflow is currently disabled; its definition is
preserved in [rust-engine.yml.disabled](.github/workflows/rust-engine.yml.disabled).
The local test and build targets below remain available.

```bash
make help
make deps
make build-core
make build-dashboard
make test-core
make test-dashboard
make lint
```

Integration regression checks run with Python 3:

```bash
make test-integration
```

`make deps-core` fetches Rust dependencies; `make deps-dashboard` installs
dashboard dependencies. `make build` builds both packages. `make package`
creates the native plugin and dashboard archives in `dist/`; `make deb` builds
the Debian package. Bare `make` runs `package`.

## Shortcuts and cleanup

```bash
make install                          # PLATFORM=codex by default; native CLI preferred
make install PLATFORM=claude
make install-local                    # Standalone skills in this repo, without a dashboard build
make install-local PLATFORM=cursor LOCAL="/absolute/path/to/project"
make engine-help                      # List engine commands; builds engine if needed
make clean-local LOCAL="/absolute/path/to/project" DRY_RUN=1
make clean-local LOCAL="/absolute/path/to/project"
make clean-cache                      # Clear caches and analysis scratch only
make uninstall-local                  # Remove local skill links, wrappers and copied payload only
make clean-build                      # Remove this checkout's dependencies and build artifacts
make clean-stamps                     # Force the next build to recheck stamped steps
make clean                            # clean-local + clean-build
```

`LOCAL` defaults to this repository for local installation and cleanup. Use a
repository root; repeat the command with a different `LOCAL` to clean another
repository. `make install` delegates directly to the installer; `make
install-<platform>` also builds the engine and dashboard before installation.
Source installs may build the Rust engine while checking the installation.

Cleanup permanently deletes selected paths with `rm`. Set `DRY_RUN=1` on any
cleanup target to print the selected paths first. Local cleanup removes only
Understand Anything skill symlinks, installer-generated tool wrappers/workflows,
and the identified copied `.agents/understand-anything-plugin` payload. It preserves
unrelated skills, tracked files, and global/native host installations.

Cache cleanup removes Python/tool caches, bytecode, TypeScript build metadata,
analysis temporary files and old analysis trash. Generated graphs/indexes,
parts, embeddings, fingerprints, configuration and metadata remain under
`.ua/`; the intermediate scan result and save summary also
remain. `clean-build` always targets this source checkout, even when `LOCAL`
selects another repository for `clean-local`.

## TODO / future work

- Add relevance ranking before limiting graph matches: score exact symbol/path
  matches and meaningful term coverage, with stable tie-breaking. Dictionary-backed
  normalization and word filtering are implemented.

## Layout

- [Plugin](understand-anything-plugin/README.md): manifests, skills, agents, hooks,
  deterministic commands, and packages.
- [Engine](understand-anything-plugin/packages/rust/README.md): Rust analysis,
  graph contracts, persistence, search, and context builders.
- `understand-anything-plugin/packages/dashboard/`: React/TypeScript dashboard
  and its standalone Node server.
- `install.sh`, `scripts/build_dist.py`, and `packaging/deb/`: installation and
  distribution.
- [Agent guidance](AGENTS.md): repository conventions for coding agents.

Distribution bundles exclude dictionary data and never download it. Installation
and plugin updates discover compatible system dictionaries, record their paths,
and maintain downloaded data for missing components. Marketplace setup defaults
to the plugin source directory as described above. Other first-time dictionary
maintenance can choose shared OS storage or repo storage and saves that choice.
Unattended installers can set `UA_DICTIONARY_STORAGE=shared` or `repo`; existing
configurations reuse their saved path.
Use `make update-dictionaries` to repeat that process or `make configure-dictionaries`
for offline discovery. Graph updates and searches stay offline.
Downloaded dictionaries and generated query caches should stay out of Git.
For multiple projects, use the [shared storage setup and recommendations](understand-anything-plugin/scripts/dictionaries.md#share-downloads-across-projects);
per-project caches remain separate. See [dictionary maintenance](understand-anything-plugin/scripts/dictionaries.md).

## Project data directory compatibility

New analyses store project data in `.ua/`. Existing projects with only
`.understand-anything/` keep using that directory. When both exist, `.ua/` is
selected for the entire workflow; missing files are not borrowed from the old
snapshot. To migrate manually, stop analysis and dashboard processes, move the
whole legacy directory to `.ua`, and update any custom dictionary paths in your
configuration. Project-specific data and caches stay inside the selected directory;
shared dictionaries and the plugin installation home keep their existing locations.

## Native stage benchmarks

The optional [large-repository benchmark](docs/benchmarks/large-monorepo.md)
measures deterministic Rust stages with isolated artifacts and versioned reports.
Use `make help` for the explicit target; normal builds and tests do not run scale
benchmarks.

## License

This fork uses the [MIT License](LICENSE), matching
[upstream](https://github.com/Egonex-AI/Understand-Anything/blob/main/LICENSE).
The license preserves the upstream copyright notices for Yuxiang Lin and
Infinite Universe, Inc. The plugin includes the same license so marketplace
installs and distribution packages carry it with the code.

Third-party dependencies and dictionary datasets retain their own licenses;
see [dictionary provenance and licensing](understand-anything-plugin/scripts/dictionaries.md).
