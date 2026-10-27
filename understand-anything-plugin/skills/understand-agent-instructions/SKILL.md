---
name: understand-agent-instructions
description: Print or integrate project agent instructions for efficient Understand Anything graph exploration, scoped retrieval, and context reuse. Use when recommending agent guidance or adding it as a separate section in a project's AGENTS.md.
---

# Understand Anything agent instructions

Use this workflow to give an agent practical guidance for exploring a codebase
with less repeated retrieval. It prints instructions by default; when the user
asks to integrate them, it adds or updates a separate section in `AGENTS.md`.
It does not index the project, load graphs, install dependencies, or run queries.

Read [host integration](../../HOSTS.md) for invocation and root resolution.
Resolve `SKILL_DIR` from this file, following symlinks; keep `PLUGIN_ROOT` and
the user's `PROJECT_ROOT` distinct. Use the requested project or current directory.

## Print recommended instructions

```bash
python3 "$SKILL_DIR/scripts/agent_instructions.py" "$PROJECT_ROOT"
```

Present the printed [instruction section](assets/agent-instructions.md) as
copyable Markdown. It covers skill selection, query tools, partition discovery,
freshness, boundary stubs, current-source verification, and reuse of loaded context.
Translate skill invocations for the active host when explaining the examples.
The section is portable and does not embed this installation's absolute paths.

## Integrate into AGENTS.md

When the user requests integration or supplies `--write`, read the existing
`AGENTS.md` for conflicting project preferences, then run:

```bash
python3 "$SKILL_DIR/scripts/agent_instructions.py" "$PROJECT_ROOT" --write
```

The helper creates `AGENTS.md` if absent, appends a marked section if absent,
or replaces only that marked section. Repeated writes are idempotent. It leaves
other sections and unmarked existing guidance intact. If an older unmarked
Understand Anything section duplicates or conflicts with the recommendation,
merge it deliberately within the user's requested scope instead of adding
contradictory instructions. Preserve explicit skill exclusions and project rules.

Report the destination and whether instructions were printed or written. A help
request alone prints guidance; it does not authorize editing a project file.
