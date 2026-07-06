---
description: Merge subdomain knowledge-graph fragments into a single knowledge-graph.json.
---

# /understand-merge-subdomains

Merges `*-knowledge-graph.json` fragments into a single `knowledge-graph.json`,
deduplicating nodes and edges (existing graph is the base).

Execute with the `bash` tool, forwarding `$ARGUMENTS`
(`<project-root> [fragment.json ...]`; with no fragments it auto-discovers them
under `.understand-anything/`):

```bash
__PLUGIN_ROOT__/tools/commands/merge-subdomains/run.sh $ARGUMENTS
```

Report the merge summary from stderr. On non-zero exit, show the error.
