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

Use this context to produce a more accurate project name, description, and framework detection. The README and manifest are authoritative; prefer their information over heuristics.

## Dispatch Prompt

Scan this project directory to discover all project files, including non-code files like configs, docs, infrastructure, data, scripts, and markup. Detect languages and frameworks.

- Project root: `{{PROJECT_ROOT}}`
- Write output to: `{{PROJECT_ROOT}}/.understand-anything/intermediate/scan-result.json`
