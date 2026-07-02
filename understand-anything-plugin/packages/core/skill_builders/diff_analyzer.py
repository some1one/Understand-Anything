"""Map changed files to graph nodes and assess ripple effects.

Port of ``diff-analyzer.ts``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from understand_core import GraphEdge, GraphNode, KnowledgeGraph, Layer


class DiffContext(BaseModel):
    """Changed/affected slice of the graph for a set of changed files."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    projectName: str
    changedFiles: list[str]
    changedNodes: list[GraphNode]
    affectedNodes: list[GraphNode]
    impactedEdges: list[GraphEdge]
    affectedLayers: list[Layer]
    unmappedFiles: list[str]


def build_diff_context(graph: KnowledgeGraph, changed_files: list[str]) -> DiffContext:
    """Map changed file paths to nodes and find the downstream ripple effect."""
    nodes, edges, layers = graph.nodes, graph.edges, graph.layers

    changed_node_ids: set[str] = set()
    unmapped_files: list[str] = []

    for file in changed_files:
        mapped = False
        for node in nodes:
            if node.filePath == file:
                changed_node_ids.add(node.id)
                mapped = True
        if not mapped:
            unmapped_files.append(file)

    # Also include "contains" children of changed file nodes.
    for edge in edges:
        if edge.type == "contains" and edge.source in changed_node_ids:
            changed_node_ids.add(edge.target)

    changed_nodes = [n for n in nodes if n.id in changed_node_ids]

    # Find affected nodes: 1-hop neighbors of changed nodes (excluding changed).
    affected_node_ids: set[str] = set()
    impacted_edges: list[GraphEdge] = []

    for edge in edges:
        source_changed = edge.source in changed_node_ids
        target_changed = edge.target in changed_node_ids

        if source_changed or target_changed:
            impacted_edges.append(edge)
            if source_changed and edge.target not in changed_node_ids:
                affected_node_ids.add(edge.target)
            if target_changed and edge.source not in changed_node_ids:
                affected_node_ids.add(edge.source)

    affected_nodes = [n for n in nodes if n.id in affected_node_ids]

    all_impacted_ids = changed_node_ids | affected_node_ids
    affected_layers = [
        layer
        for layer in layers
        if any(node_id in all_impacted_ids for node_id in layer.nodeIds)
    ]

    return DiffContext(
        projectName=graph.project.name,
        changedFiles=changed_files,
        changedNodes=changed_nodes,
        affectedNodes=affected_nodes,
        impactedEdges=impacted_edges,
        affectedLayers=affected_layers,
        unmappedFiles=unmapped_files,
    )


def format_diff_analysis(ctx: DiffContext) -> str:
    """Render the diff analysis as structured markdown."""
    lines: list[str] = []

    lines.append(f"# Diff Analysis: {ctx.projectName}")
    lines.append("")

    lines.append("## Changed Components")
    lines.append("")
    if not ctx.changedNodes:
        lines.append("No mapped components found for changed files.")
    else:
        for node in ctx.changedNodes:
            lines.append(f"- **{node.name}** ({node.type}) — {node.summary}")
            if node.filePath:
                lines.append(f"  - File: `{node.filePath}`")
            lines.append(f"  - Complexity: {node.complexity}")
    lines.append("")

    lines.append("## Affected Components")
    lines.append("")
    if not ctx.affectedNodes:
        lines.append("No downstream impact detected.")
    else:
        lines.append(
            "These components are connected to changed code and may need attention:"
        )
        lines.append("")
        for node in ctx.affectedNodes:
            lines.append(f"- **{node.name}** ({node.type}) — {node.summary}")
    lines.append("")

    lines.append("## Affected Layers")
    lines.append("")
    if not ctx.affectedLayers:
        lines.append("No layers affected.")
    else:
        for layer in ctx.affectedLayers:
            lines.append(f"- **{layer.name}**: {layer.description}")
    lines.append("")

    if ctx.impactedEdges:
        lines.append("## Impacted Relationships")
        lines.append("")
        for edge in ctx.impactedEdges:
            lines.append(f"- {edge.source} --[{edge.type}]--> {edge.target}")
        lines.append("")

    if ctx.unmappedFiles:
        lines.append("## Unmapped Files")
        lines.append("")
        lines.append("These changed files are not yet in the knowledge graph:")
        lines.append("")
        for f in ctx.unmappedFiles:
            lines.append(f"- `{f}`")
        lines.append("")

    lines.append("## Risk Assessment")
    lines.append("")
    complex_changes = [n for n in ctx.changedNodes if n.complexity == "complex"]
    cross_layer_count = len({layer.id for layer in ctx.affectedLayers})

    if complex_changes:
        names = ", ".join(n.name for n in complex_changes)
        lines.append(
            f"- **High complexity**: {len(complex_changes)} complex component(s) changed: {names}"
        )
    if cross_layer_count > 1:
        lines.append(
            f"- **Cross-layer impact**: Changes span {cross_layer_count} architectural layers"
        )
    if len(ctx.affectedNodes) > 5:
        lines.append(
            f"- **Wide blast radius**: {len(ctx.affectedNodes)} components affected downstream"
        )
    if ctx.unmappedFiles:
        lines.append(
            f"- **New/unmapped files**: {len(ctx.unmappedFiles)} files not in the knowledge graph (may need re-analysis)"
        )
    if (
        not complex_changes
        and cross_layer_count <= 1
        and len(ctx.affectedNodes) <= 5
        and not ctx.unmappedFiles
    ):
        lines.append(
            "- **Low risk**: Changes are localized with limited downstream impact."
        )
    lines.append("")

    return "\n".join(lines)
