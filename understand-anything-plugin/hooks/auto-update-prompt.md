# Auto-update knowledge graph

Follow this workflow when a native hook reports a stale graph and the project's
`config.json` explicitly enables `autoUpdate`. Read [host integration](../HOSTS.md)
for dispatch and host conventions. Use the absolute project root in the hook
message; resolve the plugin root from this file's parent directory.

Resolve the project data directory before reading any artifacts:

```bash
UA_DIR=$(python3 "$PLUGIN_ROOT/scripts/data_directory.py" "$PROJECT_ROOT")
```

Use that directory for the entire update, including worker inputs and outputs.

An enabled hook authorizes this graph-maintenance workflow within the current
task's permissions. Honor instructions to stop and wait for an existing analysis
run to finish before starting another. Do not stage, commit, or modify source files.

Dictionary dependencies are discovered during installation and the explicit
[plugin maintenance skill](../skills/understand-update/SKILL.md). Keep this graph
workflow offline: do not invoke the dictionary downloader here. Graph publication
rebuilds project caches from configured system data and local fallback snapshots.

## Part-based graphs

Read `$UA_DIR/config.json`. If it contains
`includedParts`, read `$PLUGIN_ROOT/skills/understand/SKILL.md` and run its
incremental path for the supplied project root. Reuse the saved source/depth and
part selection. Refresh the scan, analyze affected or pending parts, merge, and
validate before publishing the new baseline.

Do not run the legacy file-only flow below on a part-based graph: it would leave
saved partitions stale, and a later partition merge would undo the update.

## Legacy graphs without partition selection

The deterministic commands below write JSON under
`$UA_DIR/intermediate/` and print a JSON summary. Inspect each
result before proceeding. Fingerprinting avoids semantic analysis for unchanged
structure, but does not prove that internal behavior is unchanged. This workflow
uses the host's model context; do not claim it consumes zero tokens.

The compatibility field `changedSourceFiles` includes all supported project
categories, including configuration, documentation, infrastructure, and data.
Do not narrow it to code extensions. Non-code content changes are conservative
structural changes because code declaration signatures do not describe them.

### 1. Check the baseline

```bash
"$PLUGIN_ROOT/packages/rust/run.sh" auto_update_preflight "$PROJECT_ROOT"
```

Read `auto-update-state.json`. On `STOP`, report its reason and stop.
`NO_GRAPH` or `NO_META` requires a normal analysis run; `UP_TO_DATE`,
`NO_CHANGES`, `NO_SOURCE_CHANGES`, and `ALL_IGNORED` require no semantic work.
`GENERATED_ONLY` also stops without advancing metadata: graph artifacts are not
evidence of newly analyzed source. Changes to user ignore rules still require
inventory reconciliation even when the rules live inside the data directory.
`DIRTY_WORKTREE` stops without changing the baseline. Report `dirtyPaths`; the
user must commit or stash those changes before an incremental update. Do not
stage, commit, stash, or discard their work automatically. Generated graph data
and ignored files do not block the update; ignore-rule changes do. Fingerprint
comparison, preparation, and finalization recheck HEAD and relevant worktree
changes, so source drift requires a new preflight instead of publishing against
the old revision.
`SCAN_FAILED` stops ignore-rule reconciliation when the inventory is incomplete.
Report `scanFailures`; retain the existing graph and baseline, resolve the read
or enumeration failures, and retry preflight. Missing scan entries are not proof
that files were deleted or excluded.
On `CONTINUE / PROCEED`, continue.

### 2. Compare structural fingerprints

```bash
"$PLUGIN_ROOT/packages/rust/run.sh" auto_update_fingerprint_check "$PROJECT_ROOT"
```

Read `change-analysis.json`:

- `SKIP`: metadata is already updated; report that semantic analysis was skipped.
- `FULL_UPDATE`: report the reason and recommend the analysis skill with `--full`.
- `PARTIAL_UPDATE` or `ARCHITECTURE_UPDATE`: continue; retain `rerunArchitecture`.

### 3. Analyze changed files

```bash
"$PLUGIN_ROOT/packages/rust/run.sh" auto_update_prepare_batches "$PROJECT_ROOT"
```

Read `dispatch-summary.json` and `batches.json`. For each batch, use the bundled
`agents/file-analyzer.md` and
`skills/understand/prompts/file-analyzer-batch-dispatch.md`, providing both roots,
batch index, project context, and required output path. The agent runs the
prepare/extract/seed/finalize commands and writes the canonical numbered batch
files (including split `batch-<N>-part-<K>.json` files when needed).

Verify outputs for every requested batch before pruning old nodes. Retry a failed
dispatch once; if it still fails, stop and retain intermediates. Do not finalize
an incomplete update or advance its baseline.

```bash
"$PLUGIN_ROOT/packages/rust/run.sh" auto_update_apply_batches "$PROJECT_ROOT"
```

This writes `merged-graph.json` and, when architecture must be refreshed,
`ua-arch-input.json`.

### 4. Refresh layers when required

If `rerunArchitecture` is true, dispatch `agents/architecture-analyzer.md` with
`intermediate/ua-arch-input.json` as its prepared input. Skip inventory generation.
Use that same input path for analysis and layer validation, write
`intermediate/layers.json`, and reuse prior names where the structure still fits.
Retry once on failure, then stop if required layers are still unavailable.

Otherwise, finalization performs the deterministic layer adjustment.

### 5. Save and report

```bash
"$PLUGIN_ROOT/packages/rust/run.sh" auto_update_finalize "$PROJECT_ROOT"
```

Read `intermediate/auto-update-summary.json`. Report files checked, structural
changes, skipped cosmetic files, node/edge counts, action, and output path.
A nonzero exit is a failed update; report the error and preserve diagnostic files.
Finalization compares reanalyzed symbols with the prepared source revisions before
publishing. On unresolved symbol loss, read `incremental-symbol-report.json` and
report the affected files and reasons. Keep `incremental-symbol-baseline.json`
and `incremental-edge-candidates.json` with the batch outputs for repair; do not remove old symbols or edit the report to
force success. If the report identifies unresolved files without source/identity
errors, run the bounded repair command once:

```bash
"$PLUGIN_ROOT/packages/rust/run.sh" auto_update_prepare_symbol_retry "$PROJECT_ROOT"
```

Use its new `dispatch-summary.json` and `batches.json` to analyze only the listed
files, passing the symbol report to the file analyzer. Successful files and prior
batch outputs are preserved. Apply the new batches, rerun architecture if requested,
and finalize again using the same steps above. If preparation rejects the retry or
validation still fails, stop and preserve the diagnostics; do not restart preparation
to obtain another attempt. The repair must retain newly discovered symbols as well
as the original baseline symbols. Parser failures, empty extraction, ambiguous
identities, and
compatible dynamic definitions do not establish deletion. Verified ID replacements
preserve inbound relationships from unchanged files.

Fingerprints are initially built by the analysis skill's Phase 6. Finalization
patches that store, preserving unaffected entries. The legacy flow updates the
structural graph; regenerate a domain view with a normal analysis run if needed.
