---
description: Validate the saved knowledge graph and write the canonical review.json.
---

# /understand-validate-graph

Runs referential-integrity, completeness, layer-coverage, uniqueness, and quality
checks on the saved `knowledge-graph.json` and writes the review payload to the
canonical `.understand-anything/intermediate/review.json` (the same file
`/understand` Phase 5 produces). No LLM required.

Parse the supplied arguments into a project path; quote each path separately. Do not evaluate the raw argument text as shell code. The installer replaces `__PLUGIN_ROOT__` below.

```bash
"__PLUGIN_ROOT__/tools/commands/validate-graph/run.sh" "<project-root>"
```

Replace placeholders before execution.

The graph is approved when `issues` is empty (warnings are acceptable). Report
the issues/warnings; on non-zero exit, show the error.
