---
name: understand-domain
description: Extract business domain knowledge from a codebase and generate an interactive domain flow graph. Works standalone (lightweight scan) or derives from an existing /understand knowledge graph.
argument-hint: [--full]
---

# /understand-domain

Extracts business domain knowledge — domains, business flows, and process steps — from a codebase and produces an interactive horizontal flow graph in the dashboard.

## How It Works

- If a knowledge graph already exists (`.understand-anything/knowledge-graph.json`), derives domain knowledge from it (cheap, no file scanning)
- If no knowledge graph exists, performs a lightweight scan: file tree + entry point detection + sampled files
- Use `--full` flag to force a fresh scan even if a knowledge graph exists

## Instructions

### Phase 0: Resolve `PROJECT_ROOT`

Set `SKILL_DIR` to the directory containing this `SKILL.md`, then resolve `PROJECT_ROOT` with the bundled Bash script:

```bash
PROJECT_ROOT="$("$SKILL_DIR/scripts/resolve_project_root.sh" "$PWD")"
```

Use `$PROJECT_ROOT` (not the bare CWD) for every reference to "the current project" / `<project-root>` in subsequent phases.

**Important:** do **not** assume the plugin root is simply two directories above the skill path string. In many installations `~/.agents/skills/understand-domain` is a symlink into the real plugin checkout. Prefer runtime-provided plugin roots first (for Claude), then fall back to universal symlinks, skill symlink resolution, and common clone-based install paths.

Resolve the plugin root with the bundled Bash script:

```bash
PLUGIN_ROOT="$("$SKILL_DIR/scripts/resolve_plugin_root.sh")"
```

Use `$PLUGIN_ROOT` for every reference to agent definitions in subsequent phases.

### Phase 1: Detect Existing Graph

1. Check if `$PROJECT_ROOT/.understand-anything/knowledge-graph.json` exists
2. If it exists AND `--full` was NOT passed → proceed to Phase 3 (derive from graph)
3. Otherwise → proceed to Phase 2 (lightweight scan)

### Phase 2: Lightweight Scan (Path 1)

The preprocessing script does NOT produce a domain graph — it produces **raw material** (file tree, entry points, exports/imports) so the domain-analyzer agent can focus on the actual domain analysis instead of spending dozens of tool calls exploring the codebase. Think of it as a cheat sheet: cheap Python preprocessing → expensive LLM gets a clean, small input → better results for less cost.

1. Run the preprocessing module from the `arch_analysis` package (from its project root), passing `$PROJECT_ROOT` from Phase 0:
   ```
   python -m arch_analysis.extract_domain_context "$PROJECT_ROOT"
   ```
   This outputs `$PROJECT_ROOT/.understand-anything/intermediate/domain-context.json` containing:
   - File tree (respecting `.gitignore`)
   - Detected entry points (HTTP routes, CLI commands, event handlers, cron jobs, exported handlers)
   - File signatures (exports, imports per file)
   - Code snippets for each entry point (signature + first few lines)
   - Project metadata (package.json, README, etc.)
2. Read the generated `domain-context.json` as context for Phase 4
3. Proceed to Phase 4

### Phase 3: Derive from Existing Graph (Path 2)

1. Convert `$PROJECT_ROOT/.understand-anything/knowledge-graph.json` into domain-analyzer context with the bundled deterministic helper:
   ```bash
   python "$SKILL_DIR/scripts/graph_domain_context.py" "$PROJECT_ROOT"
   ```
2. Read the generated `domain-context.json` as context for Phase 4.
3. Proceed to Phase 4.

### Phase 4: Domain Analysis

1. Read the domain-analyzer agent prompt from `$PLUGIN_ROOT/agents/domain-analyzer.md`.
2. Dispatch a subagent with the bundled prompt template `prompts/domain-analyzer-dispatch.md`.
3. Fill the template arguments from Phase 2 or Phase 3 context:
   - `PROJECT_ROOT`
   - `CONTEXT_SOURCE`
   - `DOMAIN_CONTEXT_JSON`
4. The agent writes its output to `$PROJECT_ROOT/.understand-anything/intermediate/domain-analysis.json`.

### Phase 5: Validate and Save

1. Save the domain graph and clean deterministic intermediate files with the bundled Python helper:
   ```bash
   python "$SKILL_DIR/scripts/save_domain_graph.py" "$PROJECT_ROOT"
   ```
2. Read the helper's JSON output and include any warnings in the final report.

### Phase 6: Launch Dashboard

1. Auto-trigger `/understand-dashboard` to visualize the domain graph
2. The dashboard will detect `domain-graph.json` and show the domain view by default
