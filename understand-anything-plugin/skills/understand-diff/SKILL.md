---
name: understand-diff
description: Use when you need to analyze git diffs or pull requests to understand what changed, affected components, and risks
---

# /understand-diff

Resolve `UA_DIR` after resolving `PLUGIN_ROOT` and `PROJECT_ROOT`, before reading
or writing project artifacts:

```bash
UA_DIR=$(python3 "$PLUGIN_ROOT/scripts/data_directory.py" "$PROJECT_ROOT")
```

Use this absolute directory throughout the workflow and pass it to workers.
It selects `.ua` for new projects and retains an existing legacy directory;
see [host integration](../../HOSTS.md) for the selection rules.


Analyze the current code changes against the knowledge graph at `$UA_DIR/knowledge-graph.json`.

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

2. Run the helper. Pass a base branch as the optional second argument if the user specified one, else omit it. The helper compares feature branches against the local origin default-branch reference or an available main/master branch. On the default branch, or without a usable base, it includes staged and unstaged changes against HEAD. Gathers changed files, extracts changed/affected nodes, finds touched layers, and writes `$UA_DIR/diff-overlay.json`.
   ```bash
   python3 "$SKILL_DIR/scripts/diff_context.py" "$PWD" [base-branch]
   ```

3. Provide structured analysis from the helper output:
   - **Changed Components**: directly modified (with summaries from matched nodes)
   - **Affected Components**: potentially impacted (from 1-hop edges)
   - **Affected Layers**: touched architectural layers and cross-layer concerns
   - **Risk Assessment**: from node `complexity`, number of cross-layer edges, and blast radius (count of affected components)
   - Suggest what to review carefully and potential issues

4. Tell the user they can run `/understand-anything:understand-dashboard` to see the diff overlay visually.
