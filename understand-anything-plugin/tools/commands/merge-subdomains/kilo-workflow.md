---
description: Merge subdomain knowledge-graph fragments into a single knowledge-graph.json.
---

# /understand-merge-subdomains

Merges `*-knowledge-graph.json` fragments into a single `knowledge-graph.json`,
deduplicating nodes and edges (existing graph is the base).

Parse the supplied arguments into a project path and optional fragment paths; quote each path separately. Do not evaluate the raw argument text as shell code. The installer replaces `__PLUGIN_ROOT__` below.

```bash
"__PLUGIN_ROOT__/tools/commands/merge-subdomains/run.sh" "<project-root>" ["<fragment.json>" ...]
```

Replace placeholders before execution; omit the bracketed fragment list to use automatic discovery.

Report the merge summary from stderr. On non-zero exit, show the error.
