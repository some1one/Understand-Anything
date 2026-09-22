# Understand Anything

Analyze a codebase into a local knowledge graph, ask questions about its components,
and explore its architecture in an interactive dashboard. The plugin supports
Claude Code and Codex through shared skills and host-specific manifests.

## Install and use

From this checkout on Linux or macOS:

```bash
./install.sh claude
# Or:
./install.sh codex
```

The installer prefers the host's native plugin CLI. It creates an installer-owned
local marketplace under `~/.understand-anything/marketplace` (override the parent
with `UA_DIR`). If native installation is unavailable or fails, it installs
standalone skills and reports that hooks are unavailable. Set `UA_NO_NATIVE=1`
to choose skills-only installation explicitly.

For a project-local skills installation:

```bash
./install.sh codex --local /absolute/path/to/project
```

Claude supports native project scope; Codex uses standalone project skills for
`--local`. Standalone skills share the bundled workflows, but do not register
native hooks or named plugin agents.

Start a new host session after installation. In Claude Code, run
`/understand-anything:understand`; in Codex, select `$understand`.
Then use the dashboard skill to open the generated graph. See the
[plugin guide](understand-anything-plugin/README.md) for all skills, options,
hook behavior, and troubleshooting.

## Requirements

- Python 3.14 or newer. Source checkouts use PDM to install the core environment.
  Packaged distributions use Python's `venv` and `pip`.
- Git for commit-based incremental updates.
- Node.js 22 or newer for the dashboard. Source dashboard development also uses
  pnpm 10.6.2, pinned in its `package.json`; prebuilt dashboards need only Node.

The analysis model is provided by the host. Graph artifacts are saved under the
analyzed project's `.understand-anything/` directory. Source content and summaries
are processed by the host model; see the host's settings for its data handling.

## Development

There is no root Python or Node project. Each package owns its dependencies.

```bash
make help
make deps
make test-core
make test-dashboard
make lint
```

Integration regression checks run with the core environment:

```bash
understand-anything-plugin/packages/core/.venv/bin/python -m pytest scripts/tests -q
```

`make build` builds the dashboard. `make package` creates source, Python wheel,
wheelhouse, and dashboard archives in `dist/`; `make deb` builds the Debian
package. The default Make target is `package`, so use an explicit target when
you only want tests or help.

## Layout

- [Plugin](understand-anything-plugin/README.md): manifests, skills, agents, hooks,
  deterministic commands, and packages.
- [Core](understand-anything-plugin/packages/core/README.md): Python analysis,
  graph contracts, persistence, search, and context builders.
- `understand-anything-plugin/packages/dashboard/`: React/TypeScript dashboard
  and its standalone Node server.
- `install.sh`, `scripts/build_dist.py`, and `packaging/deb/`: installation and
  distribution.
- [Agent guidance](AGENTS.md): repository conventions for coding agents.
