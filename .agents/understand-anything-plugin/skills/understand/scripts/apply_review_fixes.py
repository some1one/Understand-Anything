#!/usr/bin/env python3
"""Apply deterministic graph fixes after validation reports issues."""

from __future__ import annotations

import json
import sys
from pathlib import Path

VALID_NODE_TYPES = {
    "file", "function", "class", "module", "concept",
    "config", "document", "service", "table", "endpoint",
    "pipeline", "schema", "resource", "domain", "flow", "step",
}
VALID_EDGE_TYPES = {
    "imports", "exports", "contains", "inherits", "implements",
    "calls", "subscribes", "publishes", "middleware",
    "reads_from", "writes_to", "transforms", "validates",
    "depends_on", "tested_by", "configures", "related", "similar_to",
    "deploys", "serves", "provisions", "triggers", "migrates",
    "documents", "routes", "defines_schema", "contains_flow",
    "flow_step", "cross_domain",
}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.stderr.write("Usage: apply_review_fixes.py <project-root>\n")
        return 1

    project_root = Path(args[0]).resolve()
    path = project_root / ".understand-anything" / "intermediate" / "assembled-graph.json"
    graph = json.loads(path.read_text(encoding="utf-8"))
    fixed: list[str] = []

    nodes = []
    for node in graph.get("nodes", []):
        if not isinstance(node, dict):
            fixed.append("removed non-object node")
            continue
        if node.get("type") not in VALID_NODE_TYPES:
            fixed.append(f"removed node with invalid type: {node.get('id')}")
            continue
        node.setdefault("tags", ["untagged"])
        if not node.get("tags"):
            node["tags"] = ["untagged"]
            fixed.append(f"filled tags: {node.get('id')}")
        if not node.get("summary"):
            node["summary"] = "No summary available"
            fixed.append(f"filled summary: {node.get('id')}")
        node.setdefault("complexity", "moderate")
        nodes.append(node)

    node_ids = {n.get("id") for n in nodes if isinstance(n.get("id"), str)}
    edges = []
    for edge in graph.get("edges", []):
        if not isinstance(edge, dict):
            fixed.append("removed non-object edge")
            continue
        if edge.get("type") not in VALID_EDGE_TYPES:
            fixed.append(f"removed edge with invalid type: {edge.get('source')}->{edge.get('target')}")
            continue
        if edge.get("source") not in node_ids or edge.get("target") not in node_ids:
            fixed.append(f"removed dangling edge: {edge.get('source')}->{edge.get('target')}")
            continue
        edge.setdefault("direction", "forward")
        edge.setdefault("weight", 0.5)
        edges.append(edge)

    layers = []
    for layer in graph.get("layers", []):
        if not isinstance(layer, dict):
            fixed.append("removed non-object layer")
            continue
        ids = [nid for nid in layer.get("nodeIds", []) if nid in node_ids]
        if ids:
            layer["nodeIds"] = ids
            layers.append(layer)

    graph["nodes"] = nodes
    graph["edges"] = edges
    graph["layers"] = layers
    path.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
    sys.stdout.write(json.dumps({"outputPath": str(path), "fixes": fixed}, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
