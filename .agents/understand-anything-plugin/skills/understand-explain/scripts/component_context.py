#!/usr/bin/env python3
"""Extract a target component neighborhood for /understand-explain."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def node_text(node: dict[str, Any]) -> str:
    return " ".join(
        str(v)
        for v in (
            node.get("id", ""),
            node.get("name", ""),
            node.get("filePath", ""),
            node.get("summary", ""),
        )
    ).lower()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.stderr.write("Usage: component_context.py <project-root> <component>\n")
        return 1

    project_root = Path(args[0]).resolve()
    target = args[1]
    graph_path = project_root / ".understand-anything" / "knowledge-graph.json"
    if not graph_path.is_file():
        sys.stderr.write("No knowledge graph found. Run /understand first to analyze this project.\n")
        return 1

    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes = [n for n in graph.get("nodes", []) if isinstance(n, dict)]
    needle = target.lower()
    matches = [
        n
        for n in nodes
        if needle in str(n.get("filePath", "")).lower()
        or needle in str(n.get("id", "")).lower()
        or needle in str(n.get("name", "")).lower()
    ]
    target_node = matches[0] if matches else None
    target_id = target_node.get("id") if target_node else None
    edges = [
        e
        for e in graph.get("edges", [])
        if isinstance(e, dict) and target_id and (e.get("source") == target_id or e.get("target") == target_id)
    ]
    neighbor_ids = {
        value
        for e in edges
        for value in (e.get("source"), e.get("target"))
        if isinstance(value, str) and value != target_id
    }
    neighbors = [n for n in nodes if n.get("id") in neighbor_ids]
    layers = [
        layer
        for layer in graph.get("layers", [])
        if isinstance(layer, dict) and target_id in (layer.get("nodeIds", []) or [])
    ]
    file_path = target_node.get("filePath") if target_node else None
    source_excerpt = None
    if isinstance(file_path, str):
        source = project_root / file_path
        if source.is_file():
            source_excerpt = source.read_text(encoding="utf-8", errors="replace")[:12000]
    payload = {
        "project": graph.get("project", {}),
        "target": target,
        "targetNode": target_node,
        "alternateMatches": matches[1:10],
        "edges": edges,
        "neighbors": neighbors,
        "layers": layers,
        "sourceExcerpt": source_excerpt,
    }
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
