# Deterministic Auto-Update Scripts

  ## Summary

  Move the deterministic parts of understand-anything-
  plugin/hooks/auto-update-prompt.md into Python modules
  under arch_analysis, using the existing Python
  structural extractor and fingerprint baseline format.
  The hook prompt should stop embedding temporary Node/
  Bash scripts and instead call these commands, leaving
  LLM work only for file-analyzer and architecture-
  analyzer dispatches.

  ## Key Changes

  - Add shared fingerprint logic in arch_analysis/
    fingerprints.py.
      - Refactor build_fingerprints.py to reuse it while
        preserving its current CLI.

      - Implement content hashing, structural fingerprint
        extraction, fingerprint comparison, update
        classification, and load-patch-save fingerprint
        writes.

      - Match current TypeScript semantics: NONE for
        identical hash, COSMETIC for same structure,
        STRUCTURAL for signature/import/export changes or
        files without structural support.

  - Add auto-update command modules:
      - auto_update_preflight.py: validate graph/meta,
        read commit hashes, collect changed files, filter
        source files, apply .understandignore, create
        intermediate/, write auto-update-state.json, and
        handle metadata-only stop cases.

      - auto_update_fingerprint_check.py: read state +
        fingerprints.json, compute changed-file
        fingerprints, write change-analysis.json, and
        update metadata on SKIP.

      - auto_update_prepare_batches.py: write changed-file
        input for compute_batches, run/reuse changed-file
        batching, and write a dispatch summary for the LLM
        file-analysis phase.

      - auto_update_apply_batches.py: prune old nodes/
        edges for changed/deleted files, write batch-
        existing.json, reuse merge normalization, and
        produce either a partial final graph or an
        architecture-rerun input graph.

      - auto_update_finalize.py: apply optional
        architecture layers, run lite validation cleanup,
        write knowledge-graph.json, patch fingerprints
        without clobbering unrelated entries, update
        meta.json, and clean intermediate files safely
        while preserving scan-result.json.

  - Add JSON contracts and validation.
      - Add pydantic models/schema generation for
        AutoUpdateState, ChangeAnalysis, FileChangeResult,
        UpdateDecision, and AutoUpdateSummary.

      - Outputs must include machine-readable status,
        action, reason, filesToReanalyze, newFiles,
        deletedFiles, cosmeticOnlyFiles, unchangedFiles,
        and metadataUpdated.

  - Update docs and command registration.
      - Add PDM scripts for each new module in
        pyproject.toml.

      - Update arch_analysis/README.md with the auto-
        update command flow.

      - Rewrite understand-anything-plugin/hooks/auto-
        update-prompt.md so each phase invokes the Python
        commands and reads their JSON outputs instead of
        writing inline scripts.

      - Keep LLM instructions only for targeted file re-
        analysis and architecture layer re-analysis.

  ## Test Plan

  - Unit test fingerprint behavior: unchanged, cosmetic
    body-only edits, added/removed functions/classes,
    changed params/return/export/imports, unsupported
    files, new files, and deleted files.

  - Regression test fingerprint patching: existing entries
    are preserved, deleted files are removed, changed
    files are patched, and a non-empty store is never
    overwritten with only the current batch.

  - CLI test preflight with temp git repos: missing graph/
    meta stops, unchanged commit stops, non-source changes
    update metadata, ignored source files update metadata,
    changed source files continue.

  - CLI test classification thresholds: SKIP,
    PARTIAL_UPDATE, ARCHITECTURE_UPDATE, and FULL_UPDATE.

  - Integration test auto-update apply/finalize using
    small fixture graphs: old changed-file nodes are
    pruned, fresh batch nodes merge in, dangling edges/
    layer entries are removed, new files get deterministic
    lite layer placement, and metadata is written only
    after fingerprint patch success.

  - Run pdm run pytest arch_analysis/tests and a targeted
    markdown grep to confirm auto-update-prompt.md no
    longer contains generated .mjs script bodies for
    ignore filtering or fingerprint patching.

    package.

  - No new runtime dependency is required beyond the
    existing Python dependencies.

  - Existing dirty working-tree changes must be preserved;
    implementation should edit only the files needed for
    this auto-update scripting work.

  - For architecture-level changes, deterministic scripts
    prepare and validate data, but the architecture-
    analyzer still owns semantic layer judgment.