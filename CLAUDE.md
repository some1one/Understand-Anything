# Understand Anything

Read [AGENTS.md](AGENTS.md) and [plugin host guidance](understand-anything-plugin/HOSTS.md).

## Project Overview
An open-source tool combining LLM intelligence + static analysis to produce interactive dashboards for understanding codebases.

## Prerequisites
- Python >= 3.14 and PDM (for the Python package)
- Node.js >= 22 and pnpm 10.6.2 (pinned via `packageManager` in the dashboard's `package.json`) — for the dashboard only

## Architecture
The root **Makefile** orchestrates two independent, self-configured subprojects under `understand-anything-plugin/packages/`. Each owns its own config (`pyproject.toml` / `package.json`); there is no root-level project config or pnpm workspace.

- **understand-anything-plugin/** — shared Claude Code and Codex plugin:
  - **packages/core** — Python (PDM). The single Python package. `understand_core/` is the whole engine: the deterministic analysis pipeline (project scanning, import resolution, structural extraction via tree-sitter, batching, graph assembly, fingerprints, auto-update — runnable via `pdm run <script>` / `python -m understand_core.<mod>`) *plus* the graph view-model, on-disk persistence, schema/search, and language/framework registries. `skill_builders/` (the chat/diff/explain/onboard prompt builders) sits alongside it as a second top-level package in the same project. (The formerly-separate `arch_analysis` package was folded into `understand_core`; its strict JSON-Schema validator lives at `understand_core/json_schema.py` — distinct from the view-model `understand_core/schema.py`.)
  - **packages/dashboard** — React + TypeScript web dashboard (React Flow, Zustand, TailwindCSS v4), built with Vite/pnpm. Self-contained: its browser-safe `types`/`schema`/`search` live in `src/core/` and are reached via the `@understand-anything/core/*` path alias (tsconfig + vite).
  - **skills/** — Skill definitions (`/understand`, `/understand-dashboard`, etc.)
  - **agents/** — Agent definitions (project-scanner, file-analyzer, architecture-analyzer, graph-reviewer)

Import model (Python): `packages/core/` is on `sys.path` so `import understand_core` / `import skill_builders` resolve, and `python -m understand_core.<mod>` runs. Modules within `understand_core` import each other with relative imports (`from .models import …`). Do **not** add `__init__.py` to `packages/` or `understand-anything-plugin/` — the latter is hyphenated and cannot be a Python package, and either one shadows `understand_core`'s relative imports.

## Dashboard
- Dark luxury theme: deep blacks (#0a0a0a), gold/amber accents (#d4a574), DM Serif Display typography
- Graph-first layout: 75% graph + 360px right sidebar
- No ChatPanel or Monaco Editor
- Sidebar tabs: `Info` (ProjectOverview default → NodeInfo when node selected → LearnPanel in Learn persona, composing) and `Files` (FileExplorer tree built from the structural graph)
- Code viewer: prism-react-renderer source viewer that slides up from the bottom on file node click; an expand button promotes it into a full-screen modal. Source content is fetched from the dev server's `/file-content.json` endpoint, gated by access token + a graph-derived path allowlist
- Schema validation on graph load with error banner

## Agent Pipeline
- The deterministic pipeline is the Python `understand_core` package. Skills/hooks/agents invoke it through the bundled launcher **`packages/core/run.sh <module> [args…]`**, which self-locates, creates the `understand_core` virtualenv on first use (PDM in a source checkout; `python3 -m venv` and pip in packaged distributions), sets `PYTHONPATH` to `packages/core` so `import understand_core` resolves, and preserves the caller's cwd (pass absolute paths). There are no Node analysis scripts anymore.
- Skills resolve `PLUGIN_ROOT` from the loaded skill's physical path and warm the env via `skills/understand/scripts/ensure_python_env.sh`; agents receive this root explicitly. Native hooks use the host-provided plugin-root variable. The skill `.py` scripts (e.g. `query_graph.py`) are standalone stdlib operating on `.understand-anything/*.json` — they do not import the packages.
- Agents write intermediate results to `.understand-anything/intermediate/` on disk (not returned to context)
- Agent model field is omitted from frontmatter so each platform falls back to its configured default — `inherit` was a Claude Code-only keyword that opencode (and similar tools) treated as a literal model id and rejected with `ProviderModelNotFoundError` (see #167)
- `/understand` does **not** auto-launch the dashboard — on completion it prints instructions for the user to run `/understand-dashboard` themselves
- Intermediate files cleaned up after graph assembly
- **Part-based analysis (default).** `/understand` splits the repo into folder-parts and analyzes each independently, merging into `knowledge-graph.json`. A layout pre-scan (`detect_layout`) recommends `{sourceFolders, splitDepth}` (single `src/` → depth 1; monorepo → depth 2; flat → depth 1); the first run lists parts and prompts which to include, persisting `sourceFolders`/`splitDepth`/`includedParts` in `config.json` (reused silently on updates). `--all` skips partition-selection prompts; ignore review still applies; `--source=`/`--split=` override detection. Each part is written to `.understand-anything/partitions/<part>.knowledge-graph.json` (with `part:<name>` + cross-part **boundary stubs**), then `merge_parts`/`merge_subdomain_graphs` recombine them (a real node beats a stub). A part is a file subset, so per-part batching reuses `compute_batches --changed-files`; incremental updates re-analyze only affected/pending parts (`parts_to_process`). Core modules: `detect_layout`, `partition_files`, `assemble_part_graph`, `merge_parts`, `parts_to_process`, `affected_parts`, `write_config`, `boundary_stubs`.
- Part-aware skills: `/load-graph [--all | <parts>]` (loads the full merged graph or only selected parts into context), `/understand-add-part <dir>` (analyze a new folder as a part), `/understand-merge` (recombine parts without re-analyzing).

## Key Commands
All run from the repo root via the Makefile (`make help` lists everything). Each target `cd`s into the relevant subproject. The **default goal is `package`** (build all distributable artifacts into `dist/`).
- `make deps` — Install all deps (`pdm install` for core, `pnpm install` for dashboard)
- `make install-<platform> [LOCAL=<dir>]` — Install the plugin for an agent/IDE. Per-platform targets so `make install-<TAB>` completes (`claude`, `codex`, `opencode`, `agents`, `vscode`, `jetbrains`, `kilo`, `kiro`, `cursor`). Prefers the target's native CLI (`claude plugin install`, `codex plugin add`), falling back to the scripted `install.sh`. The project dir for a local install is the `LOCAL` variable, given inline: `LOCAL=. make install-cursor`. `make uninstall-<platform> [LOCAL=<dir>]` reverses it. (Concrete rules are generated per platform via `foreach`/`eval` — a bare `install-%:` pattern is skipped for names listed in `.PHONY`.)
- `make build` — Build everything with a build step (the dashboard: `tsc -b && vite build`)
- `make test` — Run all suites (`test-core`, `test-dashboard`)
- `make test-core` / `make test-dashboard` — Per-project tests
- `make lint` — ESLint the dashboard
- `make dev` — Dashboard dev server (Vite)
- `make clean` — Remove venvs, node_modules, dist, caches

Python tests run as `pdm run python -m pytest` (invoke pytest as a module — pdm's generated `bin/pytest` shebang is not portable if the venv is moved/copied).

## Conventions
- Python (core): PDM-managed, one `pyproject.toml`, pytest, pydantic; JSON wire keys stay camelCase via pydantic aliases.
- Dashboard: TypeScript strict mode, Vitest, ESM.
- Knowledge graph JSON lives in the `.understand-anything/` directory of analyzed projects.
- The dashboard's browser-safe view-model (`src/core/{types,schema,search}.ts`) is the only TypeScript copy of those; the analysis engine's source of truth is Python.

## Gotchas
- **tree-sitter**: The Python packages use `tree-sitter` + `tree-sitter-language-pack` (native wheels). `understand_core.treesitter.parse(language_id, source)` returns the **root node directly** (not a tree) and takes a language id, not a Parser.
- **Dashboard core imports**: the dashboard imports `@understand-anything/core/{types,schema,search}`, which resolve to `dashboard/src/core/*` via the tsconfig `paths` alias and matching `resolve.alias` in `vite.config.ts` + `vite.config.demo.ts`. There is no `@understand-anything/core` package anymore.
- **No root project config**: don't reintroduce a root `package.json`/`pyproject.toml`/pnpm workspace — subproject configs are intentionally self-contained.

## Build & Distribution
`make package` / `make deb` (→ `scripts/build_dist.py`) produce artifacts in `dist/`. **Archives contain only copyable content — all symlinks / moves / renames / per-platform layout are done by the install scripts, never baked into the archives.**
- **Python** (`dist/python/`): the single `understand-anything-core` wheel + sdist. `understand_core` and `skill_builders` are normal package dirs, so this is a plain in-place `pdm build` (no flat-package staging).
- **One core archive** `understand-anything-plugin-<ver>.tar.gz`: the copied/source payload (skills, agents, hooks, `.claude-plugin`, `.codex-plugin`, Python source + `run.sh`, dashboard `serve.mjs`). Platform-agnostic, no build output.
- **Separate build-specific archives** (extracted *onto* the payload by the installer):
  - `understand-anything-wheelhouse-<plat>-<ver>.tar.gz` — offline `pip wheel` of the core package + all deps → `packages/core/wheelhouse/`. **CPU/OS + Python-version specific** (the wheels are e.g. `cp314 … x86_64`). `run.sh` installs from it with `--no-index`, and **falls back to an online install** if the wheelhouse doesn't match the interpreter.
  - `understand-anything-dashboard-<ver>.tar.gz` — `vite build` static output → `packages/dashboard/dist/`. `launch_dashboard.sh` runs `node serve.mjs` when `dist/` is present, else falls back to `vite` dev. `serve.mjs` is a zero-dep port of the dev-server's token-gated endpoints.
- **`understand-anything_<ver>_<arch>.deb`** (`make deb`, linux_x64/py3.14): bundles the three archives + a per-user linker. Uses dpkg's own mechanisms — `Depends: python3 (>= 3.14~), python3-venv, python3-pip` (+ `Recommends: nodejs`), and a `postinst` that assembles the payload into `/usr/share/understand-anything/understand-anything-plugin` and warms the venv system-wide. The per-user linker generates separate Claude and Codex marketplace catalogs under `~/.understand-anything/marketplace`, pointing to the system payload. Built with `dpkg-deb --root-owner-group` (no fakeroot needed).

### Native-CLI-first
Both installers **prefer a target's built-in plugin CLI and fall back to the scripted symlink installer**. Two targets have a marketplace-style native install for this plugin:
- **Claude Code** — `claude plugin marketplace add <marketplace-root>` + `claude plugin install understand-anything@understand-anything --scope user|project` (user and project scopes).
- **Codex** — `codex plugin marketplace add <marketplace-root>` + `codex plugin add understand-anything@understand-anything` (inspect installed state with `codex plugin list --json`). Codex's marketplace install is **global-only** (no per-project scope), so a `--local` codex install falls back to the scripted path.

On any failure the installer falls back. **opencode** is intentionally *not* native: `opencode plugin <module>` installs an npm module, not SKILL.md skills, so opencode (like `agents`, `vscode`, `jetbrains`, `kilo`, `kiro`, `cursor`) is a filesystem skill-drop. `UA_NO_NATIVE=1` forces the scripted path everywhere. Both installers use `scripts/create_marketplace.py` from the plugin to create installer-owned catalogs: `.claude-plugin/marketplace.json` for Claude and `.agents/plugins/marketplace.json` for Codex. Standalone fallback installs skills only; it does not register native hooks.

### Install scripts (two, by design)
- **`install.sh`** (repo root) — standalone installer for source/tarball users. Finds the archives (next to it, `$UA_ASSET_DIR`, `dist/`, or `/usr/share/...`) and **assembles** them (else falls back to `git` via `UA_REPO_URL`), checks prerequisites, tries the native CLI, else links skills per platform, symlinks `~/.understand-anything-plugin`, writes the Kiro agent config, and warms the venv. Modes: `install.sh <platform> [--local <PATH>]`, `--uninstall <platform> [--local <PATH>]`, `--assemble <dir>`, `--update`. `--local <PATH>` is a per-platform **flag** (required for `cursor`, optional for the rest); there is no separate `local` subcommand. Platform layout tables live here.
- **`packaging/deb/understand-anything`** — the deb's slim per-user linker (installed to `/usr/bin/understand-anything`). Same `<platform> [--local <PATH>]` interface and native-CLI-first behavior, but does **only** per-user linking/native-install against the system payload; assembly, prerequisites, and env-warming are handled by the deb's `postinst`/`Depends`, so it deliberately omits them.

Platform set (kept in sync between both scripts, `install.sh`, and the Makefile's `INSTALL_PLATFORMS`): `claude` (native `claude plugin`; scripted fallback → `~/.claude/skills`), `codex` (native `codex plugin`, global-only; scripted fallback → `~/.agents/skills`), `opencode` (scripted → `~/.agents/skills`), `agents` (cross-client `~/.agents/skills`: VSCodium/…), `vscode` (Copilot → `~/.copilot/skills`), `jetbrains` (Junie → `~/.junie/skills`), `kilo`, `kiro`; all support an optional `--local <PATH>`, and `cursor` is project-only (`--local` required → `.cursor/skills`). Note: the Zed IDE is **not** a target — it reads AGENTS.md/`.rules` (worktree root or `~/.config/zed/AGENTS.md`), not a skills drop.

## Scripts
- `understand-anything-plugin/packages/dashboard/scripts/generate-large-graph.mjs` — Generates a fake knowledge graph for performance testing. Writes to `.understand-anything/knowledge-graph.json`. Usage: `node scripts/generate-large-graph.mjs [nodeCount]` (default: 3000 nodes). Not part of the production pipeline.

## Versioning and local testing

Keep the release version aligned in the two plugin manifests:
`understand-anything-plugin/.claude-plugin/plugin.json` and
`understand-anything-plugin/.codex-plugin/plugin.json`. Do not bump versions merely
because a commit or push is requested. Package versions may have their own lifecycle.

Validate the plugin with `claude plugin validate understand-anything-plugin`.
For Claude development, launch `claude --plugin-dir /absolute/path/to/understand-anything-plugin`
from a fixture project. For installed plugins, use the native update/reinstall
workflow and start a new session. Do not replace host cache directories manually.

Run regression checks with
`understand-anything-plugin/packages/core/.venv/bin/python -m pytest scripts/tests -q`.
Test hooks using their stdin JSON contract. Codex hook execution also requires
host trust; never bypass that trust to make a test pass.
