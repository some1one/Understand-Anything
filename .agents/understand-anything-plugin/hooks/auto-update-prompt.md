# Auto-Update Knowledge Graph (Internal — Hook-Triggered)

Incrementally update the knowledge graph using deterministic structural fingerprinting to minimize token usage. This prompt is triggered automatically by the post-commit hook when `autoUpdate` is enabled. It is NOT a user-facing skill.

**Key principle:** Spend zero LLM tokens when changes are cosmetic (formatting, internal logic). Only invoke LLM agents when structural changes (new/removed functions, classes, imports, exports) are detected.

**Deterministic by construction.** Every mechanical step — diffing commits, filtering source files, applying `.understandignore`, fingerprint comparison, batching, pruning, merging, layer reconciliation, fingerprint patching, and metadata writes — is implemented in the `arch_analysis` Python package and invoked as a command below. This prompt no longer embeds temporary Node/Bash scripts. The **only** LLM work is the targeted `file-analyzer` re-analysis (Phase 2) and the optional `architecture-analyzer` layer re-analysis (Phase 3a).

Each command writes its outputs under `$PROJECT_ROOT/.understand-anything/intermediate/` and prints a single machine-readable JSON object to stdout. Read that JSON (or the written file) to drive the next step.

**Running `arch_analysis` commands.** Set `PROJECT_ROOT` to the current working directory. Resolve `PLUGIN_ROOT` — the directory containing `.claude-plugin/plugin.json` (usually `$CLAUDE_PLUGIN_ROOT`; otherwise the install location, e.g. `$HOME/.understand-anything-plugin`). Run every deterministic step through the bundled launcher `"$PLUGIN_ROOT/packages/arch_analysis/run.sh" <module> …`, which creates the Python virtualenv on first use and resolves imports automatically. It preserves the working directory, so pass absolute paths (the commands below already use `$PROJECT_ROOT/…`).

---

## Phase 0 — Pre-flight (Zero Token Cost)

Run the pre-flight command. It validates that `knowledge-graph.json` and `meta.json` exist, reads the stored commit hash, runs `git rev-parse HEAD`, diffs the commits, filters to source files, applies `.understandignore`, creates `intermediate/`, and writes `auto-update-state.json`. It also handles every metadata-only stop case (bumping `meta.json` itself where appropriate).

```bash
"$PLUGIN_ROOT/packages/arch_analysis/run.sh" auto_update_preflight "$PROJECT_ROOT"
# add --force to re-run even when the commit hash is unchanged
```

Read `$PROJECT_ROOT/.understand-anything/intermediate/auto-update-state.json` (also printed to stdout). Act on `status` / `action`:

| `status` | `action` | What to do |
|---|---|---|
| `STOP` | `NO_GRAPH` | Report: "No existing knowledge graph found. Run `/understand` first to create one." **STOP.** |
| `STOP` | `NO_META` | Report the `reason` (no baseline / cannot diff). Suggest `/understand` to re-baseline. **STOP.** |
| `STOP` | `UP_TO_DATE` | Report: "Knowledge graph is already up to date." **STOP.** |
| `STOP` | `NO_CHANGES` / `NO_SOURCE_CHANGES` / `ALL_IGNORED` | Metadata already updated by the command (`metadataUpdated: true`). Report the `reason`. **STOP.** |
| `CONTINUE` | `PROCEED` | `changedSourceFiles` holds the files to inspect. Proceed to Phase 1. |

---

## Phase 1 — Structural Fingerprint Check (Zero LLM Tokens)

Run the fingerprint check. It reads `auto-update-state.json` and `fingerprints.json`, classifies each changed source file as `NONE` / `COSMETIC` / `STRUCTURAL` against its stored fingerprint (new files and files without structural support are `STRUCTURAL`; deleted files are recorded as removals), derives the overall decision, and writes `change-analysis.json`. On a `SKIP` decision it bumps `meta.json` to the new commit.

```bash
"$PLUGIN_ROOT/packages/arch_analysis/run.sh" auto_update_fingerprint_check "$PROJECT_ROOT"
```

Read `$PROJECT_ROOT/.understand-anything/intermediate/change-analysis.json`. It contains `action`, `rerunArchitecture`, `reason`, `filesToReanalyze`, `newFiles`, `deletedFiles`, `cosmeticOnlyFiles`, `unchangedFiles`, and `fileChanges`.

**Decision gate:**

| `action` | What to do |
|---|---|
| `SKIP` | `meta.json` already updated (`metadataUpdated: true`). Report: "No structural changes detected. Graph metadata updated. Zero tokens spent." **STOP.** |
| `FULL_UPDATE` | Report: "Major structural changes detected (`reason`). Recommend running `/understand --full` for a complete rebuild." **STOP.** |
| `PARTIAL_UPDATE` | Proceed to Phase 2 (`rerunArchitecture` is `false`). |
| `ARCHITECTURE_UPDATE` | Proceed to Phase 2, then run Phase 3a (`rerunArchitecture` is `true`). |

---

## Phase 2 — Targeted Re-Analysis (Minimal Token Cost)

Only files with structural changes are re-analyzed. This is the **only** phase that costs LLM tokens.

### 2a. Prepare batches (deterministic)

```bash
"$PLUGIN_ROOT/packages/arch_analysis/run.sh" auto_update_prepare_batches "$PROJECT_ROOT"
```

This reuses the `/understand` batching machinery (`compute_batches`) on just `filesToReanalyze` — loading the preserved `intermediate/scan-result.json`, scanning any new files, and writing:

- `intermediate/batches.json` — the same batch format `file-analyzer` consumes via `arch_analysis.prepare_file_analysis_batch`.
- `intermediate/dispatch-summary.json` — `projectName`, `projectDescription`, `languages`, `frameworks`, `allProjectFiles`, and a per-batch file list with each batch's `outputPath`.

### 2b. Dispatch file-analyzer per batch (LLM)

Read `dispatch-summary.json`. For each batch (`batchIndex` 1..`totalBatches`), dispatch a subagent using the **`file-analyzer`** agent definition (at `agents/file-analyzer.md`) exactly as `/understand` Phase 2 does — it reads `intermediate/batches.json`, runs `prepare_file_analysis_batch` / `extract_structure` / `seed_file_batch_graph` / `finalize_file_batch_output`, and writes `intermediate/batch-<batchIndex>.json`.

Append this context to each dispatch:

> **Additional context from main session:**
>
> Project: `<projectName>` — `<projectDescription>`
> Frameworks: `<frameworks>`
> Languages: `<languages>`
> Batch: `<batchIndex>/<totalBatches>`
>
> **IMPORTANT:** This is an incremental update. Only the files in this batch have structural changes. Analyze them thoroughly; do not invent nodes for files outside this batch. For cross-batch / cross-project import resolution, the full file inventory is in `dispatch-summary.json#allProjectFiles`.

If a dispatch fails, retry once; if it fails again, continue with the batches that succeeded (apply/finalize still produce a valid partial graph).

### 2c. Prune + merge (deterministic)

```bash
"$PLUGIN_ROOT/packages/arch_analysis/run.sh" auto_update_apply_batches "$PROJECT_ROOT"
```

This prunes old nodes for every changed/deleted file, writes the survivors as `intermediate/batch-existing.json`, then runs the standard merge normalization over `batch-existing.json` + all `batch-<N>.json` fragments (dedup by id, drop dangling edges, canonicalize edges, `tested_by` linking). It writes `intermediate/merged-graph.json`. When `rerunArchitecture` is `true` it also writes `intermediate/ua-arch-input.json` (the `{fileNodes, importEdges, allEdges}` payload for the architecture-analyzer).

---

## Phase 3 — Architecture + Save

### 3a. Architecture re-analysis (only if `rerunArchitecture === true`) (LLM)

Dispatch a subagent using the **`architecture-analyzer`** agent definition (at `agents/architecture-analyzer.md`). Point it at the prepared input rather than having it generate its own:

> Use `$PROJECT_ROOT/.understand-anything/intermediate/ua-arch-input.json` as the analyzer input (skip `generate_input`). Run `"$PLUGIN_ROOT/packages/arch_analysis/run.sh" analyze $PROJECT_ROOT/.understand-anything/intermediate/ua-arch-input.json $PROJECT_ROOT/.understand-anything/intermediate/results.json`, then assign layers per your normal process and write the layer array to `$PROJECT_ROOT/.understand-anything/intermediate/layers.json`.
>
> For naming consistency, reuse the previous layer names/IDs from `intermediate/merged-graph.json#layers` wherever the structure still matches; only add/remove layers if the file structure has materially changed.

The deterministic scripts prepare and validate the data, but the architecture-analyzer still owns the semantic layer judgment.

If `rerunArchitecture` is `false`, skip directly to 3b — the finalize command performs a deterministic lite layer update (new files placed by directory match, deleted files removed).

### 3b. Finalize (deterministic)

```bash
"$PLUGIN_ROOT/packages/arch_analysis/run.sh" auto_update_finalize "$PROJECT_ROOT"
```

This applies the layers (fresh `layers.json` when present, otherwise a lite update of the carried-forward layers), runs lite validation cleanup (drop dangling edges, prune unknown layer ids, ensure every file-level node sits in exactly one layer), writes `knowledge-graph.json`, **patches `fingerprints.json` LOAD-PATCH-SAVE** (only `filesToReanalyze` + `deletedFiles` are touched — every other entry is preserved, and the write is refused if the store would be clobbered), bumps `meta.json` (`gitCommitHash`, `lastAnalyzedAt`, `analyzedFiles`), and cleans `intermediate/` while preserving `scan-result.json` (and `auto-update-summary.json`).

Read `intermediate/auto-update-summary.json` (also printed to stdout) and report:

- Files checked: `filesChecked`
- Structural changes: `structuralChanges` (new: `newFiles`, deleted: `deletedFiles`)
- Cosmetic-only (skipped): `cosmeticOnly`
- Nodes in graph: `totalNodes`, edges: `totalEdges`
- Action: `action`
- Output: `outputPath`

---

## Error Handling

- If `auto_update_fingerprint_check` cannot read `fingerprints.json`, it treats files with no stored fingerprint as `STRUCTURAL` (conservative) — no special handling needed.
- If a `file-analyzer` dispatch fails twice, continue; `apply_batches`/`finalize` still produce a valid (partial) graph.
- `finalize` refuses to overwrite a populated `fingerprints.json` with an empty one (issue #152 guard) and aborts with a non-zero exit; if that happens, report the error and recommend `/understand --full` to re-baseline rather than leaving a corrupt store.
- ALWAYS prefer a saved partial result over no update.

---

## Notes

- This flow reuses the same `file-analyzer` and `architecture-analyzer` agent definitions as `/understand` — no separate agent prompts.
- The authoritative fingerprints in `fingerprints.json` are generated by `/understand` Phase 7 (`arch_analysis.build_fingerprints`) and patched here by `arch_analysis.auto_update_finalize`; both share the extraction/comparison logic in `arch_analysis.fingerprints`, so baseline and incremental fingerprints are computed identically (tree-sitter precise, not regex).
- The JSON contracts for `auto-update-state.json`, `change-analysis.json`, and `auto-update-summary.json` are defined by the pydantic models in `arch_analysis/models.py` and rendered to `arch_analysis/schemas/`.
