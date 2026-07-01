#!/usr/bin/env python3
"""Assemble the final KnowledgeGraph JSON from deterministic phase outputs."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.stderr.write("Usage: assemble_knowledge_graph.py <project-root> <git-commit-hash>\n")
        return 1

    project_root = Path(args[0]).resolve()
    commit_hash = args[1]
    inter = project_root / ".understand-anything" / "intermediate"
    scan = load_json(inter / "scan-result.json")
    assembled = load_json(inter / "assembled-graph.json")
    layers_path = inter / "layers.json"
    layers = load_json(layers_path) if layers_path.is_file() else assembled.get("layers", [])

    graph = {
        "version": assembled.get("version", "1.0.0"),
        "project": {
            "name": scan.get("name") or assembled.get("project", {}).get("name") or project_root.name,
            "languages": scan.get("languages", []),
            "frameworks": scan.get("frameworks", []),
            "description": scan.get("description") or assembled.get("project", {}).get("description") or "",
            "analyzedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "gitCommitHash": commit_hash,
        },
        "nodes": assembled.get("nodes", []),
        "edges": assembled.get("edges", []),
        "layers": layers if isinstance(layers, list) else [],
    }

    out_path = inter / "assembled-graph.json"
    out_path.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
    sys.stdout.write(
        json.dumps(
            {
                "outputPath": str(out_path),
                "nodes": len(graph["nodes"]),
                "edges": len(graph["edges"]),
                "layers": len(graph["layers"]),
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
