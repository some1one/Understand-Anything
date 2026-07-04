#!/usr/bin/env python3
"""Validate-tolerant save step for the /understand domain phase (Phase 7)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.stderr.write("Usage: save_domain_graph.py <project-root>\n")
        return 1

    project_root = Path(args[0]).resolve()
    ua_dir = project_root / ".understand-anything"
    intermediate = ua_dir / "intermediate"
    source = intermediate / "domain-analysis.json"
    target = ua_dir / "domain-graph.json"
    if not source.is_file():
        sys.stderr.write(f"Missing domain analysis output: {source}\n")
        return 1

    try:
        graph = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        sys.stderr.write(f"Malformed domain analysis JSON: {err}\n")
        return 1

    warnings: list[str] = []
    for key in ("nodes", "edges"):
        if not isinstance(graph.get(key), list):
            graph[key] = []
            warnings.append(f"Inserted empty {key} array")
    graph.setdefault("version", "1.0.0")
    graph.setdefault("layers", [])

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")

    for name in ("domain-analysis.json", "domain-context.json"):
        path = intermediate / name
        if path.exists():
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except OSError as err:
                warnings.append(f"Could not remove {path}: {err}")

    payload = {"outputPath": str(target), "warnings": warnings}
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
