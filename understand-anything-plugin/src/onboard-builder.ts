import type { KnowledgeGraph } from "@understand-anything/core";

/**
 * Generate a structured onboarding guide from the knowledge graph.
 * Output is standalone markdown suitable for a README, wiki, or docs.
 */
export function buildOnboardingGuide(graph: KnowledgeGraph): string {
  const { project, nodes, edges, layers } = graph;
  const lines: string[] = [];

  // --- Project Overview ---
  lines.push(`# ${project.name}`);
  lines.push("");
  lines.push(`> ${project.description}`);
  lines.push("");
  lines.push(`| | |`);
  lines.push(`|---|---|`);
  lines.push(`| **Languages** | ${project.languages.join(", ")} |`);
  lines.push(`| **Frameworks** | ${project.frameworks.join(", ")} |`);
  lines.push(`| **Components** | ${nodes.length} nodes, ${edges.length} relationships |`);
  lines.push(`| **Last Analyzed** | ${project.analyzedAt} |`);
  lines.push("");

  // --- Architecture ---
  if (layers.length > 0) {
    lines.push("## Architecture");
    lines.push("");
    lines.push("The project is organized into the following layers:");
    lines.push("");

    for (const layer of layers) {
      const memberNames = layer.nodeIds
        .map((id) => nodes.find((n) => n.id === id)?.name)
        .filter(Boolean);
      lines.push(`### ${layer.name}`);
      lines.push("");
      lines.push(layer.description);
      lines.push("");
      if (memberNames.length > 0) {
        lines.push(`Key components: ${memberNames.join(", ")}`);
        lines.push("");
      }
    }
  }

  // --- Key Concepts ---
  const conceptNodes = nodes.filter((n) => n.type === "concept");
  if (conceptNodes.length > 0) {
    lines.push("## Key Concepts");
    lines.push("");
    lines.push("Important architectural and domain concepts to understand:");
    lines.push("");
    for (const concept of conceptNodes) {
      lines.push(`### ${concept.name}`);
      lines.push("");
      lines.push(concept.summary);
      lines.push("");
    }
  }

  // --- Getting Started ---
  // Derive a deterministic reading order from the dependency graph: the most
  // depended-on files (highest fan-in via imports/depends_on) are foundational
  // and worth reading first.
  const dependencyEdgeTypes = new Set(["imports", "depends_on"]);
  const fanIn = new Map<string, number>();
  for (const edge of edges) {
    if (!dependencyEdgeTypes.has(edge.type)) continue;
    // For backward edges the dependency points the other way.
    const depended = edge.direction === "backward" ? edge.source : edge.target;
    fanIn.set(depended, (fanIn.get(depended) ?? 0) + 1);
  }

  const foundationalFiles = nodes
    .filter((n) => n.type === "file" && n.filePath && (fanIn.get(n.id) ?? 0) > 0)
    .sort((a, b) => {
      const diff = (fanIn.get(b.id) ?? 0) - (fanIn.get(a.id) ?? 0);
      return diff !== 0 ? diff : a.filePath!.localeCompare(b.filePath!);
    })
    .slice(0, 8);

  if (foundationalFiles.length > 0 || layers.length > 0) {
    lines.push("## Getting Started");
    lines.push("");

    if (foundationalFiles.length > 0) {
      lines.push(
        "Start with the most depended-on files — these are the foundations the rest of the code builds on:",
      );
      lines.push("");
      for (const node of foundationalFiles) {
        const count = fanIn.get(node.id) ?? 0;
        lines.push(
          `- \`${node.filePath}\` — ${node.summary} _(referenced by ${count} component${count === 1 ? "" : "s"})_`,
        );
      }
      lines.push("");
    }

    if (layers.length > 0) {
      lines.push(
        "Then explore the codebase layer by layer, in the order listed under **Architecture** above.",
      );
      lines.push("");
    }
  }

  // --- File Map ---
  const fileNodes = nodes.filter((n) => n.type === "file" && n.filePath);
  if (fileNodes.length > 0) {
    lines.push("## File Map");
    lines.push("");
    lines.push("| File | Purpose | Complexity |");
    lines.push("|------|---------|------------|");
    for (const node of fileNodes) {
      lines.push(`| \`${node.filePath}\` | ${node.summary} | ${node.complexity} |`);
    }
    lines.push("");
  }

  // --- Complexity Hotspots ---
  const complexNodes = nodes.filter((n) => n.complexity === "complex");
  if (complexNodes.length > 0) {
    lines.push("## Complexity Hotspots");
    lines.push("");
    lines.push("These components are the most complex and deserve extra attention:");
    lines.push("");
    for (const node of complexNodes) {
      lines.push(`- **${node.name}** (${node.type}): ${node.summary}`);
    }
    lines.push("");
  }

  // --- Footer ---
  lines.push("---");
  lines.push("");
  lines.push(`*Generated from knowledge graph v${graph.version}*`);
  lines.push("");

  return lines.join("\n");
}
