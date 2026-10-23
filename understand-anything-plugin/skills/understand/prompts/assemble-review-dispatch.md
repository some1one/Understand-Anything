# Assemble Reviewer Dispatch

## Arguments

- `PROJECT_ROOT`: Absolute path to the project being analyzed.
- `UA_DIR`: Absolute project data directory resolved by the caller; may be `.ua` or the retained legacy directory.
- `MERGE_REPORT`: Full stderr output from `understand-anything-rs merge_batch_graphs`.
- `IMPORT_MAP_JSON`: Import map from `scan-result.json#importMap`.

## Dispatch Prompt

Review the assembled graph at `{{UA_DIR}}/intermediate/assembled-graph.json`.

- Project root: `{{PROJECT_ROOT}}`
- Saved part graphs: `{{UA_DIR}}/partitions/*.knowledge-graph.json`. Per-part batch scratch is cleared after assembly.
- Write review output to: `{{UA_DIR}}/intermediate/assemble-review.json`

Merge script report:

```text
{{MERGE_REPORT}}
```

Import map for cross-batch edge verification:

```json
{{IMPORT_MAP_JSON}}
```
