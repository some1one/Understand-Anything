#!/usr/bin/env python3
"""Save the assembled graph as knowledge-graph.json and emit summary counts."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.stderr.write("Usage: save_knowledge_graph.py <project-root>\n")
        return 1

    project_root = Path(args[0]).resolve()
    source = project_root / ".understand-anything" / "intermediate" / "assembled-graph.json"
    target = project_root / ".understand-anything" / "knowledge-graph.json"
    graph = json.loads(source.read_text(encoding="utf-8"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")

    nodes = [n for n in graph.get("nodes", []) if isinstance(n, dict)]
    edges = [e for e in graph.get("edges", []) if isinstance(e, dict)]
    file_paths = {
        n.get("filePath")
        for n in nodes
        if isinstance(n.get("filePath"), str) and n.get("filePath")
    }
    summary = {
        "outputPath": str(target),
        "project": graph.get("project", {}),
        "analyzedFiles": len(file_paths),
        "totalNodes": len(nodes),
        "nodesByType": dict(Counter(str(n.get("type", "unknown")) for n in nodes)),
        "totalEdges": len(edges),
        "edgesByType": dict(Counter(str(e.get("type", "unknown")) for e in edges)),
        "layers": [
            {"id": layer.get("id"), "name": layer.get("name"), "nodeCount": len(layer.get("nodeIds", []) or [])}
            for layer in graph.get("layers", [])
            if isinstance(layer, dict)
        ],
    }
    summary_path = project_root / ".understand-anything" / "intermediate" / "save-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    sys.stdout.write(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
