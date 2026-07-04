# Graph Reviewer Dispatch

## Arguments

- `PROJECT_ROOT`: Absolute path to the project being analyzed.
- `SCAN_FILE_LIST_JSON`: List of `{path, sizeLines}` entries from `scan-result.json`.
- `PHASE_WARNINGS`: Batch failures, skipped files, or warnings from Phases 2-4.

## Additional Context

Phase 1 scan results (file inventory):

```json
{{SCAN_FILE_LIST_JSON}}
```

Phase warnings/errors accumulated during analysis:

```text
{{PHASE_WARNINGS}}
```

Scan coverage is cross-checked deterministically. The graph-reviewer runs `validate_graph` with `--scan-result`, which flags any scanned file lacking a node and any node referencing a file absent from the scan inventory. Do not cross-validate coverage by hand.

## Dispatch Prompt

Validate the knowledge graph at `{{PROJECT_ROOT}}/.understand-anything/intermediate/assembled-graph.json`.

- Project root: `{{PROJECT_ROOT}}`
- Read the graph file and validate it for completeness and correctness.
- Write output to: `{{PROJECT_ROOT}}/.understand-anything/intermediate/review.json`
