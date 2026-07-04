---
description: Merge subdomain knowledge-graph fragments into a single knowledge-graph.json.
---

# /understand-merge-subdomains

Run the deterministic **merge-subdomains** command from Understand-Anything. It
merges `*-knowledge-graph.json` fragments into a single `knowledge-graph.json`,
deduplicating nodes and edges (existing graph used as the base).

Execute this with the `bash` tool, forwarding `$ARGUMENTS`
(`<project-root> [fragment.json ...]`; with no fragments it auto-discovers them
under `.understand-anything/`):

```bash
__PLUGIN_ROOT__/tools/commands/merge-subdomains/run.sh $ARGUMENTS
```

Report the merge summary from stderr. If it exits non-zero, show the error.
