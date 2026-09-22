# Assemble Reviewer Dispatch

## Arguments

- `PROJECT_ROOT`: Absolute path to the project being analyzed.
- `MERGE_REPORT`: Full stderr output from `understand_core.merge_batch_graphs`.
- `IMPORT_MAP_JSON`: Import map from `scan-result.json#importMap`.

## Dispatch Prompt

Review the assembled graph at `{{PROJECT_ROOT}}/.understand-anything/intermediate/assembled-graph.json`.

- Project root: `{{PROJECT_ROOT}}`
- Saved part graphs: `{{PROJECT_ROOT}}/.understand-anything/partitions/*.knowledge-graph.json`. Per-part batch scratch is cleared after assembly.
- Write review output to: `{{PROJECT_ROOT}}/.understand-anything/intermediate/assemble-review.json`

Merge script report:

```text
{{MERGE_REPORT}}
```

Import map for cross-batch edge verification:

```json
{{IMPORT_MAP_JSON}}
```
