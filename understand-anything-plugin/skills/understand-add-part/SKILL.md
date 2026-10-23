---
name: understand-add-part
description: Add a folder as a new part to an existing analysis — analyze just that part and fold it into the merged knowledge graph
argument-hint: "<dir>"
---

# /understand-add-part

Resolve `UA_DIR` after resolving `PLUGIN_ROOT` and `PROJECT_ROOT`, before reading
or writing project artifacts:

```bash
UA_DIR=$(python3 "$PLUGIN_ROOT/scripts/data_directory.py" "$PROJECT_ROOT")
```

Use this absolute directory throughout the workflow and pass it to workers.
It selects `.ua` for new projects and retains an existing legacy directory;
see [host integration](../../HOSTS.md) for the selection rules.


Add a directory as a new **part** to an existing `/understand` analysis: analyze
only that part and merge it into the full graph. Use this when a new
folder/module appears, or to bring a previously-excluded part into the selection,
without re-analyzing the whole repo.

Requires a prior `/understand` run (a `$UA_DIR/config.json` with
`sourceFolders` / `splitDepth`). If missing, tell the user to run `/understand`
first.

`$ARGUMENTS` is the folder to add (relative to the project root), e.g. `src/payments`.

Read [host integration](../../HOSTS.md) for invocation, argument handling, and agent dispatch.

## Instructions

1. Set `SKILL_DIR` to the directory containing this `SKILL.md`. Check the Rust engine:
   ```bash
   PLUGIN_ROOT="$("$SKILL_DIR/../understand/scripts/ensure_rust_engine.sh")"
   UNDERSTAND_DIR="$SKILL_DIR/../understand"
   ```
   Confirm `$UA_DIR/config.json` exists with `sourceFolders`/`splitDepth`; if not, stop and instruct the user to run `/understand`.

2. **Refresh the scan** so the new folder's files are known — run **`/understand` Phase 1 (SCAN)**: dispatch the `project-scanner` agent exactly as that phase describes, refreshing `intermediate/scan-result.json`. (Use the resolved project root and `git -C "$PROJECT_ROOT" rev-parse HEAD`.)

3. **Partition and select the new part.** Re-partition with the saved source/depth (no flags → `partition_files` reads none, so pass the saved values from `config.json`):
   ```bash
   "$PLUGIN_ROOT/packages/rust/run.sh" partition_files "$PWD" [--source=<saved>] [--depth=<saved>]
   ```
   From `intermediate/partitions.json`, take the part key(s) equal to `$ARGUMENTS` or starting with `$ARGUMENTS/`. Add them to the selection (existing `includedParts` + new):
   ```bash
   "$PLUGIN_ROOT/packages/rust/run.sh" write_config "$PWD" --parts=<existing + new parts>
   ```
   If `$ARGUMENTS` matches no files, report that and stop.

4. **Analyze the new part(s).** For each new part, run **`/understand` Phase 2 steps 1–4** (compute_batches `--changed-files=intermediate/part-files/<part>.json` → dispatch `file-analyzer` agents → `merge_batch_graphs` → `assemble_part_graph "$PWD" "<part>" "<commit hash>"`).

5. **Merge + finalize.** Recombine all included parts and re-run architecture so the new nodes get layers:
   ```bash
   "$PLUGIN_ROOT/packages/rust/run.sh" merge_parts "$PWD"
   ```
   Then run **`/understand` Phases 3–7** (architecture on the merged set, review, save) to write `knowledge-graph.json`, fingerprints, and `meta.json`.

6. Report the added part(s) and new totals; suggest `/understand-dashboard`.
