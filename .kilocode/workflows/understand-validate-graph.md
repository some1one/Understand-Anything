---
description: Validate the saved knowledge graph and write the canonical review.json.
---

# /understand-validate-graph

Run the deterministic **validate-graph** command from Understand-Anything. It
runs referential-integrity, completeness, layer-coverage, uniqueness, and
quality checks on the project's saved `knowledge-graph.json` and writes the
review payload to the canonical
`.understand-anything/intermediate/review.json` (the same file `/understand`
Phase 5 produces). No LLM required.

Execute this with the `bash` tool, forwarding `$ARGUMENTS` (`<project-root>`):

```bash
/home/justin/repos/Understand-Anything/.agents/understand-anything-plugin/tools/commands/validate-graph/run.sh $ARGUMENTS
```

The graph is approved when `issues` is empty (warnings are acceptable). Report
the issues/warnings; if it exits non-zero, show the error.
