# Assemble Reviewer Dispatch

## Arguments

- `PROJECT_ROOT`: Absolute path to the project being analyzed.
- `MERGE_REPORT`: Full stderr output from `arch_analysis.merge_batch_graphs`.
- `IMPORT_MAP_JSON`: Import map from `scan-result.json#importMap`.

## Dispatch Prompt

Review the assembled graph at `{{PROJECT_ROOT}}/.understand-anything/intermediate/assembled-graph.json`.

- Project root: `{{PROJECT_ROOT}}`
- Batch files: `{{PROJECT_ROOT}}/.understand-anything/intermediate/batch-*.json`
- Write review output to: `{{PROJECT_ROOT}}/.understand-anything/intermediate/assemble-review.json`

Merge script report:

```text
{{MERGE_REPORT}}
```

Import map for cross-batch edge verification:

```json
{{IMPORT_MAP_JSON}}
```
