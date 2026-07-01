# Domain Analyzer Dispatch

## Arguments

- `PROJECT_ROOT`: Absolute path to the project being analyzed.
- `CONTEXT_SOURCE`: Either `domain-context.json` from the lightweight scan or structured context derived from `knowledge-graph.json`.
- `DOMAIN_CONTEXT_JSON`: The context payload to pass to the domain analyzer.

## Dispatch Prompt

Analyze the project domain using the provided context. Extract business domains, business flows, and process steps.

- Project root: `{{PROJECT_ROOT}}`
- Context source: `{{CONTEXT_SOURCE}}`
- Write output to: `{{PROJECT_ROOT}}/.understand-anything/intermediate/domain-analysis.json`

Domain analysis context:

```json
{{DOMAIN_CONTEXT_JSON}}
```
