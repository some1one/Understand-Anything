---
name: load-graph
description: Load the knowledge graph into context — either the full merged graph or only selected parts, to keep prompt size small when the whole repo isn't needed
argument-hint: "[--all | <part>[,<part>...]]"
---

# /load-graph

Load a codebase's knowledge graph into context for follow-up questions. Analysis
with `/understand` produces per-part graphs under
`.understand-anything/partitions/` plus a merged `knowledge-graph.json`. This
skill loads either:

- **selected parts** — a smaller, focused slice (cheaper context), or
- **the full merged graph** (`--all`).

## Graph Structure Reference

- `project` — {name, description, languages, frameworks}
- `nodes[]` — {id, type, name, filePath?, summary, tags[], complexity}. `stub:true` nodes are **external references** — a real node defined in a part you did not load.
- `edges[]` — {source, target, type, direction, weight}
- `layers[]` — {id, name, description, nodeIds[]}

Read [host integration](../../HOSTS.md) for invocation, argument handling, and agent dispatch.

## Instructions

1. Set `SKILL_DIR` to the directory containing this `SKILL.md`.

2. Run the loader. The argument selects the scope:
   - `--all` → the full merged graph
   - `frontend,api` (comma-separated part names) → only those parts
   - nothing → the parts in `config.includedParts`
   ```bash
   python3 "$SKILL_DIR/scripts/load_graph.py" "$PWD" "$ARGUMENTS"
   ```
   Part names match the folder-parts shown by `/understand` (e.g. `src`, `src/api`, `packages/web`).

3. Use the printed graph as context for the user's questions:
   - Reference specific files, functions, and relationships from the loaded scope.
   - A `(external)` node means the relationship crosses into a part you did not load — offer to `/load-graph <that-part>` (or `--all`) if the user needs it.
   - If a requested part has no graph, say so and suggest `/understand` or `/understand-add-part <dir>`.
