---
name: understand
description: Analyze a codebase to produce or refresh a knowledge graph of architecture, components, and relationships. For plugin installation, first-run setup instructions, or usage help, use understand-help.
argument-hint: "[path] [--split=<depth>] [--source=<dir>] [--all] [--full] [--auto-update|--no-auto-update] [--review] [--no-domain] [--exclude=patterns]"
---

# /understand

Resolve `UA_DIR` after resolving `PLUGIN_ROOT` and `PROJECT_ROOT`, before reading
or writing project artifacts:

```bash
UA_DIR=$(python3 "$PLUGIN_ROOT/scripts/data_directory.py" "$PROJECT_ROOT")
```

Use this absolute directory throughout the workflow and pass it to workers.
Fill `UA_DIR` in every dispatch template with this resolved path; never derive
worker output paths by appending `.ua` to the project root.
It selects `.ua` for new projects and retains an existing legacy directory;
see [host integration](../../HOSTS.md) for the selection rules.


Analyze the current codebase and write `$UA_DIR/knowledge-graph.json`, which powers the interactive dashboard.

## Options

Analysis is **part-based by default**: the repo is split into folder-parts, and
on first run you choose which parts to analyze (remembered for later updates).
Each part is analyzed independently into `partitions/<part>.knowledge-graph.json`
and merged into the full `knowledge-graph.json`.

`$ARGUMENTS` may contain:
- `--source=<dir>[,<dir>]` — treat these as the source root(s) for partitioning (overrides detection)
- `--split=<depth>` — folder depth for parts (1 = top-level; 2 for monorepos). Overrides detection
- `--all` — include every part and skip the inclusion prompt (builds the whole repo, part-wise)
- `--full` — force a full rebuild of the included parts, ignoring any existing graph
- `--auto-update` / `--no-auto-update` — set `autoUpdate` in `$UA_DIR/config.json`
- `--review` — run the full LLM graph-reviewer instead of inline deterministic validation
- `--exclude=<pattern>[,<pattern>]` — invocation-scoped gitignore patterns, applied after defaults and user ignore files; `!` re-includes an enumerated path. Quote the value. Omission means no extra patterns for this explicit analysis; auto-update retains the last published scope.
- `--no-domain` — skip Phase 7 (business-domain graph); by default a domain flow graph is derived
- A directory path — analyze that directory instead of the cwd

Partition config (`sourceFolders`, `splitDepth`, `includedParts`) is persisted in
`$UA_DIR/config.json`. At least one of source / depth is always set.
On an update run the saved config is reused silently (no prompts).

Read [host integration](../../HOSTS.md) before running the workflow. It explains Claude/Codex invocation, argument handling, and how to load the bundled agent instructions. Give concise updates during long runs and report failures when they occur.

---

Dictionary downloads are plugin maintenance via
[understand-update](../understand-update/SKILL.md), not part of graph indexing.
Use configured system dictionaries and local fallback snapshots throughout this workflow.
If dictionary access fails, report the configuration path and both repair options
from the error: update system file paths or use the configurator with
`--prefer-local --local-dir` to download latest repo-local data. Relay the
[maintenance instructions](../understand-update/SKILL.md) and recommend
`/understand --full` after repair; do not download during indexing.

## Phase 0 — Pre-flight

Decide full analysis vs. incremental update.

1. **Resolve `PROJECT_ROOT`:** parse `$ARGUMENTS` for a non-flag token as the target dir. Set `SKILL_DIR` to this file's directory. Then:
   ```bash
   PROJECT_ROOT="$("$SKILL_DIR/scripts/resolve_project_root.sh" "<path-or-cwd>")"
   ```
   Keep the requested worktree as the analysis target; do not redirect to another checkout.

1.5. **Locate and check the Rust engine.** Prints `PLUGIN_ROOT`:
   ```bash
   PLUGIN_ROOT="$("$SKILL_DIR/scripts/ensure_rust_engine.sh")"
   ```
   Run later deterministic commands with `"$PLUGIN_ROOT/packages/rust/run.sh" <command> …`. Packaged installs ship the executable; source checkouts build it with stable Rust and Cargo on first use.

   **Three roots — never use bare relative paths** (the skill installs apart from the analyzed code, sometimes via symlink):
   - `$PROJECT_ROOT` — analyzed codebase; all `$UA_DIR/*`, source, and git state live here.
   - `$SKILL_DIR` — this skill; bundled `scripts/`, `prompts/`, `frameworks/`, `languages/` are here.
   - `$PLUGIN_ROOT` — plugin root; `agents/` and `packages/rust/` (and its `schemas/`) are here.

2. Get the commit hash: `git -C "$PROJECT_ROOT" rev-parse HEAD`. For a non-Git project or unborn branch, use an empty hash and perform a full analysis; commit-based incremental updates are unavailable.

3. Prepare workspace (creates temp dirs and merges auto-update flags into existing config). Pass only the parsed auto-update flag, if present:
   ```bash
   "$SKILL_DIR/scripts/prepare_workspace.sh" "$PROJECT_ROOT" [--auto-update|--no-auto-update]
   ```

4. **Inventory existing graphs:** note legacy `*knowledge-graph*.json` fragments and `partitions/*.knowledge-graph.json`. Do not overwrite the saved graph during preflight. The normal part workflow merges selected parts in Phase 2; use the `understand-merge` skill for an explicitly requested standalone merge.

5. If `$UA_DIR/knowledge-graph.json` exists, read it.
6. If `$UA_DIR/meta.json` exists, read it for `gitCommitHash`.
7. **Resolve exclusion scope before deciding whether to stop:** parse all `--exclude` values into an ordered list `$EXCLUDE_PATTERNS` (split on commas, trim whitespace, drop empty entries; default `[]`). Compare this list with `meta.json.excludePatterns` (missing means `[]`). If they differ, set `$SCOPE_CHANGED=true`: continue through SCAN and refresh every included part, even if HEAD or the changed-file list is unchanged. Do not change `includedParts` or write ignore files. Review-only requests stay read-only; disclose that exclusion changes require an analysis run.

   **Decision:**

   | Condition | Action |
   |---|---|
   | `--full`, exclusion scope changed (unless review-only), or no existing graph/meta | Full analysis (all phases) |
   | `--review` + existing graph + unchanged hash | Skip to Phase 5 (review-only) |
   | Existing graph + unchanged hash | Ask: "(a) full rebuild, (b) LLM reviewer, (c) nothing?" — follow choice; (c) STOP |
   | Existing graph + changed files | Incremental (re-analyze only the **affected parts** — see Phase 1.6/2) |

   **Review-only path:** copy `knowledge-graph.json` to `intermediate/assembled-graph.json`, jump to Phase 5 step 2 with the LLM reviewer selected. Use the retained scan result when available; otherwise derive the file list from the saved graph and disclose that scan coverage was not rechecked. Report the review findings and STOP before fixes or SAVE; reviewing alone does not authorize graph changes.

   For incremental updates, write the changed-file list:
   ```bash
   python3 "$SKILL_DIR/scripts/write_changed_files.py" "$PROJECT_ROOT" "<lastCommitHash>"
   ```
   If `changed-files.txt` is empty and exclusion scope is unchanged, skip analysis. With `--review`, follow the
   review-only path above even when the commit hash changed (for example, a
   sibling monorepo project changed). Otherwise report "Graph is up to date"
   and STOP. Do not advance the saved baseline for a review-only run.

8. **Capture project context** (writes `intermediate/project-context.json`, prints the same JSON). Use its `readmeContent`, `manifestContent`, `dirTree`, `entryPoint` as `$README_CONTENT`, `$MANIFEST_CONTENT`, `$DIR_TREE`, `$ENTRY_POINT`:
   ```bash
   python3 "$SKILL_DIR/scripts/capture_project_context.py" "$PROJECT_ROOT"
   ```

---

## Phase 0.5 — Ignore Configuration

1. If `$UA_DIR/.understandignore` does not exist, generate a starter:
   ```bash
   "$PLUGIN_ROOT/packages/rust/run.sh" generate_ignore "$PROJECT_ROOT"
   ```

2. **Decide whether to prompt for review:**
   - **New/full run:** always prompt and wait (step 3).
   - **Incremental update:** skip the prompt silently — **unless** `changed-files.txt` includes any of these (ignore rules likely need revisiting → prompt and wait):
     - a **dot-prefixed** path (`.eslintrc`, `.github/…`, `.env`, …);
     - **workspace tooling** — dependency manifests/lockfiles, `tsconfig*.json`, `Makefile`, or CI config;
     - an obvious **framework/domain** change — new framework or new top-level domain/service dirs.

3. **Prompt-and-wait** (only when step 2 requires it):
   - Just generated: "Generated `$UA_DIR/.understandignore` with suggested exclusions. Review it, uncomment patterns to exclude, then confirm to continue."
   - Already existed: "Found `$UA_DIR/.understandignore`. Review it if needed, then confirm to continue."
   - **Wait for confirmation before proceeding.**

---

## Phase 1 — SCAN (Full and incremental analysis)

Dispatch a subagent using the `project-scanner` agent (`$PLUGIN_ROOT/agents/project-scanner.md`) and template `$SKILL_DIR/prompts/project-scanner-dispatch.md`. Fill args from Phase 0: `PROJECT_ROOT`, `README_CONTENT`, `MANIFEST_CONTENT`, `EXCLUDE_PATTERNS_JSON` (the ordered list, including `[]` when omitted).

After it completes, read `$UA_DIR/intermediate/scan-result.json` for: project name/description, languages, frameworks, file list (line counts + `fileCategory`: `code`|`config`|`docs`|`infra`|`data`|`script`|`markup`), complexity, and `importMap` (pre-resolved internal imports per file).

Store `importMap` as `$IMPORT_MAP` and the file list (with `fileCategory`) as `$FILE_LIST` for Phase 2 batching. The scan covers the **whole repo** (partitioning happens next); there is no file-count gate — large repos are handled by analyzing selected parts.

If `filteredByIgnore > 0`, note it for the final report.

---

## Phase 1.6 — PARTITION

Split the scanned repo into folder-parts and decide which to analyze. Load `$UA_DIR/config.json` first.

**Resolve source / depth** (at least one required; flags override config, config overrides detection):
- `--source=` / `--split=` given → use them.
- else `config.sourceFolders` / `config.splitDepth` present → use them (update run).
- else run layout detection for a recommended default:
  ```bash
  "$PLUGIN_ROOT/packages/rust/run.sh" detect_layout "$PROJECT_ROOT"
  ```
  It prints `{detectedRoots, recommendation:{sourceFolders, splitDepth}}` (single `src/` → `{[src],1}`; monorepo → `{null,2}`; flat → `{null,1}`).

**First run** (no `config.includedParts`) **and not `--all`:**
1. Show the detected roots + recommended source/depth; ask the user to accept or adjust (at least one of source/depth must be set). Wait for confirmation.
2. Partition (writes `intermediate/partitions.json` + per-part file lists under `intermediate/part-files/`):
   ```bash
   "$PLUGIN_ROOT/packages/rust/run.sh" partition_files "$PROJECT_ROOT" [--source=a,b] [--depth=N]
   ```
3. Show each part with its file count (from `partitions.json`); ask which parts to include. Wait for confirmation.
4. Persist the choice:
   ```bash
   "$PLUGIN_ROOT/packages/rust/run.sh" write_config "$PROJECT_ROOT" --source=<...> --depth=<N> --parts=<comma-separated included>
   ```

**`--all`:** partition with the resolved source/depth, then persist `includedParts` = **every** part from `partitions.json` (no inclusion prompt).

**Update run** (config present, no first-run prompt needed): re-partition with the saved source/depth to refresh `partitions.json` + `part-files/`; keep the saved `includedParts`. Included parts with no remaining files retain an empty file list; process them to replace their saved graph with an empty graph.

**Determine `$PARTS_TO_PROCESS`** (prints part names, one per line):
```bash
"$PLUGIN_ROOT/packages/rust/run.sh" parts_to_process "$PROJECT_ROOT" \
  [--full] [--changed="$UA_DIR/tmp/changed-files.txt"]
```
- Pass `--full` for `--full`/`--all`/first-run or `$SCOPE_CHANGED=true` → every included part. This replaces newly empty part graphs and restores newly included files. Partitioning, import resolution, batching, and fingerprints must all use the filtered scan inventory; do not rescan without the invocation patterns.
- Otherwise pass `--changed=…` → **affected** parts plus any included part that has no partition graph yet (e.g. one just added via `/understand-add-part`).
- If the output is empty, skip analysis. With `--review`, follow Phase 0's
  review-only path using the saved graph; retain warnings about changed files
  outside the selected parts and distinguish that saved scope from the fresh
  scan. Otherwise report "Graph is up to date" and STOP. Do not assemble or save
  a replacement graph just to perform the requested review.

---

## Phase 2 — ANALYZE (per part)

For **each** part in `$PARTS_TO_PROCESS`, run steps 1–4. Parts are independent; process them one at a time (each part's file-analyzers still run up to **5 concurrently**). A part's file list is `intermediate/part-files/<part>.txt` (the part name with `/` written as `~`).

1. **Batch the part's files** (scoped via the part file list; `neighborMap` still references files in other parts so cross-part edges stay emittable):
   ```bash
   "$PLUGIN_ROOT/packages/rust/run.sh" compute_batches "$PROJECT_ROOT" \
     --changed-files="$UA_DIR/intermediate/part-files/<part-encoded>.txt"
   ```
   Append `Warning:` stderr lines to `$PHASE_WARNINGS`; a non-zero exit is a hard failure.

2. **Dispatch file-analyzers.** Load `intermediate/batches.json`; for each entry in `batches[]` dispatch a subagent using the `file-analyzer` agent (`$PLUGIN_ROOT/agents/file-analyzer.md`) and template `$SKILL_DIR/prompts/file-analyzer-batch-dispatch.md`, up to **5 concurrently**. Fill args from `scan-result.json`, `batches.json[i]`, and Phase 0 context: `PROJECT_ROOT`, `PROJECT_NAME`, `PROJECT_DESCRIPTION`, `LANGUAGES`, `BATCH_INDEX`, `TOTAL_BATCHES`, `SKILL_DIR`, `OUTPUT_PATH`, `BATCH_IMPORT_DATA_JSON`, `NEIGHBOR_MAP_JSON`, `BATCH_FILES`.

   **Output naming is per-batchIndex — no fusion.** If you fuse batches into one dispatch, the agent must still write one file per original `batchIndex` as `batch-<batchIndex>.json` or `batch-<batchIndex>-part-<k>.json`. The merge regex (`batch-(\d+)(?:-part-(\d+))?\.json`) silently drops other names, losing all nodes/edges in that file. After each dispatch returns, verify every dispatched `batchIndex` has a matching file on disk.

3. **Assemble the part's batches** (reads all `batch-*.json`, writes `intermediate/assembled-graph.json`):
   ```bash
   "$PLUGIN_ROOT/packages/rust/run.sh" merge_batch_graphs "$PROJECT_ROOT"
   ```
   An explicitly empty batch plan produces an empty assembled graph without dispatching analyzers. It creates scan-backed boundary stubs before normalization, combines nodes/edges, normalizes IDs and complexity values, rewrites edge refs, dedupes, drops dangling edges, and canonicalizes `tested_by` edges (all resulting edges run `production → test`; sourced production nodes get a `"tested"` tag). Add its warnings to `$PHASE_WARNINGS`. Read `$UA_DIR/intermediate/batch-merge-report.txt` if stderr was truncated; investigate any loaded batch that contributed no nodes or edges before publishing.

4. **Persist the part graph** (adds boundary stubs for cross-part edges, tags it with the part name, writes `partitions/<part>.knowledge-graph.json`, and clears this part's `batch-*.json` + `assembled-graph.json` scratch):
   ```bash
   "$PLUGIN_ROOT/packages/rust/run.sh" assemble_part_graph "$PROJECT_ROOT" "<part>" "<commit hash>"
   ```

After all parts are processed, **merge the included parts** into the unified assembled graph — reused (unaffected) parts are read from `partitions/`, and boundary stubs resolve against the real nodes:
```bash
"$PLUGIN_ROOT/packages/rust/run.sh" merge_parts "$PROJECT_ROOT"
```
This writes `intermediate/assembled-graph.json` — the input to Phases 3–7, exactly as in a monolithic run.

---

## Phase 3 — ASSEMBLE REVIEW

Dispatch a subagent using the `assemble-reviewer` agent (`$PLUGIN_ROOT/agents/assemble-reviewer.md`) and template `$SKILL_DIR/prompts/assemble-review-dispatch.md`. Fill args: `PROJECT_ROOT`, `MERGE_REPORT`, `IMPORT_MAP_JSON`.

After it completes, read `intermediate/assemble-review.json` and add any notes to `$PHASE_WARNINGS`.

---

## Phase 4 — ARCHITECTURE

Prepare deterministic template args (loads language addenda via `/understand-language` and framework addenda via `/understand-framework`; writes `intermediate/architecture-template-args.json`):
```bash
python3 "$SKILL_DIR/scripts/prepare_architecture_context.py" "$PROJECT_ROOT" "$SKILL_DIR"
```

Dispatch a subagent using the `architecture-analyzer` agent (`$PLUGIN_ROOT/agents/architecture-analyzer.md`) and template `$SKILL_DIR/prompts/architecture-analyzer-dispatch.md`. Fill args from `architecture-template-args.json`: `PROJECT_ROOT`, `PROJECT_NAME`, `PROJECT_DESCRIPTION`, `FRAMEWORKS`, `DIR_TREE`, `LANGUAGE_CONTEXT`, `FRAMEWORK_CONTEXT`, `FILE_NODES_JSON`, `IMPORT_EDGES_JSON`, `ALL_EDGES_JSON`, `PREVIOUS_LAYERS_JSON`. If a detected language/framework has no addendum, continue without it.

After it completes, normalize the layers:
```bash
python3 "$SKILL_DIR/scripts/normalize_layers.py" "$PROJECT_ROOT"
```

**Incremental updates:** always re-run architecture on the full merged node set (layer assignments may shift); pass prior layers via `PREVIOUS_LAYERS_JSON` for naming consistency.

---

## Phase 5 — REVIEW

1. Assemble the full KnowledgeGraph object from `scan-result.json`, reviewed `assembled-graph.json` nodes/edges, normalized `layers.json`, and the commit hash:
   ```bash
   python3 "$SKILL_DIR/scripts/assemble_knowledge_graph.py" "$PROJECT_ROOT" "<commit hash>"
   ```
   Shape: `{ version, project{name,languages,frameworks,description,analyzedAt,gitCommitHash}, nodes[], edges[], layers[] }`.

2. **Check `$ARGUMENTS` for `--review`** and run the matching path:

   **Default (no `--review`) — deterministic validation.** Runs referential-integrity, completeness, layer-coverage, uniqueness, quality, and (via `--scan-result`) scan-coverage checks; writes the review payload (`scriptCompleted`, `issues`, `warnings`, `stats`):
   ```bash
   "$PLUGIN_ROOT/packages/rust/run.sh" validate_graph \
     "$UA_DIR/intermediate/assembled-graph.json" \
     "$UA_DIR/intermediate/review.json" \
     --scan-result "$UA_DIR/intermediate/scan-result.json"
   ```
   On non-zero exit, diagnose from stderr (usually unreadable/malformed graph) and retry once. Approved when `issues` is empty (warnings are OK).

   **`--review` — full LLM reviewer.** Dispatch a subagent using the `graph-reviewer` agent (`$PLUGIN_ROOT/agents/graph-reviewer.md`) and template `$SKILL_DIR/prompts/graph-reviewer-dispatch.md`. Fill args: `PROJECT_ROOT`, `SCAN_FILE_LIST_JSON`, `PHASE_WARNINGS`.

3. Read `intermediate/review.json`. For a review-only run, report the findings and STOP here.
4. **If `issues` is non-empty:** apply deterministic fixes, then re-validate:
   ```bash
   python3 "$SKILL_DIR/scripts/apply_review_fixes.py" "$PROJECT_ROOT"
   ```
   Run the Phase 5 validator again after applying fixes. If critical issues remain, retain the candidate in `intermediate/assembled-graph.json`, report the errors, and stop before SAVE. Preserve the last saved graph and its baseline.
5. **If `issues` is empty:** proceed to Phase 6.

---

## Phase 6 — SAVE

1. Save the graph (writes `knowledge-graph.json` and `intermediate/save-summary.json`):
   ```bash
   python3 "$SKILL_DIR/scripts/save_knowledge_graph.py" "$PROJECT_ROOT"
   ```

2. **Build the fingerprints baseline** — **must succeed before `meta.json` is written** (otherwise auto-update finds no baseline and escalates every commit to `FULL_UPDATE`, issue #152):
   ```bash
   python3 "$SKILL_DIR/scripts/write_fingerprint_input.py" "$PROJECT_ROOT" "<commit hash>"
   "$PLUGIN_ROOT/packages/rust/run.sh" build_fingerprints \
     "$UA_DIR/intermediate/fingerprint-input.json"
   ```
   **If it exits non-zero or stdout lacks `Fingerprints baseline:`, abort Phase 6 and report — do NOT write `meta.json`.**

3. Write `meta.json` (only after step 2 succeeded), using `analyzedFiles` from `save-summary.json`:
   ```bash
   python3 "$SKILL_DIR/scripts/write_meta.py" "$PROJECT_ROOT" "<commit hash>" "<files analyzed>"
   ```

4. Clean up intermediates, preserving `scan-result.json` and `save-summary.json`. Scratch files are moved to a timestamped `.trash-*` directory and remain available for recovery:
   ```bash
   "$SKILL_DIR/scripts/cleanup_intermediate.sh" "$PROJECT_ROOT"
   ```

5. Report a final summary from `intermediate/save-summary.json`: project name/description, files analyzed, nodes (by type), edges (by type), layers (with names), reviewer warnings, and the output path `$UA_DIR/knowledge-graph.json`.

6. Proceed to Phase 7 unless `--no-domain`. Do not auto-launch the dashboard.

---

## Phase 7 — DOMAIN

Derives domains, business flows, and process steps into `domain-graph.json` from the knowledge graph (no re-scanning).

**Skip condition:** if `--no-domain`, skip to the final step (dashboard instructions). Failed Phase 5 validation already stops the run before SAVE.

1. Derive domain context (writes `intermediate/domain-context.json`; read it as context):
   ```bash
   python3 "$SKILL_DIR/scripts/graph_domain_context.py" "$PROJECT_ROOT"
   ```

2. Dispatch a subagent using the `domain-analyzer` agent (`$PLUGIN_ROOT/agents/domain-analyzer.md`) and template `$SKILL_DIR/prompts/domain-analyzer-dispatch.md`. Fill args: `PROJECT_ROOT`, `CONTEXT_SOURCE` = `knowledge-graph`, `DOMAIN_CONTEXT_JSON` = contents of `domain-context.json`. Output: `intermediate/domain-analysis.json`. If it fails after one retry, report, skip to the final step, and continue — a missing domain graph must not block the saved knowledge graph.

3. Validate and save the domain graph (also cleans domain intermediates); include any warnings in the final report:
   ```bash
   python3 "$SKILL_DIR/scripts/save_domain_graph.py" "$PROJECT_ROOT"
   ```

4. **Print dashboard instructions — do NOT auto-launch:**
   > Knowledge graph ready. To explore it, run `/understand-dashboard` (or `make dev` from the repo). The dashboard shows the structural graph and, when present, the domain view from `domain-graph.json`.

   Include non-blocking validation warnings. Never claim an invalid candidate was saved successfully.

---

## Error Handling

- Retry a failed dispatch once with the observed failure context. If a required scan, batch, merge, architecture, or validation step still fails, stop dependent phases and retain intermediates for diagnosis. Domain generation is optional and may be skipped after reporting its failure.
- Track all warnings/errors per phase in `$PHASE_WARNINGS`. With `--review`, pass it to the Phase 5 reviewer; otherwise include it in the Phase 6 final report.
- Publish the graph and advance its baseline only after required outputs validate. Report missing parts explicitly; do not present a failed batch as a completed analysis.

---

## Reference Schemas

Authoritative contracts (do not duplicate schema tables here) under `$PLUGIN_ROOT/packages/rust/schemas/`:
`knowledge-graph.schema.json`, `graph-fragment.schema.json`, `project-scan-output.schema.json`, `file-analysis-context.schema.json`, `layers.schema.json`.
