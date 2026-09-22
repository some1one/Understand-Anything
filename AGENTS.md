# Understand Anything

The plugin source is `understand-anything-plugin/`; do not edit installed copies
under `.agents/understand-anything-plugin/` when changing the source.

Skills are in `understand-anything-plugin/skills/`. The deterministic pipeline
runs through `understand-anything-plugin/packages/core/run.sh <module> …`.
Read [plugin guidance](understand-anything-plugin/AGENTS.md) for plugin changes.

Each package owns its configuration. Do not add a root `package.json`,
`pyproject.toml`, or pnpm workspace. Preserve existing worktree changes.

Use `make help` for explicit targets; bare `make` builds distribution artifacts.
Run core tests with `make test-core` and integration checks with
`understand-anything-plugin/packages/core/.venv/bin/python -m pytest scripts/tests -q`.
