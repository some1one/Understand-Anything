---
name: understand-onboard
description: Use when you need to generate an onboarding guide for new team members joining a project
---

# /understand-onboard

Generate a comprehensive onboarding guide from the project's knowledge graph.

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

2. Run the helper (loads project metadata, layers, file-level nodes, complexity hotspots):
   ```bash
   python "$SKILL_DIR/scripts/onboarding_context.py" "$PWD"
   ```

3. Generate the guide with these sections:
   - **Project Overview**: name, languages, frameworks, description (from project metadata)
   - **Architecture Layers**: each layer's name, description, key files (from layers + file nodes)
   - **Key Concepts**: important patterns and design decisions (from node summaries and tags)
   - **Recommended Reading Path**: order for exploring the codebase, starting from entry-point files and following imports/calls edges through the layers
   - **File Map**: what each key file does (from file-level nodes, organized by layer)
   - **Complexity Hotspots**: areas to approach carefully (from complexity values)

4. Format as clean markdown.
5. Offer to save to `docs/ONBOARDING.md` in the project.
6. Suggest the user commit it to the repo for the team.
