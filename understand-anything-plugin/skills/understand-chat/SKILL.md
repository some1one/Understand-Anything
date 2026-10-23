---
name: understand-chat
description: Use when you need to ask questions about a codebase or understand code using a knowledge graph
argument-hint: "[query]"
---

# /understand-chat

Resolve `UA_DIR` after resolving `PLUGIN_ROOT` and `PROJECT_ROOT`, before reading
or writing project artifacts:

```bash
UA_DIR=$(python3 "$PLUGIN_ROOT/scripts/data_directory.py" "$PROJECT_ROOT")
```

Use this absolute directory throughout the workflow and pass it to workers.
It selects `.ua` for new projects and retains an existing legacy directory;
see [host integration](../../HOSTS.md) for the selection rules.


Answer questions about this codebase using the knowledge graph at `$UA_DIR/knowledge-graph.json`.

## Graph Structure Reference

- `project` — {name, description, languages, frameworks, analyzedAt, gitCommitHash}
- `nodes[]` — {id, type, name, filePath?, summary, tags[], complexity, languageNotes?}
  - Code types: file, function, class, module, concept
  - Non-code types: config, document, service, table, endpoint, pipeline, schema, resource
  - Domain/knowledge types: domain, flow, step, article, entity, topic, claim, source
  - IDs prefix with node type, e.g. `file:path`, `function:path:name`, `config:path`, `article:path`
- `edges[]` — {source, target, type, direction, weight}. Types: imports, contains, calls, depends_on, configures, documents, deploys, triggers, contains_flow, flow_step, related, cites
- `layers[]` — {id, name, description, nodeIds[]}

Read [host integration](../../HOSTS.md) for invocation, argument handling, and agent dispatch.

## Instructions

1. Set `SKILL_DIR` to the directory containing this `SKILL.md`.

2. Run the helper (loads project metadata, searches matching nodes, collects 1-hop edges, identifies relevant layers):
   ```bash
   python3 "$SKILL_DIR/scripts/query_graph.py" "$PWD" "$ARGUMENTS"
   ```

If the helper reports inaccessible dictionaries, relay its configuration path and
repair instructions: updated system paths (`--lemma-resources`/`--cspell-root`),
or latest repo-local data (`--prefer-local --local-dir` through
[understand-update](../understand-update/SKILL.md)). Do not silently download data
or treat an error as an empty result. Recommend `/understand --full` after repair.

3. Use the helper's relevant subgraph to locate evidence, then inspect current source when the question concerns current behavior:
   - Reference specific files, functions, and relationships from the graph
   - Explain which layer(s) are relevant and why
   - Concise but thorough — link concepts to actual code locations
   - If nothing matches, say so and suggest related terms from the graph
