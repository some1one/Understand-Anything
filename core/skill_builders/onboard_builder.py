"""Generate a standalone onboarding guide — port of ``onboard-builder.ts``."""

from __future__ import annotations

from understand_core import KnowledgeGraph


def build_onboarding_guide(graph: KnowledgeGraph) -> str:
    """Produce a markdown onboarding guide (README/wiki-ready) from the graph."""
    project, nodes, edges, layers = (
        graph.project,
        graph.nodes,
        graph.edges,
        graph.layers,
    )
    lines: list[str] = []

    # --- Project Overview ---
    lines.append(f"# {project.name}")
    lines.append("")
    lines.append(f"> {project.description}")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| **Languages** | {', '.join(project.languages)} |")
    lines.append(f"| **Frameworks** | {', '.join(project.frameworks)} |")
    lines.append(
        f"| **Components** | {len(nodes)} nodes, {len(edges)} relationships |"
    )
    lines.append(f"| **Last Analyzed** | {project.analyzedAt} |")
    lines.append("")

    # --- Architecture ---
    if layers:
        lines.append("## Architecture")
        lines.append("")
        lines.append("The project is organized into the following layers:")
        lines.append("")

        name_by_id = {n.id: n.name for n in nodes}
        for layer in layers:
            member_names = [
                name_by_id[node_id]
                for node_id in layer.nodeIds
                if name_by_id.get(node_id)
            ]
            lines.append(f"### {layer.name}")
            lines.append("")
            lines.append(layer.description)
            lines.append("")
            if member_names:
                lines.append(f"Key components: {', '.join(member_names)}")
                lines.append("")

    # --- Key Concepts ---
    concept_nodes = [n for n in nodes if n.type == "concept"]
    if concept_nodes:
        lines.append("## Key Concepts")
        lines.append("")
        lines.append("Important architectural and domain concepts to understand:")
        lines.append("")
        for concept in concept_nodes:
            lines.append(f"### {concept.name}")
            lines.append("")
            lines.append(concept.summary)
            lines.append("")

    # --- Getting Started ---
    # Derive a deterministic reading order from the dependency graph: the most
    # depended-on files (highest fan-in via imports/depends_on) are foundational
    # and worth reading first.
    dependency_edge_types = {"imports", "depends_on"}
    fan_in: dict[str, int] = {}
    for edge in edges:
        if edge.type not in dependency_edge_types:
            continue
        # For backward edges the dependency points the other way.
        direction = getattr(edge, "direction", "forward")
        depended = edge.source if direction == "backward" else edge.target
        fan_in[depended] = fan_in.get(depended, 0) + 1

    foundational_candidates = [
        n
        for n in nodes
        if n.type == "file" and n.filePath and fan_in.get(n.id, 0) > 0
    ]
    foundational_candidates.sort(
        key=lambda n: (-fan_in.get(n.id, 0), n.filePath or "")
    )
    foundational_files = foundational_candidates[:8]

    if foundational_files or layers:
        lines.append("## Getting Started")
        lines.append("")

        if foundational_files:
            lines.append(
                "Start with the most depended-on files — these are the foundations the rest of the code builds on:"
            )
            lines.append("")
            for node in foundational_files:
                count = fan_in.get(node.id, 0)
                plural = "" if count == 1 else "s"
                lines.append(
                    f"- `{node.filePath}` — {node.summary} _(referenced by {count} component{plural})_"
                )
            lines.append("")

        if layers:
            lines.append(
                "Then explore the codebase layer by layer, in the order listed under **Architecture** above."
            )
            lines.append("")

    # --- File Map ---
    file_nodes = [n for n in nodes if n.type == "file" and n.filePath]
    if file_nodes:
        lines.append("## File Map")
        lines.append("")
        lines.append("| File | Purpose | Complexity |")
        lines.append("|------|---------|------------|")
        for node in file_nodes:
            lines.append(
                f"| `{node.filePath}` | {node.summary} | {node.complexity} |"
            )
        lines.append("")

    # --- Complexity Hotspots ---
    complex_nodes = [n for n in nodes if n.complexity == "complex"]
    if complex_nodes:
        lines.append("## Complexity Hotspots")
        lines.append("")
        lines.append(
            "These components are the most complex and deserve extra attention:"
        )
        lines.append("")
        for node in complex_nodes:
            lines.append(f"- **{node.name}** ({node.type}): {node.summary}")
        lines.append("")

    # --- Footer ---
    lines.append("---")
    lines.append("")
    lines.append(f"*Generated from knowledge graph v{graph.version}*")
    lines.append("")

    return "\n".join(lines)
