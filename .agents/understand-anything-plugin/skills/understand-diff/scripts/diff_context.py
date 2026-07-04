#!/usr/bin/env python3
"""Build graph context for changed files and write diff-overlay.json."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def changed_files(project_root: Path, base: str | None) -> tuple[list[str], str]:
    if base:
        cmd = ["git", "diff", f"{base}...HEAD", "--name-only"]
        label = base
    else:
        cmd = ["git", "diff", "--name-only"]
        label = "working-tree"
    result = subprocess.run(cmd, cwd=project_root, text=True, capture_output=True, check=False)
    if result.returncode != 0 and base:
        result = subprocess.run(["git", "diff", "--name-only"], cwd=project_root, text=True, capture_output=True, check=False)
        label = "working-tree"
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()], label


def node_file_path(node: dict[str, Any]) -> str | None:
    fp = node.get("filePath")
    if isinstance(fp, str):
        return fp
    nid = node.get("id")
    if isinstance(nid, str) and ":" in nid:
        return nid.split(":", 2)[1]
    return None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        sys.stderr.write("Usage: diff_context.py <project-root> [base-branch]\n")
        return 1

    project_root = Path(args[0]).resolve()
    base = args[1] if len(args) > 1 else None
    graph_path = project_root / ".understand-anything" / "knowledge-graph.json"
    if not graph_path.is_file():
        sys.stderr.write("No knowledge graph found. Run /understand first to analyze this project.\n")
        return 1

    try:
        files, base_label = changed_files(project_root, base)
    except RuntimeError as err:
        sys.stderr.write(str(err) + "\n")
        return 1

    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes = [n for n in graph.get("nodes", []) if isinstance(n, dict)]
    changed_set = set(files)
    changed_nodes = [n for n in nodes if node_file_path(n) in changed_set]
    changed_ids = {n.get("id") for n in changed_nodes if n.get("id")}
    related_edges = [
        e
        for e in graph.get("edges", [])
        if isinstance(e, dict) and (e.get("source") in changed_ids or e.get("target") in changed_ids)
    ]
    affected_ids = {
        value
        for e in related_edges
        for value in (e.get("source"), e.get("target"))
        if isinstance(value, str) and value not in changed_ids
    }
    affected_nodes = [n for n in nodes if n.get("id") in affected_ids]
    touched_ids = changed_ids | affected_ids
    layers = [
        layer
        for layer in graph.get("layers", [])
        if isinstance(layer, dict) and touched_ids.intersection(layer.get("nodeIds", []) or [])
    ]
    overlay = {
        "version": "1.0.0",
        "baseBranch": base_label,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "changedFiles": files,
        "changedNodeIds": sorted(changed_ids),
        "affectedNodeIds": sorted(affected_ids),
    }
    overlay_path = project_root / ".understand-anything" / "diff-overlay.json"
    overlay_path.write_text(json.dumps(overlay, indent=2, ensure_ascii=False), encoding="utf-8")
    payload = {
        "project": graph.get("project", {}),
        "changedFiles": files,
        "changedNodes": changed_nodes,
        "affectedNodes": affected_nodes,
        "edges": related_edges,
        "layers": layers,
        "overlayPath": str(overlay_path),
    }
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
