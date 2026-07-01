#!/usr/bin/env python3
"""Extract deterministic onboarding context from knowledge-graph.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

FILE_LEVEL_TYPES = {
    "file", "config", "document", "service", "pipeline",
    "table", "schema", "resource", "endpoint",
}
COMPLEXITY_RANK = {"complex": 3, "moderate": 2, "simple": 1}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.stderr.write("Usage: onboarding_context.py <project-root>\n")
        return 1

    project_root = Path(args[0]).resolve()
    graph_path = project_root / ".understand-anything" / "knowledge-graph.json"
    if not graph_path.is_file():
        sys.stderr.write("No knowledge graph found. Run /understand first to analyze this project.\n")
        return 1

    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    file_nodes = [
        n
        for n in graph.get("nodes", [])
        if isinstance(n, dict) and n.get("type") in FILE_LEVEL_TYPES
    ]
    by_id = {n.get("id"): n for n in file_nodes if n.get("id")}
    layers = []
    for layer in graph.get("layers", []):
        if not isinstance(layer, dict):
            continue
        ids = layer.get("nodeIds", []) or []
        layer_files = [by_id[i] for i in ids if i in by_id]
        layers.append({**layer, "files": layer_files[:25]})
    hotspots = sorted(
        file_nodes,
        key=lambda n: (COMPLEXITY_RANK.get(str(n.get("complexity", "")).lower(), 0), str(n.get("name", ""))),
        reverse=True,
    )[:20]
    payload = {
        "project": graph.get("project", {}),
        "layers": layers,
        "fileNodes": file_nodes,
        "complexityHotspots": hotspots,
    }
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
