"""Wrap a per-part assembled graph into a persisted partition graph.

After ``merge_batch_graphs`` assembles ONE part's batches into
``intermediate/assembled-graph.json``, this step:
  1. adds boundary stubs for cross-part edges (using the whole-repo scan file
     set as ``known_paths``), so the part graph is self-valid and cross-part
     edges survive the later merge;
  2. tags the graph with its ``part`` name and project metadata;
  3. writes ``partitions/<part>.knowledge-graph.json``.

Layers are left empty — architecture runs once on the merged graph.

Usage:
    python -m understand_core.assemble_part_graph <project-root> <part> [<commit-hash>]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .boundary_stubs import add_boundary_stubs
from .partition_files import part_to_filename


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def build_part_graph(
    assembled: dict[str, Any],
    part: str,
    known_paths: set[str],
    scan: dict[str, Any],
    commit_hash: str = "",
) -> dict[str, Any]:
    """Build a self-valid partition graph dict tagged with its ``part`` name."""
    stubbed = add_boundary_stubs(
        {"nodes": assembled.get("nodes", []), "edges": assembled.get("edges", [])},
        known_paths,
    )
    return {
        "version": assembled.get("version", "1.0.0"),
        "part": part,
        "project": {
            "name": scan.get("name") or "",
            "languages": scan.get("languages", []),
            "frameworks": scan.get("frameworks", []),
            "description": scan.get("description") or "",
            "analyzedAt": _now_iso(),
            "gitCommitHash": commit_hash,
        },
        "nodes": stubbed["nodes"],
        "edges": stubbed["edges"],
        "layers": [],
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        sys.stderr.write(
            "Usage: python -m understand_core.assemble_part_graph "
            "<project-root> <part> [<commit-hash>]\n"
        )
        return 1

    project_root = Path(args[0]).resolve()
    part = args[1]
    commit_hash = args[2] if len(args) > 2 else ""

    inter = project_root / ".understand-anything" / "intermediate"
    scan = _load_json(inter / "scan-result.json")
    assembled = _load_json(inter / "assembled-graph.json")
    known_paths = {f["path"] for f in scan.get("files", []) if isinstance(f, dict) and f.get("path")}

    graph = build_part_graph(assembled, part, known_paths, scan, commit_hash)

    partitions_dir = project_root / ".understand-anything" / "partitions"
    partitions_dir.mkdir(parents=True, exist_ok=True)
    out_path = partitions_dir / part_to_filename(part)
    out_path.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")

    # Clear this part's batch scratch so batches never leak into the next part.
    for scratch in inter.glob("batch-*.json"):
        scratch.unlink()
    (inter / "assembled-graph.json").unlink(missing_ok=True)

    stub_count = sum(1 for n in graph["nodes"] if n.get("stub"))
    sys.stdout.write(
        json.dumps(
            {
                "outputPath": str(out_path),
                "part": part,
                "nodes": len(graph["nodes"]),
                "edges": len(graph["edges"]),
                "boundaryStubs": stub_count,
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
