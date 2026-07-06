---
name: understand-explain
description: Use when you need a deep-dive explanation of a specific file, function, or module in the codebase
argument-hint: [file-path]
---

# /understand-explain

Provide a thorough, in-depth explanation of a specific code component.

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

2. Run the helper (finds the target node, connected edges, neighboring nodes, layer membership, and a source excerpt):
   ```bash
   python "$SKILL_DIR/scripts/component_context.py" "$PWD" "$ARGUMENTS"
   ```

3. Explain the component in context:
   - Its role in the architecture (which layer, why it exists)
   - Internal structure (functions/classes it contains — from `contains` edges)
   - External connections (imports, callers, dependencies — from edges)
   - Data flow (inputs → processing → outputs — from source code)
   - Explain clearly, assuming the reader may not know the language
   - Highlight patterns, idioms, or complexity worth understanding
