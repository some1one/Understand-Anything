"""Build an explain context for a file or function — port of ``explain-builder.ts``."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from understand_core import GraphEdge, GraphNode, KnowledgeGraph, Layer


class ExplainContext(BaseModel):
    """Context for explaining a single file or function in the graph."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    projectName: str
    path: str
    targetNode: GraphNode | None
    childNodes: list[GraphNode]
    connectedNodes: list[GraphNode]
    relevantEdges: list[GraphEdge]
    layer: Layer | None


def _opt(obj: object, name: str) -> object | None:
    """Read an optional/extra pydantic field (e.g. ``languageNotes``)."""
    return getattr(obj, name, None)


def build_explain_context(graph: KnowledgeGraph, path: str) -> ExplainContext:
    """Resolve ``path`` to a node and gather children, neighbors, and layer.

    Supports file paths (``src/auth.ts``) and ``path:function`` form
    (``src/auth.ts:login``).
    """
    nodes, edges, layers = graph.nodes, graph.edges, graph.layers

    target_node: GraphNode | None = None

    # Check for path:function format (e.g. "src/auth.ts:login").
    colon_idx = path.rfind(":")
    if colon_idx > 0 and "://" not in path:
        file_path = path[:colon_idx]
        func_name = path[colon_idx + 1 :]
        target_node = next(
            (n for n in nodes if n.filePath == file_path and n.name == func_name),
            None,
        )

    # Fall back to file path match.
    if target_node is None:
        target_node = next((n for n in nodes if n.filePath == path), None)

    if target_node is None:
        return ExplainContext(
            projectName=graph.project.name,
            path=path,
            targetNode=None,
            childNodes=[],
            connectedNodes=[],
            relevantEdges=[],
            layer=None,
        )

    # Find child nodes (contained by this node via "contains" edges).
    child_nodes = [
        n
        for n in nodes
        if any(
            e.source == target_node.id and e.target == n.id and e.type == "contains"
            for e in edges
        )
    ]

    all_related_ids = {target_node.id, *(n.id for n in child_nodes)}

    # Find connected nodes (1-hop neighbors, excluding children and self).
    connected_ids: set[str] = set()
    relevant_edges: list[GraphEdge] = []

    for edge in edges:
        if edge.source in all_related_ids or edge.target in all_related_ids:
            relevant_edges.append(edge)
            if edge.source in all_related_ids and edge.target not in all_related_ids:
                connected_ids.add(edge.target)
            if edge.target in all_related_ids and edge.source not in all_related_ids:
                connected_ids.add(edge.source)

    connected_nodes = [n for n in nodes if n.id in connected_ids]

    layer = next((l for l in layers if target_node.id in l.nodeIds), None)

    return ExplainContext(
        projectName=graph.project.name,
        path=path,
        targetNode=target_node,
        childNodes=child_nodes,
        connectedNodes=connected_nodes,
        relevantEdges=relevant_edges,
        layer=layer,
    )


def format_explain_prompt(ctx: ExplainContext) -> str:
    """Render the explain context as a structured LLM prompt."""
    if ctx.targetNode is None:
        return "\n".join(
            [
                "# Component Not Found",
                "",
                f'The path "{ctx.path}" was not found in the knowledge graph for {ctx.projectName}.',
                "",
                "Possible reasons:",
                "- The file hasn't been analyzed yet — try running /understand first",
                "- The path may be different in the graph — check the exact file path",
                "- The file may have been deleted or renamed since the last analysis",
            ]
        )

    target_node = ctx.targetNode
    child_nodes = ctx.childNodes
    connected_nodes = ctx.connectedNodes
    relevant_edges = ctx.relevantEdges
    layer = ctx.layer
    lines: list[str] = []

    lines.append(f"# Deep Dive: {target_node.name}")
    lines.append("")
    lines.append(
        f"**Type:** {target_node.type} | **Complexity:** {target_node.complexity}"
    )
    if target_node.filePath:
        lines.append(f"**File:** `{target_node.filePath}`")
    line_range = _opt(target_node, "lineRange")
    if line_range:
        lines.append(f"**Lines:** {line_range[0]}-{line_range[1]}")
    lines.append("")
    lines.append(f"**Summary:** {target_node.summary}")
    lines.append("")

    if layer is not None:
        lines.append(f"## Architectural Layer: {layer.name}")
        lines.append(layer.description)
        lines.append("")

    if child_nodes:
        lines.append("## Internal Components")
        for child in child_nodes:
            lines.append(f"- **{child.name}** ({child.type}): {child.summary}")
        lines.append("")

    if connected_nodes:
        lines.append("## Connected Components")
        for node in connected_nodes:
            lines.append(f"- **{node.name}** ({node.type}): {node.summary}")
        lines.append("")

    if relevant_edges:
        node_map = {
            n.id: n for n in [target_node, *child_nodes, *connected_nodes]
        }
        lines.append("## Relationships")
        for edge in relevant_edges:
            if edge.type == "contains":
                continue
            src_node = node_map.get(edge.source)
            tgt_node = node_map.get(edge.target)
            src = src_node.name if src_node else edge.source
            tgt = tgt_node.name if tgt_node else edge.target
            description = _opt(edge, "description")
            desc = f" — {description}" if description else ""
            lines.append(f"- {src} --[{edge.type}]--> {tgt}{desc}")
        lines.append("")

    language_notes = _opt(target_node, "languageNotes")
    if language_notes:
        lines.append("## Language Notes")
        lines.append(str(language_notes))
        lines.append("")

    lines.append("## Instructions")
    lines.append("Provide a thorough explanation of this component:")
    lines.append("1. What it does and why it exists in the project")
    lines.append("2. How data flows through it (inputs, processing, outputs)")
    lines.append("3. How it interacts with connected components")
    lines.append("4. Any patterns, idioms, or design decisions worth noting")
    lines.append("5. Potential gotchas or areas of complexity")
    lines.append("")

    return "\n".join(lines)
