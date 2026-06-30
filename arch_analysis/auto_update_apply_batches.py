"""Auto-update Phase 2b — prune + merge fresh batch output.

Prunes the existing graph of nodes/edges belonging to changed or deleted files,
writes the survivors as ``batch-existing.json``, then reuses the standard merge
normalization to fold in the freshly-analyzed ``batch-*.json`` fragments. The
result is written as ``merged-graph.json`` (nodes + edges + carried-forward
layers). When the change analysis flagged an architecture re-run, it also emits
``ua-arch-input.json`` for the architecture-analyzer.

Usage:
    python -m arch_analysis.auto_update_apply_batches <project-root>

Input:  intermediate/change-analysis.json, knowledge-graph.json, intermediate/batch-*.json
Output: intermediate/merged-graph.json (+ ua-arch-input.json when rerunArchitecture)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from . import auto_update_common as c
from .merge_batch_graphs import merge_and_normalize
from .validate_graph import FILE_LEVEL_TYPES, _node_file_path


def _discover_batch_files(intermediate: Path) -> list[Path]:
    files = list(intermediate.glob("batch-*.json"))
    # Exclude our own batch-existing.json — only numbered analyzer outputs.
    numbered = [f for f in files if re.match(r"batch-\d+$", f.stem)]
    numbered.sort(
        key=lambda p: int(re.search(r"batch-(\d+)", p.stem).group(1))
    )
    return numbered


def _build_arch_input(nodes: list[dict], edges: list[dict]) -> dict:
    """Build the architecture-analyzer ``{fileNodes, importEdges, allEdges}`` input."""
    file_nodes = []
    file_node_ids: set[str] = set()
    for n in nodes:
        fp = n.get("filePath") or _node_file_path(n)
        if fp and n.get("type") in FILE_LEVEL_TYPES:
            file_node_ids.add(n["id"])
            file_nodes.append(
                {
                    "id": n["id"],
                    "type": n["type"],
                    "name": n.get("name") or fp.rsplit("/", 1)[-1],
                    "filePath": fp,
                    "summary": n.get("summary", ""),
                    "tags": n.get("tags", []),
                }
            )
    file_to_file = [
        {"source": e["source"], "target": e["target"], "type": e.get("type", "imports")}
        for e in edges
        if e.get("source") in file_node_ids and e.get("target") in file_node_ids
    ]
    import_edges = [e for e in file_to_file if e["type"] == "imports"]
    return {
        "fileNodes": file_nodes,
        "importEdges": import_edges,
        "allEdges": file_to_file,
    }


def run(project_root: Path) -> dict:
    """Prune + merge; return the merged-graph dict."""
    analysis = c.read_json(c.change_analysis_path(project_root))
    if not isinstance(analysis, dict):
        raise FileNotFoundError("change-analysis.json missing or unreadable")

    graph = c.read_json(c.graph_path(project_root))
    if not isinstance(graph, dict):
        raise FileNotFoundError("knowledge-graph.json missing or unreadable")

    target_files = set(analysis.get("filesToReanalyze", [])) | set(
        analysis.get("deletedFiles", [])
    )

    existing_nodes = graph.get("nodes", []) or []
    existing_edges = graph.get("edges", []) or []

    # Prune nodes belonging to changed/deleted files. Changed-file nodes are
    # re-supplied by the fresh batches; deleted-file nodes are gone for good.
    # Edges are kept wholesale — merge_and_normalize drops the dangling ones
    # (edges into deleted nodes) while edges into re-added file nodes survive.
    kept_nodes = [n for n in existing_nodes if _node_file_path(n) not in target_files]
    existing_batch = {"nodes": kept_nodes, "edges": existing_edges}
    c.write_json(
        c.intermediate_dir(project_root) / "batch-existing.json", existing_batch
    )

    intermediate = c.intermediate_dir(project_root)
    fresh_batches = [c.read_json(p) or {} for p in _discover_batch_files(intermediate)]

    assembled, report = merge_and_normalize([existing_batch, *fresh_batches])

    # Carry layers forward; finalize reconciles them against the new node set.
    merged = {
        "version": graph.get("version", "1.0.0"),
        "project": graph.get("project", {}),
        "nodes": assembled["nodes"],
        "edges": assembled["edges"],
        "layers": graph.get("layers", []),
    }
    c.write_json(c.merged_graph_path(project_root), merged)

    if analysis.get("rerunArchitecture"):
        arch_input = _build_arch_input(assembled["nodes"], assembled["edges"])
        c.write_json(c.arch_input_path(project_root), arch_input)

    sys.stderr.write("\n".join(report) + "\n")
    return merged


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        sys.stderr.write(
            "Usage: python -m arch_analysis.auto_update_apply_batches <project-root>\n"
        )
        return 1

    project_root = Path(args[0]).resolve()
    try:
        merged = run(project_root)
    except FileNotFoundError as err:
        sys.stderr.write(f"auto_update_apply_batches failed: {err}\n")
        return 1

    c.emit(
        {
            "totalNodes": len(merged["nodes"]),
            "totalEdges": len(merged["edges"]),
            "rerunArchitecture": c.arch_input_path(project_root).exists(),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
