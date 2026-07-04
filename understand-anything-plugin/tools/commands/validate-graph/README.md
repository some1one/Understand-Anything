# validate-graph

Validate the project's saved knowledge graph — referential integrity,
completeness, layer coverage, uniqueness, and quality checks — and write the
review payload (`scriptCompleted`, `issues`, `warnings`, `stats`) to the
canonical `intermediate/review.json`, the same file `/understand`'s Phase 5
produces. If a `scan-result.json` is present it also cross-checks scan coverage.
Deterministic — no LLM.

**Wraps:** `arch_analysis.validate_graph`

```bash
run.sh <project-root>
```

- Validates `<project-root>/.understand-anything/knowledge-graph.json`.
- Writes `<project-root>/.understand-anything/intermediate/review.json`.
- The graph is approved when `issues` is empty (warnings are acceptable).
