#!/usr/bin/env python3
"""Write batch-existing.json after pruning changed-file nodes from a graph."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PATH_BEARING_PREFIXES = {
    "file", "function", "class", "config", "document",
    "service", "table", "endpoint", "pipeline", "schema", "resource",
}


def node_file_path(node: dict[str, Any]) -> str | None:
    fp = node.get("filePath")
    if isinstance(fp, str) and fp:
        return fp
    nid = node.get("id")
    if not isinstance(nid, str):
        return None
    parts = nid.split(":")
    if len(parts) >= 2 and parts[0] in PATH_BEARING_PREFIXES:
        return parts[1]
    return None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.stderr.write("Usage: prune_incremental_batch.py <project-root> <changed-files.txt>\n")
        return 1

    project_root = Path(args[0]).resolve()
    changed_path = Path(args[1])
    graph_path = project_root / ".understand-anything" / "knowledge-graph.json"
    out_path = project_root / ".understand-anything" / "intermediate" / "batch-existing.json"

    try:
        changed = {line.strip() for line in changed_path.read_text(encoding="utf-8").splitlines() if line.strip()}
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        sys.stderr.write(f"Cannot prepare incremental batch: {err}\n")
        return 1

    nodes = [n for n in graph.get("nodes", []) if isinstance(n, dict)]
    removed_ids = {n.get("id") for n in nodes if node_file_path(n) in changed and n.get("id")}
    kept_nodes = [n for n in nodes if n.get("id") not in removed_ids]
    kept_edges = [
        e
        for e in graph.get("edges", [])
        if isinstance(e, dict)
        and e.get("source") not in removed_ids
        and e.get("target") not in removed_ids
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"nodes": kept_nodes, "edges": kept_edges}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    sys.stdout.write(
        json.dumps(
            {
                "outputPath": str(out_path),
                "changedFiles": len(changed),
                "removedNodes": len(removed_ids),
                "keptNodes": len(kept_nodes),
                "keptEdges": len(kept_edges),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
