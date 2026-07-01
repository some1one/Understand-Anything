# Architecture Analyzer Dispatch

## Arguments

- `PROJECT_ROOT`: Absolute path to the project being analyzed.
- `PROJECT_NAME`: Project name from `scan-result.json`.
- `PROJECT_DESCRIPTION`: Project description from `scan-result.json`.
- `FRAMEWORKS`: Frameworks detected in Phase 1.
- `DIR_TREE`: Top-level directory tree from `capture_project_context.py`.
- `LANGUAGE_CONTEXT`: Concatenated language addenda from `languages/*.md`.
- `FRAMEWORK_CONTEXT`: Concatenated framework addenda from `frameworks/*.md`.
- `FILE_NODES_JSON`: File-level nodes as `{id, type, name, filePath, summary, tags}`.
- `IMPORT_EDGES_JSON`: Edges with type `imports`.
- `ALL_EDGES_JSON`: All graph edges.
- `PREVIOUS_LAYERS_JSON`: Previous layer definitions for incremental updates, or an empty array.

## Additional Context

Frameworks detected: `{{FRAMEWORKS}}`

Directory tree (top 2 levels):

```text
{{DIR_TREE}}
```

Language context:

```markdown
{{LANGUAGE_CONTEXT}}
```

Framework context:

```markdown
{{FRAMEWORK_CONTEXT}}
```

Use the directory tree, language context, and framework addenda to inform layer assignments. Directory structure is strong evidence for layer boundaries. Non-code files such as config, docs, infrastructure, data, scripts, and markup should be assigned to appropriate layers.

Previous layer definitions, for naming consistency during incremental updates:

```json
{{PREVIOUS_LAYERS_JSON}}
```

Maintain the same layer names and IDs where possible. Only add or remove layers if the file structure has materially changed.

## Dispatch Prompt

Analyze this codebase's structure to identify architectural layers.

- Project root: `{{PROJECT_ROOT}}`
- Write output to: `{{PROJECT_ROOT}}/.understand-anything/intermediate/layers.json`
- Project: `{{PROJECT_NAME}}` — `{{PROJECT_DESCRIPTION}}`

File nodes:

```json
{{FILE_NODES_JSON}}
```

Import edges:

```json
{{IMPORT_EDGES_JSON}}
```

All edges:

```json
{{ALL_EDGES_JSON}}
```
