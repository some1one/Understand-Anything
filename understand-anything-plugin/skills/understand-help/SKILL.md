---
name: understand-help
description: Explain Understand Anything installation, first-run repository setup, prerequisites, configuration, recommended repository agent instructions, skill selection, and troubleshooting. Use for getting started after installing the plugin or skills, asking how to use them, or choosing a workflow. For a guide to the analyzed codebase itself, use understand-onboard.
---

# Understand Anything help

Resolve `UA_DIR` after resolving `PLUGIN_ROOT` and `PROJECT_ROOT`, before reading
or writing project artifacts:

```bash
UA_DIR=$(python3 "$PLUGIN_ROOT/scripts/data_directory.py" "$PROJECT_ROOT")
```

Use this absolute directory throughout the workflow and pass it to workers.
It selects `.ua` for new projects and retains an existing legacy directory;
see [host integration](../../HOSTS.md) for the selection rules.


Help the user get from an installed plugin or skill to a usable project graph.
Answer the requested question first; present only the setup steps relevant to their
installation and current project. A help request alone should not start indexing,
launch the dashboard, reinstall the plugin, or download dependencies. When the
user asks to perform setup, carry out the requested setup using the workflows
below; do not require another confirmation for already-authorized work.

Read [host conventions](../../HOSTS.md) and use the invocation style supported by
the current host. Resolve `PLUGIN_ROOT` from this skill's actual location,
following symlinks. Resolve `PROJECT_ROOT` separately from the requested repo or
working directory. Do not analyze the plugin installation instead of the user's
project. If this is a copied standalone skill and sibling scripts/packages are
absent, explain that the complete plugin payload is required; use the installation
guide rather than assuming `PLUGIN_ROOT` is valid.

## Check what is already available

For setup/troubleshooting, inspect relevant local state without changing it:

- Is the installation native or skills-only, and global or project-local? Read
  its manifests and paths; do not infer native hooks merely from skill visibility.
- Does `packages/rust/bin/understand-anything-rs` exist, or is this a source checkout
  with `packages/rust/Cargo.toml`? Packaged installs include the engine. Source
  checkouts need stable Rust/Cargo and may build on first use. `run.sh --version`
  can trigger a build, so do not describe that command as a read-only check.
- Python 3 is needed by installation and workflow helpers. Git enables
  commit-based incremental updates. Node.js 22+ is needed only for the dashboard;
  a source dashboard also needs the pnpm version in its `package.json`.
- Is dictionary configuration present at `packages/rust/dictionary-config.json`,
  `UA_DICTIONARY_CONFIG`, or the user config location described in
  [dictionary setup](../../scripts/dictionaries.md)? Check paths without importing
  installed packages. No dictionary files ship in distribution bundles.
- Does the target project have `$UA_DIR/knowledge-graph.json`,
  `meta.json`, or `config.json`? Their absence is normal before the first analysis.
  Do not create an empty graph or delete existing artifacts as a setup shortcut.

## Installation and first run

If the skill is already visible and its payload is complete, continue with setup;
reinstallation is unnecessary. For missing/incomplete installations or another
host/scope, consult the [plugin installation guide](../../README.md). In a source
checkout, run `./install.sh <host>` from the checkout root, or append
`--local /absolute/path/to/project` for project scope. Do not assume `install.sh`
exists inside an installed plugin. A Debian installation uses the installed
`understand-anything <host>` command. Native host-manager installs may bypass
installer setup, so skill visibility alone does not prove dictionaries are ready.
Start a new host session after installing/updating to refresh skill discovery.

When dictionary setup is needed, inspect without changing anything:

```bash
python3 "$PLUGIN_ROOT/scripts/configure_dictionaries.py" --plugin-root "$PLUGIN_ROOT" --project-root "$PROJECT_ROOT" --inspect
```

If all required system dictionaries are installed, use them without a storage
question. If components are missing and `snapshot` is unset, recommend a shared
OS directory and prompt for **shared storage** or **local repo storage**. Explain
that shared storage avoids duplicate full datasets; repo storage uses the target
project's ignored `$UA_DIR/dictionaries/` directory. Honor an existing
choice or manually edited `snapshot` path without asking again.

For authorized setup, pass `--storage shared` or
`--storage repo --project-root "$PROJECT_ROOT"` to the configurator. A custom path
uses `--local-dir /absolute/path`. Saved configurations need no storage flag:

```bash
python3 "$PLUGIN_ROOT/scripts/configure_dictionaries.py" --plugin-root "$PLUGIN_ROOT"
```

Terminal setup prompts if a choice is needed; noninteractive setup stops before
downloading until a choice is supplied. The config records the absolute `snapshot`
path for advanced users to edit manually. Shared data uses the OS's user cache
location; project graphs and filtered query caches always stay with the project.
See [storage locations](../../scripts/dictionaries.md#share-downloads-across-projects).

Setup prefers compatible system data and fetches missing components into the
chosen location. `--offline` records configuration without fetching or checking
upstream versions; missing data is not made ready by this option. `--inspect`
only reports state. Report outdated system-package advice without upgrading those
packages automatically. Use [dictionary maintenance](../understand-update/SKILL.md)
for updates or repairs. Runtime indexing and queries remain offline.

For the first analysis, use [understand](../understand/SKILL.md) with the target
project path. Examples below use standalone slash shorthand; translate them for
the host using HOSTS.md (`/understand-anything:understand` for native Claude,
`$understand` for Codex).

```text
/understand /absolute/path/to/project
/understand /absolute/path/to/project --source=src --split=1
```

Explain that the workflow reviews ignore rules and selects folder parts before
analysis. `--all` selects every detected part, while `--full` rebuilds the selected
parts from scratch. Existing selection is saved in
`$UA_DIR/config.json`; normal later runs update changed parts.
For temporary extra exclusions, show `/understand --exclude='docs/,e2e/,!e2e/keep.ts'`.
These gitignore patterns have highest priority. Changing or omitting them on the
next explicit analysis refreshes all included parts, even without new commits.
Auto-update retains the last published scope; permanent rules belong in
`.uaignore`. Negation can restore an enumerated file, but cannot make
Git-ignored untracked files appear in the inventory.

Recommend `/understand /absolute/path/to/project --full` after plugin or dictionary
library updates. A recommendation does not start that rebuild automatically.

The graph, part graphs, metadata and working artifacts live under the target
project's `$UA_DIR/`. Analysis uses the host's model and its data
handling settings. The dashboard is launched separately after a graph exists.

## Choose the next skill

| User intent | Workflow |
|---|---|
| Print or integrate efficient agent instructions | [understand-agent-instructions](../understand-agent-instructions/SKILL.md) |
| Create, refresh or fully rebuild an index | [understand](../understand/SKILL.md) |
| Ask a question using the graph | [understand-chat](../understand-chat/SKILL.md) |
| Explain a file, function or module | [understand-explain](../understand-explain/SKILL.md) |
| Understand a diff and affected components | [understand-diff](../understand-diff/SKILL.md) |
| Create a guide for newcomers to the codebase | [understand-onboard](../understand-onboard/SKILL.md) |
| Open the graph dashboard | [understand-dashboard](../understand-dashboard/SKILL.md) |
| Load selected graph context | [load-graph](../load-graph/SKILL.md) |
| Include an additional folder part | [understand-add-part](../understand-add-part/SKILL.md) |
| Recombine saved graphs without analysis | [understand-merge](../understand-merge/SKILL.md) |
| Configure, update or repair dictionary dependencies | [understand-update](../understand-update/SKILL.md) |

`understand-language` and `understand-framework` supply analysis references; they
are normally loaded by the analysis workflow, not first-run setup commands.

## Recommend repository agent instructions

For general help (including a bare help invocation) or a request for agent
usage guidance, print the shared recommended instruction section as copyable
Markdown after answering the immediate question:

```bash
python3 "$PLUGIN_ROOT/skills/understand-agent-instructions/scripts/agent_instructions.py" "$PROJECT_ROOT"
```

Use [understand-agent-instructions](../understand-agent-instructions/SKILL.md)
when the user asks to integrate it into the project's `AGENTS.md`; its `--write`
mode creates or updates a separate marked section and preserves other content.
Read existing instructions first and honor project-specific preferences. A help
request alone does not authorize editing. For focused troubleshooting unrelated
to agent guidance, link to this skill instead of printing the entire section.
The [template](../understand-agent-instructions/assets/agent-instructions.md)
is the single source of the recommended instructions; do not substitute a
full-graph-by-default recipe or omit its context-reuse and freshness guidance.

## Common setup issues

- **Skill missing:** verify installation scope and restart the host session.
  Use the host-displayed qualified name when another skill has the same name.
- **No graph yet:** run `understand` for the intended project before graph-based
  queries or dashboard use. Preserve any existing graph when troubleshooting.
- **Dictionary access failure:** relay the error's config path and repair commands.
  The user can update system paths with `--lemma-resources`/`--cspell-root`, or use
  `--prefer-local --local-dir` to download data into a shared user cache or an
  explicitly chosen, ignored installation-local directory. Use the
  maintenance workflow; do not silently download while answering a graph query.
- **Auto-update missing:** native hooks need an enabled boolean `autoUpdate` and,
  in Codex, reviewed/trusted hooks. Skills-only installs use explicit analysis
  runs. Enable with `understand --auto-update`; disable with `--no-auto-update`.
  Hooks suggest graph maintenance; they do not update plugin dependencies.
- **Dashboard unavailable:** use its launcher workflow and reported log. Open the
  complete loopback URL including its access token; do not expose that token in
  shared documentation.

Finish with the concrete next command or workflow appropriate to the user's
state, plus any unresolved prerequisite. Do not claim setup was completed when
only instructions were provided.
