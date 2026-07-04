# tools/ — scriptable commands for agents

Thin, deterministic **commands** an AI agent (or a human) can run directly —
without executing a full prompted skill (`SKILL.md`). Each command wraps
existing project scripts (the `arch_analysis` pipeline via
`packages/arch_analysis/run.sh`, or a standalone skill helper) behind a single
`run.sh` with a stable interface.

Use a command when you need one deterministic step that produces or updates a
**completed** artifact in `.understand-anything/` — the same files the skills
write — rather than the multi-phase LLM workflow a skill orchestrates. No
subagents are dispatched; these are pure scripts.

Every command here runs to a finished result on its own. Steps that only
produce LLM *input* (scanning, domain context, graph queries) are intentionally
**not** exposed as tools — without the model they can't complete their use case,
so they live only inside the skills.

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

On first use the `arch_analysis` virtualenv is created automatically (the shared
launcher handles it), so the first command may take a moment.

## Available commands

| Command | Wraps | Canonical file it writes |
|---------|-------|--------------------------|
| `generate-ignore` | `arch_analysis.generate_ignore` | `.understand-anything/.understandignore` |
| `merge-subdomains` | `arch_analysis.merge_subdomain_graphs` | `.understand-anything/knowledge-graph.json` (merged) |
| `validate-graph` | `arch_analysis.validate_graph` | `.understand-anything/intermediate/review.json` |

Run any command with no arguments to see its usage.

## Project/local installs — callable wrappers

Any **project-local** install (`install.sh <platform> --local <dir>`, and the
deb linker's project path) drops a callable bash wrapper per command under
`<project>/.understand-anything/tools/<command>`. Each wrapper self-resolves to
the copied plugin payload's `run.sh` (so it survives the project moving) and
forwards its arguments:

```bash
.understand-anything/tools/generate-ignore .
.understand-anything/tools/merge-subdomains .
.understand-anything/tools/validate-graph .
```

This is platform-agnostic — every `--local` target gets the wrappers. Global
installs do not (there's no single project dir to place them in). Uninstall
removes only the wrappers it generated.

## Kilo workflows

Each command ships a `kilo-workflow.md` alongside its `run.sh`. **Only** the
`kilo` install target consumes these: `install.sh kilo` (and the deb linker)
generate `/understand-<command>` workflows into `.kilocode/workflows/` (project)
or `~/.kilocode/workflows/` (global), baking in the plugin's absolute path.
Every other install target ignores `tools/` — on those, agents invoke the
`run.sh` scripts directly via their built-in shell/bash tool.
