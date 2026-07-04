"""Build chat context from a knowledge graph — port of ``context-builder.ts``.

Searches the graph for nodes relevant to a query, expands one hop via edges,
collects the associated layers, and renders the result as markdown for LLM
consumption.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from understand_core import GraphEdge, GraphNode, KnowledgeGraph, Layer, SearchEngine


class ChatContext(BaseModel):
    """Relevant slice of the knowledge graph for a chat query."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    projectName: str
    projectDescription: str
    languages: list[str]
    frameworks: list[str]
    relevantNodes: list[GraphNode]
    relevantEdges: list[GraphEdge]
    relevantLayers: list[Layer]
    query: str


def _opt(obj: object, name: str) -> object | None:
    """Read an optional/extra pydantic field (e.g. ``description``)."""
    return getattr(obj, name, None)


def build_chat_context(
    graph: KnowledgeGraph,
    query: str,
    max_nodes: int | None = None,
) -> ChatContext:
    """Find nodes relevant to ``query``, expand one hop, and collect layers."""
    limit = max_nodes if max_nodes is not None else 15

    # 1. Use SearchEngine to find relevant nodes.
    engine = SearchEngine(graph.nodes)
    search_results = engine.search(query, limit=limit)

    matched_ids = {r.node_id for r in search_results}

    # 2. Expand to connected nodes (1 hop via edges).
    expanded_ids = set(matched_ids)
    for edge in graph.edges:
        if edge.source in matched_ids:
            expanded_ids.add(edge.target)
        if edge.target in matched_ids:
            expanded_ids.add(edge.source)

    # Collect the actual node objects.
    node_map = {n.id: n for n in graph.nodes}
    relevant_nodes: list[GraphNode] = []
    for node_id in expanded_ids:
        node = node_map.get(node_id)
        if node is not None:
            relevant_nodes.append(node)

    # 3. Collect edges where both endpoints are in the relevant set.
    relevant_edges = [
        e for e in graph.edges if e.source in expanded_ids and e.target in expanded_ids
    ]

    # 4. Find layers containing any relevant node.
    relevant_layers = [
        layer
        for layer in graph.layers
        if any(node_id in expanded_ids for node_id in layer.nodeIds)
    ]

    return ChatContext(
        projectName=graph.project.name,
        projectDescription=graph.project.description,
        languages=graph.project.languages,
        frameworks=graph.project.frameworks,
        relevantNodes=relevant_nodes,
        relevantEdges=relevant_edges,
        relevantLayers=relevant_layers,
        query=query,
    )


def format_context_for_prompt(context: ChatContext) -> str:
    """Render the :class:`ChatContext` as readable markdown for an LLM."""
    lines: list[str] = []

    # Project header.
    lines.append(f"# Project: {context.projectName}")
    lines.append("")
    lines.append(context.projectDescription)
    lines.append("")
    lines.append(f"**Languages:** {', '.join(context.languages)}")
    lines.append(f"**Frameworks:** {', '.join(context.frameworks)}")
    lines.append("")

    # Layers section.
    if context.relevantLayers:
        lines.append("## Relevant Layers")
        lines.append("")
        for layer in context.relevantLayers:
            lines.append(f"### {layer.name}")
            lines.append(layer.description)
            lines.append("")

    # Nodes section.
    if context.relevantNodes:
        lines.append("## Code Components")
        lines.append("")
        for node in context.relevantNodes:
            lines.append(f"### {node.name} ({node.type})")
            if node.filePath:
                lines.append(f"- **File:** {node.filePath}")
            lines.append(f"- **Complexity:** {node.complexity}")
            lines.append(f"- **Summary:** {node.summary}")
            if node.tags:
                lines.append(f"- **Tags:** {', '.join(node.tags)}")
            language_notes = _opt(node, "languageNotes")
            if language_notes:
                lines.append(f"- **Language Notes:** {language_notes}")
            lines.append("")

    # Edges/relationships section.
    if context.relevantEdges:
        node_map = {n.id: n for n in context.relevantNodes}
        lines.append("## Relationships")
        lines.append("")
        for edge in context.relevantEdges:
            source_node = node_map.get(edge.source)
            target_node = node_map.get(edge.target)
            source_name = source_node.name if source_node else edge.source
            target_name = target_node.name if target_node else edge.target
            line = f"- {source_name} --[{edge.type}]--> {target_name}"
            description = _opt(edge, "description")
            if description:
                line += f": {description}"
            lines.append(line)
        lines.append("")

    return "\n".join(lines)
