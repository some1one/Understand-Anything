"""Graph staleness + merge — port of ``packages/core/src/staleness.ts``.

The git-diff and graph-merge logic is core-specific (the arch_analysis
auto-update modules drive the same idea through fingerprints, but the merge
here is the simple file-path-keyed node/edge replacement the dashboard uses).
Ported faithfully.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import TypedDict

from .types import GraphEdge, GraphNode, KnowledgeGraph


class StalenessResult(TypedDict):
    stale: bool
    changedFiles: list[str]


def get_changed_files(project_dir: str, last_commit_hash: str) -> list[str]:
    """Files changed between ``last_commit_hash`` and HEAD.

    Returns an empty list if there are no changes or git errors.
    """
    try:
        output = subprocess.run(
            ["git", "diff", f"{last_commit_hash}..HEAD", "--name-only"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return []
    return [line.strip() for line in output.split("\n") if line.strip()]


def is_stale(project_dir: str, last_commit_hash: str) -> StalenessResult:
    """Whether the knowledge graph is stale relative to current HEAD."""
    changed_files = get_changed_files(project_dir, last_commit_hash)
    return {"stale": len(changed_files) > 0, "changedFiles": changed_files}


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _node_field(node: GraphNode | dict, key: str):
    return node.get(key) if isinstance(node, dict) else getattr(node, key, None)


def merge_graph_update(
    existing_graph: KnowledgeGraph | dict,
    changed_file_paths: list[str],
    new_nodes: list[GraphNode | dict],
    new_edges: list[GraphEdge | dict],
    new_commit_hash: str,
) -> dict:
    """Merge new analysis results into an existing knowledge graph.

    1. Remove old nodes belonging to changed files (matched by filePath).
    2. Remove old edges whose source/target node belongs to a changed file.
    3. Add new nodes and edges.
    4. Update project.gitCommitHash and project.analyzedAt.
    """
    if not isinstance(existing_graph, dict):
        existing = existing_graph.model_dump(by_alias=True)
    else:
        existing = dict(existing_graph)

    changed_set = set(changed_file_paths)
    existing_nodes = existing.get("nodes", [])
    existing_edges = existing.get("edges", [])

    def _fp(n):
        return n.get("filePath") if isinstance(n, dict) else getattr(n, "filePath", None)

    def _id(n):
        return n.get("id") if isinstance(n, dict) else getattr(n, "id", None)

    def _src(e):
        return e.get("source") if isinstance(e, dict) else getattr(e, "source", None)

    def _tgt(e):
        return e.get("target") if isinstance(e, dict) else getattr(e, "target", None)

    removed_node_ids = {
        _id(node)
        for node in existing_nodes
        if _fp(node) is not None and _fp(node) in changed_set
    }

    retained_nodes = [n for n in existing_nodes if _id(n) not in removed_node_ids]
    retained_edges = [
        e
        for e in existing_edges
        if _src(e) not in removed_node_ids and _tgt(e) not in removed_node_ids
    ]

    project = dict(existing.get("project", {}))
    project["gitCommitHash"] = new_commit_hash
    project["analyzedAt"] = _now_iso()

    merged = dict(existing)
    merged["project"] = project
    merged["nodes"] = [*retained_nodes, *new_nodes]
    merged["edges"] = [*retained_edges, *new_edges]
    return merged


__all__ = [
    "StalenessResult",
    "get_changed_files",
    "is_stale",
    "merge_graph_update",
]
