# Understand Anything

The plugin source is `understand-anything-plugin/`; do not edit installed copies
under `.agents/understand-anything-plugin/` when changing the source.

Skills are in `understand-anything-plugin/skills/`. The deterministic pipeline
runs through `understand-anything-plugin/packages/rust/run.sh <command> …`.
Read [plugin guidance](understand-anything-plugin/AGENTS.md) for plugin changes.

Each package owns its configuration. Do not add a root `package.json`,
`pyproject.toml`, or pnpm workspace. Preserve existing worktree changes.

Use `make help` for explicit targets; bare `make` builds distribution artifacts.
Run engine tests with `make test-core` and integration checks with
`python3 -m pytest scripts/tests -q`.
