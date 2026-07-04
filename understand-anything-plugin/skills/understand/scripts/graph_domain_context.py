#!/usr/bin/env python3
"""Extract deterministic domain-analyzer context from knowledge-graph.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.stderr.write("Usage: graph_domain_context.py <project-root>\n")
        return 1

    project_root = Path(args[0]).resolve()
    graph_path = project_root / ".understand-anything" / "knowledge-graph.json"
    out_path = project_root / ".understand-anything" / "intermediate" / "domain-context.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    payload = {
        "source": "knowledge-graph",
        "project": graph.get("project", {}),
        "nodes": [
            {
                "id": n.get("id"),
                "type": n.get("type"),
                "name": n.get("name"),
                "summary": n.get("summary"),
                "tags": n.get("tags", []),
            }
            for n in graph.get("nodes", [])
            if isinstance(n, dict)
        ],
        "edges": [
            {
                "source": e.get("source"),
                "target": e.get("target"),
                "type": e.get("type"),
            }
            for e in graph.get("edges", [])
            if isinstance(e, dict)
        ],
        "layers": [
            {
                "id": layer.get("id"),
                "name": layer.get("name"),
                "description": layer.get("description"),
                "nodeIds": layer.get("nodeIds", []),
            }
            for layer in graph.get("layers", [])
            if isinstance(layer, dict)
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    sys.stdout.write(str(out_path) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
