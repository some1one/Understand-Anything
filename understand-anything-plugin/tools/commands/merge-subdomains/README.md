# merge-subdomains

Merge subdomain graph fragments (e.g. `frontend-knowledge-graph.json`,
`backend-knowledge-graph.json`) into a single `knowledge-graph.json`,
deduplicating nodes and edges. Any existing `knowledge-graph.json` is loaded as
the base, so subdomain data wins on conflict.

**Wraps:** `understand-anything-rs merge_subdomain_graphs`

```bash
run.sh <project-root> [fragment.json ...]
```

- No fragment args: discovers root-level `*knowledge-graph*.json` and
  `partitions/*.knowledge-graph.json` under `<project-root>/.understand-anything/`,
  excluding the merged `knowledge-graph.json`. A non-empty `config.includedParts`
  filters graphs with a `part` field; legacy graphs without one remain included.
- Explicit fragment paths bypass selection filtering. The existing merged graph
  remains the base, so this command does not remove previously included nodes.
- Embeddings are (re)generated afterward when an embedding API key is configured.
