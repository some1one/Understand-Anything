"""Detect a repo's source layout and recommend a default partition config.

Runs before the part-inclusion prompt in ``/understand``: it inspects the
whole-repo file list (token-free) and proposes a default
``{sourceFolders, splitDepth}`` that seeds the prompt. The user can accept or
adjust it; the resulting config is what :mod:`understand_core.partition_files`
consumes.

Recommendation rules:
  * **Monorepo** (workspace markers, or ≥2 nested build manifests under
    ``packages/`` / ``apps/`` / ``services/`` / ``libs/``)
    → ``{sourceFolders: None, splitDepth: 2}``.
  * **Single source dir** (a top-level ``src``/``lib``/``app``/``source``)
    → ``{sourceFolders: [<dir>], splitDepth: 1}``.
  * **Flat** (neither) → ``{sourceFolders: None, splitDepth: 1}``.

Usage:
    python -m understand_core.detect_layout <project-root>

Reads ``intermediate/scan-result.json`` and prints the recommendation as JSON.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_WORKSPACE_MARKERS = frozenset(
    {"pnpm-workspace.yaml", "lerna.json", "nx.json", "turbo.json"}
)
_MONOREPO_PARENTS = ("packages", "apps", "services", "libs")
_NESTED_MANIFESTS = frozenset(
    {"package.json", "pyproject.toml", "go.mod", "Cargo.toml", "pom.xml", "build.gradle"}
)
# Ordered by preference — the first present wins.
_SOURCE_DIR_CANDIDATES = ("src", "lib", "app", "source")


def _posix(path: str) -> str:
    return path.replace("\\", "/").strip().lstrip("./").strip("/")


def detect_layout(paths: Iterable[str]) -> dict[str, Any]:
    """Return ``{detectedRoots, recommendation}`` for a repo's file list."""
    norm = [_posix(p) for p in paths]
    norm = [p for p in norm if p]

    root_files = {p for p in norm if "/" not in p}
    has_workspace_marker = bool(root_files & _WORKSPACE_MARKERS)

    # Nested build manifests → candidate sub-packages (e.g. "packages/foo").
    subpackages: set[str] = set()
    for p in norm:
        segments = p.split("/")
        if (
            len(segments) >= 3
            and segments[0] in _MONOREPO_PARENTS
            and segments[-1] in _NESTED_MANIFESTS
        ):
            subpackages.add("/".join(segments[:2]))

    is_monorepo = has_workspace_marker or len(subpackages) >= 2

    if is_monorepo:
        return {
            "detectedRoots": sorted(subpackages),
            "recommendation": {"sourceFolders": None, "splitDepth": 2},
        }

    top_dirs = {p.split("/", 1)[0] for p in norm if "/" in p}
    for candidate in _SOURCE_DIR_CANDIDATES:
        if candidate in top_dirs:
            return {
                "detectedRoots": [candidate],
                "recommendation": {"sourceFolders": [candidate], "splitDepth": 1},
            }

    return {
        "detectedRoots": [],
        "recommendation": {"sourceFolders": None, "splitDepth": 1},
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _scan_paths(project_root: Path) -> list[str]:
    scan_path = project_root / ".understand-anything" / "intermediate" / "scan-result.json"
    data = json.loads(scan_path.read_text(encoding="utf-8"))
    files = data.get("files", [])
    return [f["path"] for f in files if isinstance(f, dict) and f.get("path")]


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise SystemExit("Usage: python -m understand_core.detect_layout <project-root>")
    project_root = Path(args[0]).resolve()
    result = detect_layout(_scan_paths(project_root))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
