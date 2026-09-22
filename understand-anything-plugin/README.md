# Understand Anything plugin

Build a codebase knowledge graph with Claude Code or Codex, then query, explain,
compare, or visualize it. Both hosts use the same `skills/`, Python engine,
and graph files.

## Installation

Use `./install.sh claude` or `./install.sh codex` from the repository root.
The installer generates the correct marketplace format for each host. Native
installation loads plugin skills and hooks; standalone skill fallback does not
load hooks. Start a new session after installing or updating.

For Claude development without installing, launch from the codebase you want
to analyze:

```bash
claude --plugin-dir /absolute/path/to/understand-anything-plugin
```

In Claude native installations, skills use `/understand-anything:<skill-name>`.
Standalone Claude skills use `/<skill-name>`. In Codex, choose the skill with
`$<skill-name>` or the skill picker. Use the host's displayed qualified name if
there is a naming collision.

## Skills

| Skill | Purpose |
|---|---|
| `understand` | Analyze the project, selected folder parts, or changed parts |
| `load-graph` | Load selected part graphs or the full merged graph |
| `understand-add-part` | Add an excluded or newly discovered folder part |
| `understand-merge` | Recombine saved partitions without reanalysis |
| `understand-chat` | Answer questions using graph context and current source |
| `understand-explain` | Explain a file, function, or module |
| `understand-diff` | Describe changed and affected components |
| `understand-onboard` | Draft an onboarding guide |
| `understand-dashboard` | Launch the dashboard and report its tokenized URL |
| `understand-language` | Load one language analysis reference |
| `understand-framework` | Load one framework analysis reference |

Analysis supports a target path and `--source=<dir>[,<dir>]`, `--split=<depth>`,
`--all`, `--full`, `--review`, `--no-domain`, and
`--auto-update` / `--no-auto-update`. It saves the partition selection in
`.understand-anything/config.json`. `--all` selects all detected parts; ignore
review still applies when needed.

## Runtime and artifacts

Python 3.14+ is required for the deterministic pipeline. Source installs use PDM;
packaged installs use a bundled requirements file with pip/venv. Invoke modules
through `packages/core/run.sh <module> …`, which preserves the caller's working
directory. Use absolute paths when analyzing another project.

Artifacts belong to the requested project or worktree:

- `knowledge-graph.json`: merged structural graph.
- `partitions/*.knowledge-graph.json`: saved part graphs.
- `domain-graph.json`: optional business-domain view.
- `fingerprints.json` and `meta.json`: incremental-analysis baseline.
- `intermediate/`: scan, validation reports, and working outputs.

A graph is a snapshot. Check source when answering questions about current
behavior. A failed required analysis step keeps intermediate evidence and should
not advance the saved baseline.

The dashboard requires Node.js 22+. Source mode additionally requires pnpm;
prebuilt bundles use `packages/dashboard/serve.mjs`. The launcher reports a
loopback URL with an access token. Open the full URL, including `?token=`.
Analysis does not launch the dashboard automatically.

## Optional auto-update

Enable with the analysis skill's `--auto-update` flag. Native hooks compare the
stored commit with HEAD at session start and after shell tools. The hook reads
local state and supplies a workflow reminder; the host performs the update.
In Codex, review and trust the hook definition before expecting it to run.

Part-based graphs refresh affected partitions and merge them again. Legacy
graphs use the fingerprint workflow in `hooks/auto-update-prompt.md`.
Standalone skill installs require explicit analysis runs because they do not
register hooks.

## Troubleshooting and maintenance

- Missing skill: start a new session and check `claude plugin list` or
  `codex plugin list --json`; confirm you installed for the intended scope.
- Missing auto-update: verify native installation, hook trust, and the boolean
  `autoUpdate` setting.
- Python startup failure: check Python/PDM or packaged pip/venv requirements.
  Dependency installation needs a writable plugin environment. Cached source
  installs create their own environment rather than reuse the original
  checkout's `.pdm-python` path. Failed environments are retained under
  `packages/core/.venv-recovery.*` for diagnosis.
- Dashboard startup failure: use the printed log path and check Node/pnpm.
- Native installer failure: the installer reports fallback to standalone skills;
  inspect the preceding host CLI error before assuming native hooks are active.

[Core reference](packages/core/README.md) documents the Python package.
[Command reference](tools/README.md) describes deterministic command wrappers.
[Host integration](HOSTS.md) documents invocation and agent dispatch conventions.

The compatibility manifests are `.claude-plugin/plugin.json` and
`.codex-plugin/plugin.json`. Shared hooks live at `hooks/hooks.json`.
Validate changes with `claude plugin validate /path/to/plugin` and the repository's
integration tests. Keep manifest versions aligned when preparing a release.
