---
name: understand-chat
description: Use when you need to ask questions about a codebase or understand code using a knowledge graph
argument-hint: [query]
---

# /understand-chat

Answer questions about this codebase using the knowledge graph at `.understand-anything/knowledge-graph.json`.

## Graph Structure Reference

- `project` — {name, description, languages, frameworks, analyzedAt, gitCommitHash}
- `nodes[]` — {id, type, name, filePath?, summary, tags[], complexity, languageNotes?}
  - Code types: file, function, class, module, concept
  - Non-code types: config, document, service, table, endpoint, pipeline, schema, resource
  - Domain/knowledge types: domain, flow, step, article, entity, topic, claim, source
  - IDs prefix with node type, e.g. `file:path`, `function:path:name`, `config:path`, `article:path`
- `edges[]` — {source, target, type, direction, weight}. Types: imports, contains, calls, depends_on, configures, documents, deploys, triggers, contains_flow, flow_step, related, cites
- `layers[]` — {id, name, description, nodeIds[]}

## Instructions

1. Set `SKILL_DIR` to the directory containing this `SKILL.md`.

2. Run the helper (loads project metadata, searches matching nodes, collects 1-hop edges, identifies relevant layers):
   ```bash
   python "$SKILL_DIR/scripts/query_graph.py" "$PWD" "$ARGUMENTS"
   ```

3. Answer the query using only the helper's relevant subgraph:
   - Reference specific files, functions, and relationships from the graph
   - Explain which layer(s) are relevant and why
   - Concise but thorough — link concepts to actual code locations
   - If nothing matches, say so and suggest related terms from the graph
