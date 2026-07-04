# Understand Anything

## Project Overview
An open-source tool combining LLM intelligence + static analysis to produce interactive dashboards for understanding codebases.

## Prerequisites
- Python >= 3.14 and PDM (for the two Python packages)
- Node.js >= 22 and pnpm 10.6.2 (pinned via `packageManager` in the dashboard's `package.json`) — for the dashboard only

## Architecture
The repo root holds only a **Makefile** that orchestrates three independent, self-configured subprojects under `understand-anything-plugin/packages/`. Each owns its own config (`pyproject.toml` / `package.json`); there is no root-level project config or pnpm workspace.

- **understand-anything-plugin/** — Claude Code plugin:
  - **packages/arch_analysis** — Python (PDM). Deterministic analysis engine: project scanning, import resolution, structural extraction (tree-sitter), batching, graph assembly, fingerprints, auto-update. Runnable via `pdm run <script>` / `python -m arch_analysis.<mod>`.
  - **packages/core** — Python (PDM). Port of the old `@understand-anything/core` (`understand_core/`) plus the skill builders (`skill_builders/`, formerly `src/`). Wraps `arch_analysis` (imported as a sibling package — core's pytest `pythonpath` includes `..`).
  - **packages/dashboard** — React + TypeScript web dashboard (React Flow, Zustand, TailwindCSS v4), built with Vite/pnpm. Self-contained: its browser-safe `types`/`schema`/`search` live in `src/core/` and are reached via the `@understand-anything/core/*` path alias (tsconfig + vite).
  - **skills/** — Skill definitions (`/understand`, `/understand-dashboard`, etc.)
  - **agents/** — Agent definitions (project-scanner, file-analyzer, architecture-analyzer, graph-reviewer)

Import model (Python): `packages/` is on `sys.path` so `import arch_analysis` resolves; `packages/core/` is on path so `import understand_core` / `import skill_builders` resolve. Do **not** add `__init__.py` to `packages/` or `understand-anything-plugin/` — the latter is hyphenated and cannot be a Python package, and either one shadows `arch_analysis`'s relative imports.

## Dashboard
- Dark luxury theme: deep blacks (#0a0a0a), gold/amber accents (#d4a574), DM Serif Display typography
- Graph-first layout: 75% graph + 360px right sidebar
- No ChatPanel or Monaco Editor
- Sidebar tabs: `Info` (ProjectOverview default → NodeInfo when node selected → LearnPanel in Learn persona, composing) and `Files` (FileExplorer tree built from the structural graph)
- Code viewer: prism-react-renderer source viewer that slides up from the bottom on file node click; an expand button promotes it into a full-screen modal. Source content is fetched from the dev server's `/file-content.json` endpoint, gated by access token + a graph-derived path allowlist
- Schema validation on graph load with error banner

## Agent Pipeline
- The deterministic pipeline is the Python `arch_analysis` package. Skills/hooks/agents invoke it through the bundled launcher **`packages/arch_analysis/run.sh <module> [args…]`**, which self-locates, creates the `arch_analysis` virtualenv on first use (PDM, or `python3 -m venv` fallback), sets `PYTHONPATH` to `packages/` so `import arch_analysis` resolves, and preserves the caller's cwd (pass absolute paths). There are no Node analysis scripts anymore.
- Skills resolve `PLUGIN_ROOT` (the dir with `.claude-plugin/plugin.json`) and warm the env via `skills/understand/scripts/ensure_python_env.sh`; agents/the hook resolve it via `$CLAUDE_PLUGIN_ROOT` with documented fallbacks. The skill `.py` scripts (e.g. `query_graph.py`) are standalone stdlib operating on `.understand-anything/*.json` — they do not import the packages.
- Agents write intermediate results to `.understand-anything/intermediate/` on disk (not returned to context)
- Agent model field is omitted from frontmatter so each platform falls back to its configured default — `inherit` was a Claude Code-only keyword that opencode (and similar tools) treated as a literal model id and rejected with `ProviderModelNotFoundError` (see #167)
- `/understand` does **not** auto-launch the dashboard — on completion it prints instructions for the user to run `/understand-dashboard` themselves
- Intermediate files cleaned up after graph assembly

## Key Commands
All run from the repo root via the Makefile (`make help` lists everything). Each target `cd`s into the relevant subproject. The **default goal is `package`** (build all distributable artifacts into `dist/`).
- `make deps` — Install all deps (`pdm install` for arch_analysis + core, `pnpm install` for dashboard)
- `make install-<platform> [LOCAL=<dir>]` — Install the plugin for an agent/IDE. Per-platform targets so `make install-<TAB>` completes (`claude`, `codex`, `opencode`, `agents`, `vscode`, `jetbrains`, `kilo`, `kiro`, `cursor`). Prefers the target's native CLI (`claude plugin install`, `codex plugin add`), falling back to the scripted `install.sh`. The project dir for a local install is the `LOCAL` variable, given inline: `LOCAL=. make install-cursor`. `make uninstall-<platform> [LOCAL=<dir>]` reverses it. (Concrete rules are generated per platform via `foreach`/`eval` — a bare `install-%:` pattern is skipped for names listed in `.PHONY`.)
- `make build` — Build everything with a build step (the dashboard: `tsc -b && vite build`)
- `make test` — Run all suites (`test-arch`, `test-core`, `test-dashboard`)
- `make test-arch` / `make test-core` / `make test-dashboard` — Per-project tests
- `make lint` — ESLint the dashboard
- `make dev` — Dashboard dev server (Vite)
- `make clean` — Remove venvs, node_modules, dist, caches

Python tests run as `pdm run python -m pytest` (invoke pytest as a module — pdm's generated `bin/pytest` shebang is not portable if the venv is moved/copied).

## Conventions
- Python (arch_analysis, core): PDM-managed, `pyproject.toml` per project, pytest, pydantic; JSON wire keys stay camelCase via pydantic aliases.
- Dashboard: TypeScript strict mode, Vitest, ESM.
- Knowledge graph JSON lives in the `.understand-anything/` directory of analyzed projects.
- The dashboard's browser-safe view-model (`src/core/{types,schema,search}.ts`) is the only TypeScript copy of those; the analysis engine's source of truth is Python.

## Gotchas
- **tree-sitter**: The Python packages use `tree-sitter` + `tree-sitter-language-pack` (native wheels). `arch_analysis.treesitter.parse(language_id, source)` returns the **root node directly** (not a tree) and takes a language id, not a Parser.
- **Dashboard core imports**: the dashboard imports `@understand-anything/core/{types,schema,search}`, which resolve to `dashboard/src/core/*` via the tsconfig `paths` alias and matching `resolve.alias` in `vite.config.ts` + `vite.config.demo.ts`. There is no `@understand-anything/core` package anymore.
- **No root project config**: don't reintroduce a root `package.json`/`pyproject.toml`/pnpm workspace — subproject configs are intentionally self-contained.

## Build & Distribution
`make package` / `make deb` (→ `scripts/build_dist.py`) produce artifacts in `dist/`. **Archives contain only copyable content — all symlinks / moves / renames / per-platform layout are done by the install scripts, never baked into the archives.**
- **Python** (`dist/python/`): wheels + sdists for `arch_analysis` and `core`. `arch_analysis` is flat (modules at project root), so its wheel is built from a normalized staging tree under `build/`; `pdm build` cleans `--dest` by default so the script uses `--no-clean` and clears `dist/python` once.
- **One core archive** `understand-anything-plugin-<ver>.tar.gz`: the copied/source payload (skills, agents, hooks, `.claude-plugin`, Python source + `run.sh`, dashboard `serve.mjs`). Platform-agnostic, no build output.
- **Separate build-specific archives** (extracted *onto* the payload by the installer):
  - `understand-anything-wheelhouse-<plat>-<ver>.tar.gz` — offline `pip wheel` of both packages + all deps → `packages/arch_analysis/wheelhouse/`. **CPU/OS + Python-version specific** (the wheels are e.g. `cp314 … x86_64`). `run.sh` installs from it with `--no-index`, and **falls back to an online install** if the wheelhouse doesn't match the interpreter.
  - `understand-anything-dashboard-<ver>.tar.gz` — `vite build` static output → `packages/dashboard/dist/`. `launch_dashboard.sh` runs `node serve.mjs` when `dist/` is present, else falls back to `vite` dev. `serve.mjs` is a zero-dep port of the dev-server's token-gated endpoints.
- **`understand-anything_<ver>_<arch>.deb`** (`make deb`, linux_x64/py3.14): bundles the three archives + a per-user linker. Uses dpkg's own mechanisms — `Depends: python3 (>= 3.14~), python3-venv, python3-pip` (+ `Recommends: nodejs`), and a `postinst` that assembles the payload into `/usr/share/understand-anything/understand-anything-plugin` and warms the venv system-wide. It also ships `/usr/share/understand-anything/.claude-plugin/marketplace.json` (copied from the repo root) so the linker's native `claude plugin marketplace add /usr/share/understand-anything` path works. Built with `dpkg-deb --root-owner-group` (no fakeroot needed).

### Native-CLI-first
Both installers **prefer a target's built-in plugin CLI and fall back to the scripted symlink installer**. Two targets have a marketplace-style native install for this plugin:
- **Claude Code** — `claude plugin marketplace add <marketplace-root>` + `claude plugin install understand-anything@understand-anything --scope user|project` (both scopes; verified via `claude plugin list`).
- **Codex** — `codex plugin marketplace add <marketplace-root>` + `codex plugin add understand-anything@understand-anything` (verified via `codex plugin list`). Codex's marketplace install is **global-only** (no per-project scope), so a `--local` codex install falls back to the scripted path.

On any failure the installer falls back. **opencode** is intentionally *not* native: `opencode plugin <module>` installs an npm module, not SKILL.md skills, so opencode (like `agents`, `vscode`, `jetbrains`, `kilo`, `kiro`, `cursor`) is a filesystem skill-drop. `UA_NO_NATIVE=1` forces the scripted path everywhere. The marketplace root is the dir holding `.claude-plugin/marketplace.json` (repo root in a checkout; `/usr/share/understand-anything` for the deb, which ships that manifest).

### Install scripts (two, by design)
- **`install.sh`** (repo root) — standalone installer for source/tarball users. Finds the archives (next to it, `$UA_ASSET_DIR`, `dist/`, or `/usr/share/...`) and **assembles** them (else falls back to `git` via `UA_REPO_URL`), checks prerequisites, tries the native CLI, else links skills per platform, symlinks `~/.understand-anything-plugin`, writes the Kiro agent config, and warms the venv. Modes: `install.sh <platform> [--local <PATH>]`, `--uninstall <platform> [--local <PATH>]`, `--assemble <dir>`, `--update`. `--local <PATH>` is a per-platform **flag** (required for `cursor`, optional for the rest); there is no separate `local` subcommand. Platform layout tables live here.
- **`packaging/deb/understand-anything`** — the deb's slim per-user linker (installed to `/usr/bin/understand-anything`). Same `<platform> [--local <PATH>]` interface and native-CLI-first behavior, but does **only** per-user linking/native-install against the system payload; assembly, prerequisites, and env-warming are handled by the deb's `postinst`/`Depends`, so it deliberately omits them.

Platform set (kept in sync between both scripts, `install.sh`, and the Makefile's `INSTALL_PLATFORMS`): `claude` (native `claude plugin`; scripted fallback → `~/.claude/skills`), `codex` (native `codex plugin`, global-only; scripted fallback → `~/.agents/skills`), `opencode` (scripted → `~/.agents/skills`), `agents` (cross-client `~/.agents/skills`: VSCodium/…), `vscode` (Copilot → `~/.copilot/skills`), `jetbrains` (Junie → `~/.junie/skills`), `kilo`, `kiro`; all support an optional `--local <PATH>`, and `cursor` is project-only (`--local` required → `.cursor/skills`). Note: the Zed IDE is **not** a target — it reads AGENTS.md/`.rules` (worktree root or `~/.config/zed/AGENTS.md`), not a skills drop.

## Scripts
- `understand-anything-plugin/packages/dashboard/scripts/generate-large-graph.mjs` — Generates a fake knowledge graph for performance testing. Writes to `.understand-anything/knowledge-graph.json`. Usage: `node scripts/generate-large-graph.mjs [nodeCount]` (default: 3000 nodes). Not part of the production pipeline.

## Versioning
When pushing to remote, bump the version in **all five** of these files (keep them in sync):
- `understand-anything-plugin/package.json` → `"version"` field
- `understand-anything-plugin/.claude-plugin/plugin.json` → `"version"` field
- `.claude-plugin/plugin.json` → `"version"` field
- `.cursor-plugin/plugin.json` → `"version"` field
- `.copilot-plugin/plugin.json` → `"version"` field

Note: `.claude-plugin/marketplace.json` does **not** carry a version — the `plugins[]` entry only supports `name` and `source`, and adding other fields causes marketplace schema validation failures.

## Testing Local Plugin Changes

Claude Code caches installed plugins at `~/.claude/plugins/cache/understand-anything/understand-anything/<version>/`. Symlinks don't work because Claude's Search/Glob tools can't follow them. To test local changes:

1. **Build/install the packages** (the Python packages have no build step — install deps; the dashboard builds with Vite):
   ```bash
   make deps
   make build   # dashboard only
   ```

2. **Find the installed version** (must match what the marketplace currently serves):
   ```bash
   ls ~/.claude/plugins/cache/understand-anything/understand-anything/
   ```

3. **Copy your local plugin into the cache**, replacing `<VERSION>` with the version from step 2:
   ```bash
   rm -rf ~/.claude/plugins/cache/understand-anything/understand-anything/<VERSION>
   cp -R ./understand-anything-plugin ~/.claude/plugins/cache/understand-anything/understand-anything/<VERSION>
   ```

4. **Start a fresh Claude Code session** (existing sessions cache the old prompts in context).

5. **Run `/understand --full`** in the target project to verify.

**Re-sync after further changes:**
```bash
cp -R ./understand-anything-plugin/* ~/.claude/plugins/cache/understand-anything/understand-anything/<VERSION>/
```

**To revert to upstream:** Uninstall and reinstall the plugin from the marketplace — it repopulates the cache from the upstream repo.
