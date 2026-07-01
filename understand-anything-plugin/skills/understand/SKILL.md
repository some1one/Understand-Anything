---
name: understand
description: Analyze a codebase to produce an interactive knowledge graph for understanding architecture, components, and relationships
argument-hint: ["[path] [--full|--auto-update|--no-auto-update|--review]"]
---

# /understand

Analyze the current codebase and produce a `knowledge-graph.json` file in `.understand-anything/`. This file powers the interactive dashboard for exploring the project's architecture.

## Options

- `$ARGUMENTS` may contain:
  - `--full` — Force a full rebuild, ignoring any existing graph
  - `--auto-update` — Enable automatic graph updates on commit (writes `autoUpdate: true` to `.understand-anything/config.json`)
  - `--no-auto-update` — Disable automatic graph updates (writes `autoUpdate: false` to `.understand-anything/config.json`)
  - `--review` — Run full LLM graph-reviewer instead of inline deterministic validation
  - A directory path (e.g. `/path/to/repo` or `../other-project`) — Analyze the given directory instead of the current working directory

---

## Progress Reporting

Throughout execution, report progress to the user at each phase transition and during batch processing. This keeps users informed on large codebases where analysis can take a long time.

- **Phase transitions:** At the start of each phase, print a status line:
  > `[Phase N/6] <phase name>...`
  >
  > Example: `[Phase 2/6] Analyzing files (12 batches)...`

- **Batch progress:** During Phase 2, report each batch with its index and total:
  > `Analyzing batch X/N (files: foo.ts, bar.ts, ...)` (list up to 3 filenames, then `...` if more)

- **Phase completion:** When a phase finishes, briefly confirm:
  > `Phase N complete. <one-line summary of result>`
  >
  > Example: `Phase 1 complete. Found 247 files across 3 languages.`

---

## Phase 0 — Pre-flight

Determine whether to run a full analysis or incremental update.

1. **Resolve `PROJECT_ROOT`:**
   - Parse `$ARGUMENTS` for a non-flag token (any argument that does not start with `--`). If found, treat it as the target directory path.
   - Set `SKILL_DIR` to the directory containing this `SKILL.md`.
   - Resolve the path and apply the git-worktree redirect by calling the bundled Bash script:
     ```bash
     PROJECT_ROOT="$("$SKILL_DIR/scripts/resolve_project_root.sh" "<path-or-current-working-directory>")"
     ```
   - Set `UNDERSTAND_NO_WORKTREE_REDIRECT=1` if you intentionally want a per-worktree graph (rare — most users want the redirect).
1.5. **Ensure the plugin is built.** Later phases invoke Node scripts that import `@understand-anything/core`. On a fresh install `packages/core/dist/` does not exist yet — build once.

   Use the bundled Bash script, which resolves symlinked skill installs, locates the plugin root, and builds `@understand-anything/core` if needed:
   ```bash
   PLUGIN_ROOT="$("$SKILL_DIR/scripts/ensure_plugin_built.sh")"
   ```

   If `pnpm` is missing, report to the user: "Install Node.js ≥ 22 and pnpm ≥ 10, then re-run `/understand`."

2. Get the current git commit hash:
   ```bash
   git rev-parse HEAD
   ```
3. Create the intermediate/temp output directories, purge stale trash dirs, and apply `--auto-update` / `--no-auto-update` config flags:
   ```bash
   "$SKILL_DIR/scripts/prepare_workspace.sh" "$PROJECT_ROOT" $ARGUMENTS
   ```

 4. **Check for subdomain knowledge graphs to merge:**
   List all `*knowledge-graph*.json` files in `$PROJECT_ROOT/.understand-anything/` **excluding** `knowledge-graph.json` itself (e.g. `frontend-knowledge-graph.json`, `backend-knowledge-graph.json`). If any subdomain graphs exist, run the merge module from the `arch_analysis` package (run from its project root so dependencies resolve):
   ```bash
   python -m arch_analysis.merge_subdomain_graphs $PROJECT_ROOT
   ```
   The module discovers subdomain graphs, loads the existing `knowledge-graph.json` as a base (if present), and merges everything into `knowledge-graph.json` (deduplicating nodes and edges). Report the merge summary to the user, then continue with the merged graph.

5. Check if `$PROJECT_ROOT/.understand-anything/knowledge-graph.json` exists. If it does, read it.
6. Check if `$PROJECT_ROOT/.understand-anything/meta.json` exists. If it does, read it to get `gitCommitHash`.
7. **Decision logic:**

   | Condition | Action |
   |---|---|
   | `--full` flag in `$ARGUMENTS` | Full analysis (all phases) |
   | No existing graph or meta | Full analysis (all phases) |
   | `--review` flag + existing graph + unchanged commit hash | Skip to Phase 5 (review-only — reuse existing assembled graph) |
   | Existing graph + unchanged commit hash | Ask the user: "The graph is up to date at this commit. Would you like to: **(a)** run a full rebuild (`--full`), **(b)** run the LLM graph reviewer (`--review`), or **(c)** do nothing?" Then follow their choice. If they pick (c), STOP. |
   | Existing graph + changed files | Incremental update (re-analyze changed files only) |

   **Review-only path:** Copy the existing `knowledge-graph.json` to `$PROJECT_ROOT/.understand-anything/intermediate/assembled-graph.json`, then jump directly to Phase 5 step 3.

   For incremental updates, get the changed file list:
   ```bash
   python "$SKILL_DIR/scripts/write_changed_files.py" "$PROJECT_ROOT" "<lastCommitHash>"
   ```
   If the generated `changed-files.txt` is empty, report "Graph is up to date" and STOP.

8. **Collect project context for subagent injection:**
   - Run the bundled Python context capture script. It writes `.understand-anything/intermediate/project-context.json` and prints the same JSON to stdout; use its fields (`readmeContent`, `manifestContent`, `dirTree`, `entryPoint`) as `$README_CONTENT`, `$MANIFEST_CONTENT`, `$DIR_TREE`, and `$ENTRY_POINT`:
     ```bash
     python "$SKILL_DIR/scripts/capture_project_context.py" "$PROJECT_ROOT"
     ```

---

## Phase 0.5 — Ignore Configuration

Set up and verify the `.understandignore` file before scanning.

1. Check if `$PROJECT_ROOT/.understand-anything/.understandignore` exists.
2. **If it does NOT exist**, generate a starter file with the `arch_analysis` module (reads `.gitignore`, deduplicates against built-in defaults, and emits language-grouped test-file suggestions). Run from the `arch_analysis` project root:
     ```bash
     python -m arch_analysis.generate_ignore $PROJECT_ROOT
     ```
   - Report to the user:
     > Generated `.understand-anything/.understandignore` with suggested exclusions based on your project structure. Please review it and uncomment any patterns you'd like to exclude from analysis. When ready, confirm to continue.
   - **Wait for user confirmation before proceeding.**
3. **If it already exists**, report:
   > Found `.understand-anything/.understandignore`. Review it if needed, then confirm to continue.
   - **Wait for user confirmation before proceeding.**
4. After confirmation, proceed to Phase 1.

---

## Phase 1 — SCAN (Full analysis only)

Report to the user: `[Phase 1/6] Scanning project files...`

Dispatch a subagent using the `project-scanner` agent definition (at `agents/project-scanner.md`) and the bundled prompt template `prompts/project-scanner-dispatch.md`.

Fill the template arguments from Phase 0 context:
- `PROJECT_ROOT`
- `README_CONTENT`
- `MANIFEST_CONTENT`

After the subagent completes, read `$PROJECT_ROOT/.understand-anything/intermediate/scan-result.json` to get:
- Project name, description
- Languages, frameworks
- File list with line counts and `fileCategory` per file (`code`, `config`, `docs`, `infra`, `data`, `script`, `markup`)
- Complexity estimate
- Import map (`importMap`): pre-resolved project-internal imports per file (non-code files have empty arrays)

Store `importMap` in memory as `$IMPORT_MAP` for use in Phase 2 batch construction.
Store the file list as `$FILE_LIST` with `fileCategory` metadata for use in Phase 2 batch construction.

**Gate check:** If >100 files, inform the user and suggest scoping with a subdirectory argument. Proceed only if user confirms or add guidance that this may take a while.

If the scan result includes `filteredByIgnore > 0`, report:
> Excluded {filteredByIgnore} files via `.understandignore`.

---

## Phase 1.5 — BATCH

Report: `[Phase 1.5/6] Computing semantic batches...`

Run the batching module (from the `arch_analysis` project root):
```bash
python -m arch_analysis.compute_batches $PROJECT_ROOT
```

Reads `.understand-anything/intermediate/scan-result.json`, writes `.understand-anything/intermediate/batches.json`.

Capture stderr. Append any line starting with `Warning:` to `$PHASE_WARNINGS` for the final report.

If the script exits non-zero, the failure is hard — relay the full stderr to the user as a Phase 1.5 failure. Do not attempt to recover; the script's internal fallback (count-based) already handles recoverable issues. A non-zero exit means a fundamental problem (missing input file, malformed JSON, etc.).

---

## Phase 2 — ANALYZE

### Full analysis path

Load `.understand-anything/intermediate/batches.json` (produced by Phase 1.5). Iterate the `batches[]` array.

Report: `[Phase 2/6] Analyzing files — <totalFiles> files in <totalBatches> batches (up to 5 concurrent)...`

For each batch, dispatch a subagent using the `file-analyzer` agent definition (at `agents/file-analyzer.md`) and the bundled prompt template `prompts/file-analyzer-batch-dispatch.md`. Run up to **5 subagents concurrently**.

Fill the template arguments from `scan-result.json`, `batches.json[i]`, and Phase 0 context:
- `PROJECT_ROOT`
- `PROJECT_NAME`
- `PROJECT_DESCRIPTION`
- `LANGUAGES`
- `BATCH_INDEX`
- `TOTAL_BATCHES`
- `SKILL_DIR`
- `OUTPUT_PATH`
- `BATCH_IMPORT_DATA_JSON`
- `NEIGHBOR_MAP_JSON`
- `BATCH_FILES`

**Output naming is per-batchIndex — no fusion.** If you fuse multiple small batches into a single file-analyzer dispatch for token efficiency, the dispatched agent must STILL write one output file per original `batchIndex` using `batch-<batchIndex>.json` or `batch-<batchIndex>-part-<k>.json`. The merge script's regex (`batch-(\d+)(?:-part-(\d+))?\.json`) silently drops any other naming (e.g., `batch-fused-8-13.json`, `batch-8-13.json`), losing every node and edge in that file. After each dispatch returns, verify each `batchIndex` in the dispatched input has a corresponding `batch-<batchIndex>.json` (or `batch-<batchIndex>-part-*.json`) on disk before proceeding to the next dispatch.

After ALL batches complete, report to the user: `Phase 2 complete. All <totalBatches> batches analyzed.`

Run the merge-and-normalize module from the `arch_analysis` package (run from its project root):
```bash
python -m arch_analysis.merge_batch_graphs $PROJECT_ROOT
```

This module reads all `batch-*.json` files (including `batch-<i>-part-<k>.json` produced by file-analyzers that split their output) from `$PROJECT_ROOT/.understand-anything/intermediate/`, then in one pass:
- Combines all nodes and edges across batches
- Normalizes node IDs (strips double prefixes, project-name prefixes, adds missing prefixes)
- Normalizes complexity values (`low`→`simple`, `medium`→`moderate`, `high`→`complex`, etc.)
- Rewrites edge references to match corrected node IDs
- Deduplicates nodes by ID (keeps last occurrence) and edges by `(source, target, type)`
- Drops dangling edges referencing missing nodes
- Logs all corrections and dropped items to stderr

The merge script also runs a `tested_by` linker that canonicalizes test-coverage edges in two passes. **Pass 1** walks LLM-emitted `tested_by` edges and flips inverted ones in place; semantically broken edges (test↔test, prod↔prod, orphan endpoints) are dropped. **Pass 2** supplements with path-convention pairings. Production nodes that end up sourcing any `tested_by` edge get a `"tested"` tag. All resulting edges run `production → test`.

Output: `$PROJECT_ROOT/.understand-anything/intermediate/assembled-graph.json`

Include the script's warnings in `$PHASE_WARNINGS` for the reviewer.

### Incremental update path

Write the changed-files list (one path per line) to a temp file if Phase 0 has not already done so:
```bash
python "$SKILL_DIR/scripts/write_changed_files.py" "$PROJECT_ROOT" "<lastCommitHash>"
```

Run compute-batches with `--changed-files`:
```bash
python -m arch_analysis.compute_batches $PROJECT_ROOT \
  --changed-files=$PROJECT_ROOT/.understand-anything/tmp/changed-files.txt
```

This produces a `batches.json` that contains only batches with changed files, but neighborMap entries still reference unchanged files (with their full-graph batchIndex) so cross-batch edges remain emittable.

Then dispatch file-analyzer subagents per the same template as the full path.

After batches complete:
1. Write `batch-existing.json` by pruning old nodes/edges for changed files with the bundled Python helper:
   ```bash
   python "$SKILL_DIR/scripts/prune_incremental_batch.py" \
     "$PROJECT_ROOT" \
     "$PROJECT_ROOT/.understand-anything/tmp/changed-files.txt"
   ```
2. Run the same merge module — it will combine `batch-existing.json` with the fresh `batch-*.json` files:
   ```bash
   python -m arch_analysis.merge_batch_graphs $PROJECT_ROOT
   ```

---

## Phase 3 — ASSEMBLE REVIEW

Report to the user: `[Phase 3/6] Reviewing assembled graph...`

Dispatch a subagent using the `assemble-reviewer` agent definition (at `agents/assemble-reviewer.md`) and the bundled prompt template `prompts/assemble-review-dispatch.md`.

Fill the template arguments from Phase 2 output:
- `PROJECT_ROOT`
- `MERGE_REPORT`
- `IMPORT_MAP_JSON`

After the subagent completes, read `$PROJECT_ROOT/.understand-anything/intermediate/assemble-review.json` and add any notes to `$PHASE_WARNINGS`.

---

## Phase 4 — ARCHITECTURE

Report to the user: `[Phase 4/6] Identifying architectural layers...`

**Build the combined prompt template:**
 1. Use the `architecture-analyzer` agent definition (at `agents/architecture-analyzer.md`).
 2. Use the bundled dispatch template `prompts/architecture-analyzer-dispatch.md`.
 3. Use `architecture-template-args.json` from the helper below for language addenda, framework addenda, file nodes, import edges, all edges, directory tree, and previous layer definitions.

Prepare deterministic template arguments first:
```bash
python "$SKILL_DIR/scripts/prepare_architecture_context.py" "$PROJECT_ROOT" "$SKILL_DIR"
```

Fill the architecture dispatch template arguments from `.understand-anything/intermediate/architecture-template-args.json`:
- `PROJECT_ROOT`
- `PROJECT_NAME`
- `PROJECT_DESCRIPTION`
- `FRAMEWORKS`
- `DIR_TREE`
- `LANGUAGE_CONTEXT`
- `FRAMEWORK_CONTEXT`
- `FILE_NODES_JSON`
- `IMPORT_EDGES_JSON`
- `ALL_EDGES_JSON`
- `PREVIOUS_LAYERS_JSON`

After the subagent completes, normalize `$PROJECT_ROOT/.understand-anything/intermediate/layers.json` with the bundled deterministic helper:
```bash
python "$SKILL_DIR/scripts/normalize_layers.py" "$PROJECT_ROOT"
```

**For incremental updates:** Always re-run architecture analysis on the full merged node set, since layer assignments may shift when files change.

**Context for incremental updates:** When re-running architecture analysis, pass previous layer definitions through the template's `PREVIOUS_LAYERS_JSON` argument for naming consistency.

---

## Phase 5 — REVIEW

Report to the user: `[Phase 5/6] Validating knowledge graph...`

Assemble the full KnowledgeGraph JSON object:

```json
{
  "version": "1.0.0",
  "project": {
    "name": "<projectName>",
    "languages": ["<languages>"],
    "frameworks": ["<frameworks>"],
    "description": "<projectDescription>",
    "analyzedAt": "<ISO 8601 timestamp>",
    "gitCommitHash": "<commit hash from Phase 0>"
  },
  "nodes": [<all nodes from assembled-graph.json after Phase 3 review>],
  "edges": [<all edges from assembled-graph.json after Phase 3 review>],
  "layers": [<layers from Phase 4>]
}
```

1. Assemble the full KnowledgeGraph object from `scan-result.json`, the reviewed `assembled-graph.json` nodes/edges, normalized `layers.json`, and the current commit hash:
   ```bash
   python "$SKILL_DIR/scripts/assemble_knowledge_graph.py" "$PROJECT_ROOT" "<commit hash from Phase 0>"
   ```

2. **Check `$ARGUMENTS` for `--review` flag.** Then run the appropriate validation path:

---

#### Default path (no `--review`): deterministic validation

Run the `arch_analysis` graph validator (from the `arch_analysis` project root). It performs the full referential-integrity, completeness, layer-coverage, uniqueness, and quality checks; with `--scan-result` it also cross-checks scan coverage (every scanned file has a node; no node references an unscanned file). It writes the review payload (`scriptCompleted`, `issues`, `warnings`, `stats`):

```bash
python -m arch_analysis.validate_graph \
  "$PROJECT_ROOT/.understand-anything/intermediate/assembled-graph.json" \
  "$PROJECT_ROOT/.understand-anything/intermediate/review.json" \
  --scan-result "$PROJECT_ROOT/.understand-anything/intermediate/scan-result.json"
```

If the module exits non-zero, read stderr to diagnose (almost always an unreadable or malformed graph file), then retry once. Read `review.json`: the graph is approved when `issues` is empty (warnings are acceptable).

---

#### `--review` path: full LLM reviewer

If `--review` IS in `$ARGUMENTS`, dispatch the LLM graph-reviewer subagent as follows:

Dispatch a subagent using the `graph-reviewer` agent definition (at `agents/graph-reviewer.md`) and the bundled prompt template `prompts/graph-reviewer-dispatch.md`.

Fill the template arguments from scan output and accumulated phase warnings:
- `PROJECT_ROOT`
- `SCAN_FILE_LIST_JSON`
- `PHASE_WARNINGS`

---

3. Read `$PROJECT_ROOT/.understand-anything/intermediate/review.json`.

4. **If `issues` array is non-empty:**
   - Review the `issues` list
   - Apply deterministic fixes where possible:
     ```bash
     python "$SKILL_DIR/scripts/apply_review_fixes.py" "$PROJECT_ROOT"
     ```
   - Re-run the final graph validation after automated fixes
   - If critical issues remain after one fix attempt, save the graph anyway but include the warnings in the final report and mark dashboard auto-launch as skipped

5. **If `issues` array is empty:** Proceed to Phase 6.

---

## Phase 6 — SAVE

Report to the user: `[Phase 6/6] Saving knowledge graph...`

1. Save the final knowledge graph and emit deterministic summary counts:
   ```bash
   python "$SKILL_DIR/scripts/save_knowledge_graph.py" "$PROJECT_ROOT"
   ```
   The helper writes `$PROJECT_ROOT/.understand-anything/knowledge-graph.json` and `$PROJECT_ROOT/.understand-anything/intermediate/save-summary.json`.

2. **Generate structural fingerprints baseline.** This creates the basis for future automatic incremental updates and **must succeed before `meta.json` is written** — otherwise auto-update sees a fresh commit hash with no fingerprints to compare against, classifies every file as STRUCTURAL, and escalates to `FULL_UPDATE` on every subsequent commit (issue #152).

   Write the input file with the bundled Python helper:
   ```bash
   python "$SKILL_DIR/scripts/write_fingerprint_input.py" "$PROJECT_ROOT" "<current commit hash>"
   ```

   Then invoke the module from the `arch_analysis` project root:
   ```bash
   python -m arch_analysis.build_fingerprints \
     $PROJECT_ROOT/.understand-anything/intermediate/fingerprint-input.json
   ```

   The module uses the same `arch_analysis.structure` extraction as `arch_analysis.extract_structure`, so the baseline matches the comparison logic used during auto-updates.

   **If the module exits non-zero or stdout does not include `Fingerprints baseline:`, abort Phase 6 and report the error. Do NOT proceed to step 3 (writing `meta.json`).**

3. Write metadata to `$PROJECT_ROOT/.understand-anything/meta.json` with the bundled Python helper (only after step 2 succeeded). Use `analyzedFiles` from `save-summary.json`:
   ```bash
   python "$SKILL_DIR/scripts/write_meta.py" "$PROJECT_ROOT" "<commit hash>" "<number of files analyzed>"
   ```

4. Clean up intermediate files, **preserving `scan-result.json`** so future incremental runs can skip Phase 1 SCAN (see issue #293). We `mv` scratch dirs into a timestamped `.trash-*` instead of `rm -rf`ing them directly — this avoids tripping destructive-action gates on hardened hosts (e.g. freshness-window checks) that flag deleting directories created moments earlier (see issue #301). The delayed-purge step in Phase 0 reclaims the space once the trash is older than 7 days.
   ```bash
   "$SKILL_DIR/scripts/cleanup_intermediate.sh" "$PROJECT_ROOT"
   ```

5. Report a summary to the user using `$PROJECT_ROOT/.understand-anything/intermediate/save-summary.json`:
   - Project name and description
   - Files analyzed
   - Nodes created (broken down by type)
   - Edges created (broken down by type)
   - Layers identified (with names)
   - Any warnings from the reviewer
   - Path to the output file: `$PROJECT_ROOT/.understand-anything/knowledge-graph.json`

6. Only automatically launch the dashboard by invoking the `/understand-dashboard` skill if final graph validation passed after normalization/review fixes.
   If final validation did not pass, report that the graph was saved with warnings and dashboard launch was skipped.

---

## Error Handling

- If any subagent dispatch fails, retry **once** with the same prompt plus additional context about the failure.
- Track all warnings and errors from each phase in a `$PHASE_WARNINGS` list. When using `--review`, pass this list to the graph-reviewer in Phase 5. On the default path, include accumulated warnings in the Phase 6 final report.
- If it fails a second time, skip that phase and continue with partial results.
- ALWAYS save partial results — a partial graph is better than no graph.
- Report any skipped phases or errors in the final summary so the user knows what happened.
- NEVER silently drop errors. Every failure must be visible in the final report.

---

## Reference Schemas

Do not duplicate schema tables in this skill. Use the generated `arch_analysis` JSON Schemas as the authoritative contracts:

- Knowledge graph: `arch_analysis/schemas/knowledge-graph.schema.json`
- Batch graph fragment: `arch_analysis/schemas/graph-fragment.schema.json`
- Project scan output: `arch_analysis/schemas/project-scan-output.schema.json`
- File-analysis context: `arch_analysis/schemas/file-analysis-context.schema.json`
- Architecture layers: `arch_analysis/schemas/layers.schema.json`
