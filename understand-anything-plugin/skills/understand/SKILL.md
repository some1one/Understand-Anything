---
name: understand
description: Analyze a codebase to produce an interactive knowledge graph for understanding architecture, components, and relationships
argument-hint: ["[path] [--full|--auto-update|--no-auto-update|--review]"]
---

# /understand

Analyze the current codebase and write `.understand-anything/knowledge-graph.json`, which powers the interactive dashboard.

## Options

`$ARGUMENTS` may contain:
- `--full` — force a full rebuild, ignoring any existing graph
- `--auto-update` / `--no-auto-update` — set `autoUpdate` in `.understand-anything/config.json`
- `--review` — run the full LLM graph-reviewer instead of inline deterministic validation
- `--no-domain` — skip Phase 7 (business-domain graph); by default a domain flow graph is derived
- A directory path — analyze that directory instead of the cwd

Report progress only at the end (the Phase 6/7 summary) or when a subagent returns to its parent. Do not print per-phase status lines.

---

## Phase 0 — Pre-flight

Decide full analysis vs. incremental update.

1. **Resolve `PROJECT_ROOT`:** parse `$ARGUMENTS` for a non-flag token as the target dir. Set `SKILL_DIR` to this file's directory. Then:
   ```bash
   PROJECT_ROOT="$("$SKILL_DIR/scripts/resolve_project_root.sh" "<path-or-cwd>")"
   ```
   Set `UNDERSTAND_NO_WORKTREE_REDIRECT=1` only to force a per-worktree graph (rare).

1.5. **Ensure the Python env** (creates the `arch_analysis` venv on first use). Prints `PLUGIN_ROOT`:
   ```bash
   PLUGIN_ROOT="$("$SKILL_DIR/scripts/ensure_python_env.sh")"
   ```
   All later `arch_analysis` steps run `"$PLUGIN_ROOT/packages/arch_analysis/run.sh" <module> …`. If neither `pdm` nor `python3` exists, report: "Install Python ≥ 3.14 (and ideally PDM), then re-run `/understand`."

   **Three roots — never use bare relative paths** (the skill installs apart from the analyzed code, sometimes via symlink):
   - `$PROJECT_ROOT` — analyzed codebase; all `.understand-anything/*`, source, and git state live here.
   - `$SKILL_DIR` — this skill; bundled `scripts/`, `prompts/`, `frameworks/`, `languages/` are here.
   - `$PLUGIN_ROOT` — plugin root; `agents/` and `packages/arch_analysis/` (and its `schemas/`) are here.

2. Get the commit hash: `git rev-parse HEAD`

3. Prepare workspace (creates temp dirs, purges stale trash, applies auto-update flags):
   ```bash
   "$SKILL_DIR/scripts/prepare_workspace.sh" "$PROJECT_ROOT" $ARGUMENTS
   ```

4. **Merge subdomain graphs:** list `*knowledge-graph*.json` in `$PROJECT_ROOT/.understand-anything/` excluding `knowledge-graph.json` itself. If any exist, merge them into `knowledge-graph.json` and continue with the merged graph:
   ```bash
   "$PLUGIN_ROOT/packages/arch_analysis/run.sh" merge_subdomain_graphs $PROJECT_ROOT
   ```

5. If `$PROJECT_ROOT/.understand-anything/knowledge-graph.json` exists, read it.
6. If `$PROJECT_ROOT/.understand-anything/meta.json` exists, read it for `gitCommitHash`.
7. **Decision:**

   | Condition | Action |
   |---|---|
   | `--full`, or no existing graph/meta | Full analysis (all phases) |
   | `--review` + existing graph + unchanged hash | Skip to Phase 5 (review-only) |
   | Existing graph + unchanged hash | Ask: "(a) full rebuild, (b) LLM reviewer, (c) nothing?" — follow choice; (c) STOP |
   | Existing graph + changed files | Incremental (re-analyze changed files only) |

   **Review-only path:** copy `knowledge-graph.json` to `intermediate/assembled-graph.json`, jump to Phase 5 step 3.

   For incremental updates, write the changed-file list:
   ```bash
   python "$SKILL_DIR/scripts/write_changed_files.py" "$PROJECT_ROOT" "<lastCommitHash>"
   ```
   If `changed-files.txt` is empty, report "Graph is up to date" and STOP.

8. **Capture project context** (writes `intermediate/project-context.json`, prints the same JSON). Use its `readmeContent`, `manifestContent`, `dirTree`, `entryPoint` as `$README_CONTENT`, `$MANIFEST_CONTENT`, `$DIR_TREE`, `$ENTRY_POINT`:
   ```bash
   python "$SKILL_DIR/scripts/capture_project_context.py" "$PROJECT_ROOT"
   ```

---

## Phase 0.5 — Ignore Configuration

1. If `$PROJECT_ROOT/.understand-anything/.understandignore` does not exist, generate a starter:
   ```bash
   "$PLUGIN_ROOT/packages/arch_analysis/run.sh" generate_ignore $PROJECT_ROOT
   ```

2. **Decide whether to prompt for review:**
   - **New/full run:** always prompt and wait (step 3).
   - **Incremental update:** skip the prompt silently — **unless** `changed-files.txt` includes any of these (ignore rules likely need revisiting → prompt and wait):
     - a **dot-prefixed** path (`.eslintrc`, `.github/…`, `.env`, …);
     - **workspace tooling** — dependency manifests/lockfiles, `tsconfig*.json`, `Makefile`, or CI config;
     - an obvious **framework/domain** change — new framework or new top-level domain/service dirs.

3. **Prompt-and-wait** (only when step 2 requires it):
   - Just generated: "Generated `.understand-anything/.understandignore` with suggested exclusions. Review it, uncomment patterns to exclude, then confirm to continue."
   - Already existed: "Found `.understand-anything/.understandignore`. Review it if needed, then confirm to continue."
   - **Wait for confirmation before proceeding.**

---

## Phase 1 — SCAN (Full analysis only)

Dispatch a subagent using the `project-scanner` agent (`$PLUGIN_ROOT/agents/project-scanner.md`) and template `$SKILL_DIR/prompts/project-scanner-dispatch.md`. Fill args from Phase 0: `PROJECT_ROOT`, `README_CONTENT`, `MANIFEST_CONTENT`.

After it completes, read `$PROJECT_ROOT/.understand-anything/intermediate/scan-result.json` for: project name/description, languages, frameworks, file list (line counts + `fileCategory`: `code`|`config`|`docs`|`infra`|`data`|`script`|`markup`), complexity, and `importMap` (pre-resolved internal imports per file).

Store `importMap` as `$IMPORT_MAP` and the file list (with `fileCategory`) as `$FILE_LIST` for Phase 2 batching.

**Gate:** if >100 files, inform the user and suggest scoping to a subdirectory; proceed only on confirmation.

If `filteredByIgnore > 0`, note it for the final report.

---

## Phase 1.5 — BATCH

Reads `intermediate/scan-result.json`, writes `intermediate/batches.json`:
```bash
"$PLUGIN_ROOT/packages/arch_analysis/run.sh" compute_batches $PROJECT_ROOT
```

Append any stderr line starting with `Warning:` to `$PHASE_WARNINGS`. A non-zero exit is a hard failure (missing/malformed input) — relay the full stderr and do not attempt recovery.

---

## Phase 2 — ANALYZE

### Full analysis path

Load `intermediate/batches.json`. For each entry in `batches[]`, dispatch a subagent using the `file-analyzer` agent (`$PLUGIN_ROOT/agents/file-analyzer.md`) and template `$SKILL_DIR/prompts/file-analyzer-batch-dispatch.md`. Run up to **5 concurrently**. Fill args from `scan-result.json`, `batches.json[i]`, and Phase 0 context: `PROJECT_ROOT`, `PROJECT_NAME`, `PROJECT_DESCRIPTION`, `LANGUAGES`, `BATCH_INDEX`, `TOTAL_BATCHES`, `SKILL_DIR`, `OUTPUT_PATH`, `BATCH_IMPORT_DATA_JSON`, `NEIGHBOR_MAP_JSON`, `BATCH_FILES`.

**Output naming is per-batchIndex — no fusion.** If you fuse batches into one dispatch, the agent must still write one file per original `batchIndex` as `batch-<batchIndex>.json` or `batch-<batchIndex>-part-<k>.json`. The merge regex (`batch-(\d+)(?:-part-(\d+))?\.json`) silently drops other names, losing all nodes/edges in that file. After each dispatch returns, verify every dispatched `batchIndex` has a matching file on disk before continuing.

After all batches complete, merge and normalize (reads all `batch-*.json`, writes `intermediate/assembled-graph.json`):
```bash
"$PLUGIN_ROOT/packages/arch_analysis/run.sh" merge_batch_graphs $PROJECT_ROOT
```
It combines nodes/edges, normalizes IDs and complexity values, rewrites edge refs, dedupes, drops dangling edges, and canonicalizes `tested_by` edges (all resulting edges run `production → test`; sourced production nodes get a `"tested"` tag). Add its warnings to `$PHASE_WARNINGS`.

### Incremental update path

Write the changed-files list if Phase 0 hasn't:
```bash
python "$SKILL_DIR/scripts/write_changed_files.py" "$PROJECT_ROOT" "<lastCommitHash>"
```
Compute batches for changed files only (neighborMap still references unchanged files so cross-batch edges stay emittable):
```bash
"$PLUGIN_ROOT/packages/arch_analysis/run.sh" compute_batches $PROJECT_ROOT \
  --changed-files=$PROJECT_ROOT/.understand-anything/tmp/changed-files.txt
```
Dispatch file-analyzers per the same template. After they complete:
1. Prune old nodes/edges for changed files → `batch-existing.json`:
   ```bash
   python "$SKILL_DIR/scripts/prune_incremental_batch.py" \
     "$PROJECT_ROOT" \
     "$PROJECT_ROOT/.understand-anything/tmp/changed-files.txt"
   ```
2. Run the same `merge_batch_graphs` module (combines `batch-existing.json` with the fresh batches).

---

## Phase 3 — ASSEMBLE REVIEW

Dispatch a subagent using the `assemble-reviewer` agent (`$PLUGIN_ROOT/agents/assemble-reviewer.md`) and template `$SKILL_DIR/prompts/assemble-review-dispatch.md`. Fill args: `PROJECT_ROOT`, `MERGE_REPORT`, `IMPORT_MAP_JSON`.

After it completes, read `intermediate/assemble-review.json` and add any notes to `$PHASE_WARNINGS`.

---

## Phase 4 — ARCHITECTURE

Prepare deterministic template args (loads language addenda via `/understand-language` and framework addenda via `/understand-framework`; writes `intermediate/architecture-template-args.json`):
```bash
python "$SKILL_DIR/scripts/prepare_architecture_context.py" "$PROJECT_ROOT" "$SKILL_DIR"
```

Dispatch a subagent using the `architecture-analyzer` agent (`$PLUGIN_ROOT/agents/architecture-analyzer.md`) and template `$SKILL_DIR/prompts/architecture-analyzer-dispatch.md`. Fill args from `architecture-template-args.json`: `PROJECT_ROOT`, `PROJECT_NAME`, `PROJECT_DESCRIPTION`, `FRAMEWORKS`, `DIR_TREE`, `LANGUAGE_CONTEXT`, `FRAMEWORK_CONTEXT`, `FILE_NODES_JSON`, `IMPORT_EDGES_JSON`, `ALL_EDGES_JSON`, `PREVIOUS_LAYERS_JSON`. If a detected language/framework has no addendum, continue without it.

After it completes, normalize the layers:
```bash
python "$SKILL_DIR/scripts/normalize_layers.py" "$PROJECT_ROOT"
```

**Incremental updates:** always re-run architecture on the full merged node set (layer assignments may shift); pass prior layers via `PREVIOUS_LAYERS_JSON` for naming consistency.

---

## Phase 5 — REVIEW

1. Assemble the full KnowledgeGraph object from `scan-result.json`, reviewed `assembled-graph.json` nodes/edges, normalized `layers.json`, and the commit hash:
   ```bash
   python "$SKILL_DIR/scripts/assemble_knowledge_graph.py" "$PROJECT_ROOT" "<commit hash>"
   ```
   Shape: `{ version, project{name,languages,frameworks,description,analyzedAt,gitCommitHash}, nodes[], edges[], layers[] }`.

2. **Check `$ARGUMENTS` for `--review`** and run the matching path:

   **Default (no `--review`) — deterministic validation.** Runs referential-integrity, completeness, layer-coverage, uniqueness, quality, and (via `--scan-result`) scan-coverage checks; writes the review payload (`scriptCompleted`, `issues`, `warnings`, `stats`):
   ```bash
   "$PLUGIN_ROOT/packages/arch_analysis/run.sh" validate_graph \
     "$PROJECT_ROOT/.understand-anything/intermediate/assembled-graph.json" \
     "$PROJECT_ROOT/.understand-anything/intermediate/review.json" \
     --scan-result "$PROJECT_ROOT/.understand-anything/intermediate/scan-result.json"
   ```
   On non-zero exit, diagnose from stderr (usually unreadable/malformed graph) and retry once. Approved when `issues` is empty (warnings are OK).

   **`--review` — full LLM reviewer.** Dispatch a subagent using the `graph-reviewer` agent (`$PLUGIN_ROOT/agents/graph-reviewer.md`) and template `$SKILL_DIR/prompts/graph-reviewer-dispatch.md`. Fill args: `PROJECT_ROOT`, `SCAN_FILE_LIST_JSON`, `PHASE_WARNINGS`.

3. Read `intermediate/review.json`.
4. **If `issues` is non-empty:** apply deterministic fixes, then re-validate:
   ```bash
   python "$SKILL_DIR/scripts/apply_review_fixes.py" "$PROJECT_ROOT"
   ```
   If critical issues remain after one fix attempt, save anyway and carry the warnings into the final report.
5. **If `issues` is empty:** proceed to Phase 6.

---

## Phase 6 — SAVE

1. Save the graph (writes `knowledge-graph.json` and `intermediate/save-summary.json`):
   ```bash
   python "$SKILL_DIR/scripts/save_knowledge_graph.py" "$PROJECT_ROOT"
   ```

2. **Build the fingerprints baseline** — **must succeed before `meta.json` is written** (otherwise auto-update finds no baseline and escalates every commit to `FULL_UPDATE`, issue #152):
   ```bash
   python "$SKILL_DIR/scripts/write_fingerprint_input.py" "$PROJECT_ROOT" "<commit hash>"
   "$PLUGIN_ROOT/packages/arch_analysis/run.sh" build_fingerprints \
     $PROJECT_ROOT/.understand-anything/intermediate/fingerprint-input.json
   ```
   **If it exits non-zero or stdout lacks `Fingerprints baseline:`, abort Phase 6 and report — do NOT write `meta.json`.**

3. Write `meta.json` (only after step 2 succeeded), using `analyzedFiles` from `save-summary.json`:
   ```bash
   python "$SKILL_DIR/scripts/write_meta.py" "$PROJECT_ROOT" "<commit hash>" "<files analyzed>"
   ```

4. Clean up intermediates, **preserving `scan-result.json`** (issue #293). Moves scratch dirs to a timestamped `.trash-*` rather than `rm -rf` to avoid destructive-action gates (issue #301); Phase 0 purges trash older than 7 days:
   ```bash
   "$SKILL_DIR/scripts/cleanup_intermediate.sh" "$PROJECT_ROOT"
   ```

5. Report a final summary from `intermediate/save-summary.json`: project name/description, files analyzed, nodes (by type), edges (by type), layers (with names), reviewer warnings, and the output path `$PROJECT_ROOT/.understand-anything/knowledge-graph.json`.

6. Proceed to Phase 7 unless `--no-domain`. Do not auto-launch the dashboard.

---

## Phase 7 — DOMAIN

Derives domains, business flows, and process steps into `domain-graph.json` from the knowledge graph (no re-scanning).

**Skip conditions:** if `--no-domain`, or if Phase 5 validation did not pass — skip to the final step (dashboard instructions), noting any warnings.

1. Derive domain context (writes `intermediate/domain-context.json`; read it as context):
   ```bash
   python "$SKILL_DIR/scripts/graph_domain_context.py" "$PROJECT_ROOT"
   ```

2. Dispatch a subagent using the `domain-analyzer` agent (`$PLUGIN_ROOT/agents/domain-analyzer.md`) and template `$SKILL_DIR/prompts/domain-analyzer-dispatch.md`. Fill args: `PROJECT_ROOT`, `CONTEXT_SOURCE` = `knowledge-graph`, `DOMAIN_CONTEXT_JSON` = contents of `domain-context.json`. Output: `intermediate/domain-analysis.json`. If it fails after one retry, report, skip to the final step, and continue — a missing domain graph must not block the saved knowledge graph.

3. Validate and save the domain graph (also cleans domain intermediates); include any warnings in the final report:
   ```bash
   python "$SKILL_DIR/scripts/save_domain_graph.py" "$PROJECT_ROOT"
   ```

4. **Print dashboard instructions — do NOT auto-launch:**
   > Knowledge graph ready. To explore it, run `/understand-dashboard` (or `make dev` from the repo). The dashboard shows the structural graph and, when present, the domain view from `domain-graph.json`.

   If validation did not pass, still print these but note the graph was saved with warnings.

---

## Error Handling

- Retry a failed subagent dispatch **once** with added failure context; if it fails again, skip that phase and continue with partial results.
- Track all warnings/errors per phase in `$PHASE_WARNINGS`. With `--review`, pass it to the Phase 5 reviewer; otherwise include it in the Phase 6 final report.
- ALWAYS save partial results — a partial graph beats none. Never silently drop errors; every failure must be visible in the final report.

---

## Reference Schemas

Authoritative contracts (do not duplicate schema tables here) under `$PLUGIN_ROOT/packages/arch_analysis/schemas/`:
`knowledge-graph.schema.json`, `graph-fragment.schema.json`, `project-scan-output.schema.json`, `file-analysis-context.schema.json`, `layers.schema.json`.
