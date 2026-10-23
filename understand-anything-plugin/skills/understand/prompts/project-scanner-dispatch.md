# Project Scanner Dispatch

## Arguments

- `PROJECT_ROOT`: Absolute path to the project being analyzed.
- `README_CONTENT`: First 3000 characters of the project README, or an empty string.
- `MANIFEST_CONTENT`: Contents of the primary project manifest, or an empty string.

## Additional Context

Project README (first 3000 chars):

```text
{{README_CONTENT}}
```

Package manifest:

```text
{{MANIFEST_CONTENT}}
```

README and manifest are authoritative for project name, description, and framework detection; prefer them over heuristics.

## Dispatch Prompt

Scan this project directory to discover all project files (including non-code: configs, docs, infrastructure, data, scripts, markup). Detect languages and frameworks.

- Project root: `{{PROJECT_ROOT}}`
- Write output to: `{{PROJECT_ROOT}}/.ua/intermediate/scan-result.json`
