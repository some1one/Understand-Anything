"""Directory and node-type grouping (sections A & B).

Groups file nodes by their top-level directory (relative to the common path
prefix shared by all files) and by node type.
"""

from __future__ import annotations

from collections import defaultdict

from .constants import ROOT_GROUP
from .models import FileNode


def _parts(path: str) -> list[str]:
    """Split a path into clean segments, dropping empties and ``.``."""
    return [p for p in path.replace("\\", "/").split("/") if p not in ("", ".")]


def common_dir_prefix(paths: list[str]) -> list[str]:
    """Longest sequence of leading *directory* segments shared by all paths.

    Only directory components count (the final filename is never part of a
    prefix), so ``["src/a.ts", "src/b.ts"]`` yields ``["src"]``.
    """
    dir_parts = [_parts(p)[:-1] for p in paths]
    if not dir_parts:
        return []
    common = list(dir_parts[0])
    for dp in dir_parts[1:]:
        i = 0
        while i < len(common) and i < len(dp) and common[i] == dp[i]:
            i += 1
        common = common[:i]
        if not common:
            break
    return common


def _flat_group(node: FileNode) -> str:
    """Group key for a flat project: by test/config role, then extension."""
    base = node.basename.lower()
    if ".test." in base or ".spec." in base or base.startswith("test_"):
        return "test"
    if ".config." in base or base.endswith(".config"):
        return "config"
    if "." in base:
        return base.rsplit(".", 1)[1]
    return ROOT_GROUP


def group_by_directory(
    nodes: list[FileNode],
) -> tuple[dict[str, list[str]], list[str]]:
    """Group node IDs by top-level directory (section A).

    Returns ``(groups, common_prefix_segments)``. Falls back to extension-based
    grouping when the project is flat (no file lives below the common prefix).
    """
    paths = [n.filePath for n in nodes]
    prefix = common_dir_prefix(paths)
    plen = len(prefix)

    remainders = {n.id: _parts(n.filePath)[plen:] for n in nodes}
    is_flat = all(len(r) <= 1 for r in remainders.values())

    groups: dict[str, list[str]] = defaultdict(list)
    if is_flat:
        for n in nodes:
            groups[_flat_group(n)].append(n.id)
        return dict(groups), prefix

    for n in nodes:
        remainder = remainders[n.id]
        key = remainder[0] if len(remainder) > 1 else ROOT_GROUP
        groups[key].append(n.id)
    return dict(groups), prefix


def group_by_node_type(nodes: list[FileNode]) -> dict[str, list[str]]:
    """Group node IDs by node type (section B)."""
    groups: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        groups[n.type].append(n.id)
    return dict(groups)


def node_to_group(directory_groups: dict[str, list[str]]) -> dict[str, str]:
    """Invert ``directory_groups`` into a node-id -> group lookup."""
    return {nid: g for g, ids in directory_groups.items() for nid in ids}
