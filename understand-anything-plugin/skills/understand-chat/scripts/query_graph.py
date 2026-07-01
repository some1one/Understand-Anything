#!/usr/bin/env python3
"""Extract a compact query-relevant subgraph for /understand-chat."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def text(node: dict[str, Any]) -> str:
    return " ".join(
        str(v)
        for v in (
            node.get("id", ""),
            node.get("name", ""),
            node.get("filePath", ""),
            node.get("summary", ""),
            " ".join(node.get("tags", []) or []),
        )
    ).lower()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2:
        sys.stderr.write("Usage: query_graph.py <project-root> <query...>\n")
        return 1

    project_root = Path(args[0]).resolve()
    query = " ".join(args[1:]).strip()
    graph_path = project_root / ".understand-anything" / "knowledge-graph.json"
    if not graph_path.is_file():
        sys.stderr.write("No knowledge graph found. Run /understand first to analyze this project.\n")
        return 1

    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    terms = [t.lower() for t in query.split() if t.strip()]
    nodes = [n for n in graph.get("nodes", []) if isinstance(n, dict)]
    matched = [n for n in nodes if all(term in text(n) for term in terms)] if terms else []
    if not matched and terms:
        matched = [n for n in nodes if any(term in text(n) for term in terms)]
    matched_ids = {n.get("id") for n in matched if n.get("id")}
    edges = [
        e
        for e in graph.get("edges", [])
        if isinstance(e, dict) and (e.get("source") in matched_ids or e.get("target") in matched_ids)
    ]
    connected_ids = {
        value
        for e in edges
        for value in (e.get("source"), e.get("target"))
        if isinstance(value, str)
    }
    connected = [n for n in nodes if n.get("id") in connected_ids and n.get("id") not in matched_ids]
    layers = [
        layer
        for layer in graph.get("layers", [])
        if isinstance(layer, dict) and matched_ids.intersection(layer.get("nodeIds", []) or [])
    ]
    payload = {
        "project": graph.get("project", {}),
        "query": query,
        "matchedNodes": matched[:25],
        "connectedNodes": connected[:50],
        "edges": edges[:100],
        "layers": layers,
    }
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
