"""Directory and file pattern matching (section G).

Classifies directory groups and individual files against the known
architectural patterns declared in :mod:`arch_analysis.constants`.
"""

from __future__ import annotations

import re

from .constants import (
    CI_DIR_SEGMENTS,
    CI_FILENAMES,
    CONFIG_FILENAMES,
    DIRECTORY_PATTERN_MAP,
    DOC_EXTENSIONS,
    ENTRY_FILENAMES,
    GO_ENTRY_BASENAME,
    INFRA_EXTENSIONS,
    MAKEFILE_NAME,
    TEST_FILE_REGEXES,
    TYPE_DEF_EXTENSIONS,
)
from .models import FileNode

_TEST_RE = [re.compile(p) for p in TEST_FILE_REGEXES]


def match_directory_patterns(group_names: list[str]) -> dict[str, str]:
    """Map each directory group to a known pattern label, where one exists."""
    matches: dict[str, str] = {}
    for name in group_names:
        label = DIRECTORY_PATTERN_MAP.get(name.lower())
        if label:
            matches[name] = label
    return matches


def classify_file(node: FileNode) -> str | None:
    """Return the file-level pattern label for a node, or ``None``.

    Rules are evaluated in priority order (tests first, then declaration files,
    entry points, config, infra, ci-cd, data, type defs, docs).
    """
    path = node.filePath.replace("\\", "/")
    low = path.lower()
    base = node.basename
    blow = base.lower()
    framed = "/" + low  # so "/cmd/" etc. match at the start too

    if any(rx.search(base) for rx in _TEST_RE):
        return "test"
    if blow.endswith(".d.ts"):
        return "types"
    if base in ENTRY_FILENAMES:
        return "entry"
    if base == GO_ENTRY_BASENAME:
        return "entry" if "/cmd/" in framed else None
    if base in CONFIG_FILENAMES:
        return "config"
    if base == "Dockerfile" or blow.startswith("dockerfile.") or blow.startswith(
        "docker-compose"
    ):
        return "infrastructure"
    if low.endswith(INFRA_EXTENSIONS):
        return "infrastructure"
    if (
        "/.github/workflows/" in framed
        or base in CI_FILENAMES
        or any(f"/{seg}/" in framed for seg in CI_DIR_SEGMENTS)
    ):
        return "ci-cd"
    if low.endswith(".sql"):
        return "data"
    if low.endswith(TYPE_DEF_EXTENSIONS):
        return "types"
    if low.endswith(DOC_EXTENSIONS):
        return "documentation"
    if base == MAKEFILE_NAME:
        return "infrastructure"
    return None


def classify_all_files(nodes: list[FileNode]) -> dict[str, str]:
    """Per-node-id file pattern labels (only nodes that match a rule)."""
    out: dict[str, str] = {}
    for n in nodes:
        label = classify_file(n)
        if label:
            out[n.id] = label
    return out
