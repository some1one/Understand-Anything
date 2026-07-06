# merge-subdomains

Merge subdomain graph fragments (e.g. `frontend-knowledge-graph.json`,
`backend-knowledge-graph.json`) into a single `knowledge-graph.json`,
deduplicating nodes and edges. Any existing `knowledge-graph.json` is loaded as
the base, so subdomain data wins on conflict.

**Wraps:** `arch_analysis.merge_subdomain_graphs`

```bash
run.sh <project-root> [fragment.json ...]
```

- No fragment args: auto-discovers `*knowledge-graph*.json` in
  `<project-root>/.understand-anything/` (excluding `knowledge-graph.json`).
- Embeddings are (re)generated afterward when an embedding API key is configured.
