# File Analyzer Batch Dispatch

## Arguments

- `PROJECT_ROOT`: Absolute path to the project being analyzed.
- `PROJECT_NAME`: Project name from `scan-result.json`.
- `PROJECT_DESCRIPTION`: Project description from `scan-result.json`.
- `LANGUAGES`: Languages from `scan-result.json`.
- `BATCH_INDEX`: Current batch index from `batches.json`.
- `TOTAL_BATCHES`: Total batch count from `batches.json`.
- `SKILL_DIR`: Directory containing `understand/SKILL.md`.
- `OUTPUT_PATH`: Batch output path. Use `batch-<BATCH_INDEX>.json` for single-file output or `batch-<BATCH_INDEX>-part-<k>.json` for split output.
- `BATCH_IMPORT_DATA_JSON`: `batches.json[i].batchImportData`.
- `NEIGHBOR_MAP_JSON`: `batches.json[i].neighborMap`.
- `BATCH_FILES`: Ordered list of files from `batches.json[i].files`, preserving `path`, `language`, `sizeLines`, and `fileCategory`.

## Additional Context

Project: `{{PROJECT_NAME}}` — `{{PROJECT_DESCRIPTION}}`

Languages: `{{LANGUAGES}}`

## Dispatch Prompt

Analyze these files and produce GraphNode and GraphEdge objects.

- Project root: `{{PROJECT_ROOT}}`
- Project: `{{PROJECT_NAME}}`
- Languages: `{{LANGUAGES}}`
- Batch: `{{BATCH_INDEX}}/{{TOTAL_BATCHES}}`
- Skill directory (for bundled scripts): `{{SKILL_DIR}}`
- Output: write to `{{OUTPUT_PATH}}`

Pre-resolved import data for this batch. Use this directly; do not re-resolve imports from source:

```json
{{BATCH_IMPORT_DATA_JSON}}
```

Cross-batch neighbors with exported symbols, for cross-batch edge confidence:

```json
{{NEIGHBOR_MAP_JSON}}
```

Files to analyze in this batch. Every entry must be passed through to `batchFiles` with all four fields: `path`, `language`, `sizeLines`, and `fileCategory`.

```text
{{BATCH_FILES}}
```

Output naming is per `BATCH_INDEX`; do not fuse output filenames. If several small batches are analyzed in one dispatch for token efficiency, still write one output file per original `batchIndex` using `batch-<batchIndex>.json` or `batch-<batchIndex>-part-<k>.json`.
