---
name: understand-merge
description: Merge saved part and legacy graph fragments into the existing knowledge graph without re-analyzing source
argument-hint: "[]"
---

# /understand-merge

Merge saved fragments into `.understand-anything/knowledge-graph.json` without
re-running analysis. This is an additive merge: the existing merged graph is
the base. It does **not** remove old nodes when parts are deselected. To rebuild
the selected set and its architecture, use `understand` with `--full`.

A non-empty `config.includedParts` filters incoming graphs with a `part` field.
Legacy root-level fragments without one are also included. Nodes are deduped by
id (a real node beats a cross-part boundary stub), edges by (source, target,
type), and existing layers are unioned.

Read [host integration](../../HOSTS.md) for invocation, argument handling, and agent dispatch.

## Instructions

1. Set `SKILL_DIR` to the directory containing this `SKILL.md`. Check the Rust engine and get `PLUGIN_ROOT`:
   ```bash
   PLUGIN_ROOT="$("$SKILL_DIR/../understand/scripts/ensure_rust_engine.sh")"
   ```

2. Merge the selected partition graphs into `knowledge-graph.json`:
   ```bash
   "$PLUGIN_ROOT/packages/rust/run.sh" merge_subdomain_graphs "$PWD"
   ```
   Report the resulting node/edge/layer counts (from stderr).

3. If no partitions are found, tell the user to run `/understand` first. Otherwise, suggest `/understand-dashboard` to explore the merged graph.

> This does not re-run architecture/layer assignment or advance the fingerprint
> baseline. New nodes may lack layers. Use `understand` for a validated rebuild.
