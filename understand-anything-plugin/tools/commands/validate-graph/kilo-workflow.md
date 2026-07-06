---
description: Validate the saved knowledge graph and write the canonical review.json.
---

# /understand-validate-graph

Runs referential-integrity, completeness, layer-coverage, uniqueness, and quality
checks on the saved `knowledge-graph.json` and writes the review payload to the
canonical `.understand-anything/intermediate/review.json` (the same file
`/understand` Phase 5 produces). No LLM required.

Execute with the `bash` tool, forwarding `$ARGUMENTS` (`<project-root>`):

```bash
__PLUGIN_ROOT__/tools/commands/validate-graph/run.sh $ARGUMENTS
```

The graph is approved when `issues` is empty (warnings are acceptable). Report
the issues/warnings; on non-zero exit, show the error.
