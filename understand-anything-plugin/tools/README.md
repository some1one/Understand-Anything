# tools/ — scriptable commands for agents

Thin, deterministic **commands** an AI agent (or human) can run directly, without
executing a full prompted skill (`SKILL.md`). Each wraps existing project scripts
(the `arch_analysis` pipeline via `packages/arch_analysis/run.sh`, or a skill
helper) behind a single `run.sh` with a stable interface.

Use a command for one deterministic step that produces or updates a **completed**
artifact in `.understand-anything/` — the same files the skills write — rather
than a multi-phase LLM workflow. No subagents; pure scripts. Steps that only
produce LLM *input* (scanning, domain context, graph queries) are intentionally
**not** exposed as tools — they live only inside the skills.

## Layout

```
tools/commands/<command>/run.sh     # the entrypoint (self-locating)
tools/commands/<command>/README.md  # usage + what it wraps
```

Every `run.sh` self-locates the plugin root from its own path (symlink-safe via
`pwd -P`), so it can be invoked with an absolute or relative path from anywhere:

```bash
understand-anything-plugin/tools/commands/scan/run.sh /path/to/project /tmp/scan.json
```

On first use the `arch_analysis` virtualenv is created automatically, so the
first command may take a moment.

## Available commands

| Command | Wraps | Canonical file it writes |
|---------|-------|--------------------------|
| `generate-ignore` | `arch_analysis.generate_ignore` | `.understand-anything/.understandignore` |
| `merge-subdomains` | `arch_analysis.merge_subdomain_graphs` | `.understand-anything/knowledge-graph.json` (merged) |
| `validate-graph` | `arch_analysis.validate_graph` | `.understand-anything/intermediate/review.json` |

Run any command with no arguments to see its usage.

## Project/local installs — callable wrappers

Any **project-local** install (`install.sh <platform> --local <dir>`, and the deb
linker's project path) drops a callable bash wrapper per command under
`<project>/.understand-anything/tools/<command>`. Each wrapper self-resolves to
the copied payload's `run.sh` (surviving project moves) and forwards its args:

```bash
.understand-anything/tools/generate-ignore .
.understand-anything/tools/merge-subdomains .
.understand-anything/tools/validate-graph .
```

Platform-agnostic — every `--local` target gets the wrappers; global installs do
not (no single project dir). Uninstall removes only the wrappers it generated.

## Kilo workflows

Each command ships a `kilo-workflow.md` alongside its `run.sh`. **Only** the
`kilo` install target consumes these: `install.sh kilo` (and the deb linker)
generate `/understand-<command>` workflows into `.kilocode/workflows/` (project)
or `~/.kilocode/workflows/` (global), baking in the plugin's absolute path. Every
other target ignores `tools/` — agents invoke the `run.sh` scripts directly via
their built-in bash tool.
