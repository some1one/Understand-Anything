"""Group scanned files into folder-parts for scoped analysis.

A *part* is a subset of the repo's files keyed by a directory prefix. Parts are
the unit of scoped ``/understand`` analysis: each part is analyzed independently
(reusing the incremental "file subset" plumbing) and merged back into the full
knowledge graph. :mod:`understand_core.detect_layout` derives the default
``{sourceFolders, splitDepth}`` recommendation that seeds the inclusion prompt.

Partition modes — at least one of ``sources`` / ``depth`` is required:

======================  ====================================================
Config                  Rule
======================  ====================================================
depth only              part = first ``depth`` dir components from repo root;
                        loose root files → ``_root``.
source only             files outside all sources → single ``_root`` part;
                        else part = ``<source>`` + first **1** rel-dir
                        component (files directly in a source → ``<source>``).
source + depth          like *source only*, but expand to ``depth`` rel-dir
                        components under the source.
======================  ====================================================

Paths are always repo-root-relative POSIX (matching ``ScanFile.path`` and the
``file:<path>`` node-id convention).

Usage:
    python -m understand_core.partition_files <project-root> \
        [--source=a,b] [--depth=N]

Reads ``intermediate/scan-result.json`` (``files[].path``) and writes
``intermediate/partitions.json`` = ``{"parts": {name: [paths...]},
"counts": {name: n}}``.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

ROOT_PART = "_root"


def _posix(path: str) -> str:
    """Normalise to forward slashes and strip a leading ``./`` / trailing ``/``."""
    p = path.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p.strip("/")


def _dir_components(path: str) -> list[str]:
    """Directory components of a file path (excludes the filename)."""
    segments = [s for s in path.split("/") if s]
    return segments[:-1]


def _normalize_sources(sources: Sequence[str] | None) -> list[str]:
    """Normalise, dedupe, and drop empties from a source-folder list."""
    if not sources:
        return []
    seen: dict[str, None] = {}
    for raw in sources:
        s = _posix(raw)
        if s:
            seen.setdefault(s, None)
    return list(seen.keys())


def _matching_source(path: str, sources: Sequence[str]) -> str | None:
    """Return the longest source that ``path`` lives under, or ``None``."""
    best: str | None = None
    for s in sources:
        if path.startswith(s + "/") and (best is None or len(s) > len(best)):
            best = s
    return best


def _part_key(path: str, sources: Sequence[str], depth: int | None) -> str:
    """Compute the part key for a single file path (see module docstring)."""
    dirs = _dir_components(path)

    if sources:
        src = _matching_source(path, sources)
        if src is None:
            return ROOT_PART
        src_depth = len(src.split("/"))
        rel_dirs = dirs[src_depth:]
        effective = depth if depth is not None else 1
        sub = rel_dirs[:effective]
        return "/".join([src, *sub]) if sub else src

    # depth-only mode (depth is guaranteed non-None here)
    assert depth is not None
    sub = dirs[:depth]
    return "/".join(sub) if sub else ROOT_PART


def partition_files(
    paths: Iterable[str],
    *,
    sources: Sequence[str] | None = None,
    depth: int | None = None,
) -> dict[str, list[str]]:
    """Group ``paths`` into parts. Requires at least one of ``sources``/``depth``.

    Returns a mapping ``{part_name: [sorted paths]}`` with keys in sorted order
    (deterministic output).
    """
    if not sources and depth is None:
        raise ValueError(
            "partition_files requires at least one of `sources` or `depth`"
        )
    if depth is not None and depth < 1:
        raise ValueError(f"depth must be >= 1, got {depth}")

    norm_sources = _normalize_sources(sources)
    buckets: dict[str, list[str]] = {}
    for raw in paths:
        p = _posix(raw)
        if not p:
            continue
        buckets.setdefault(_part_key(p, norm_sources, depth), []).append(p)

    return {key: sorted(buckets[key]) for key in sorted(buckets)}


def part_counts(parts: dict[str, list[str]]) -> dict[str, int]:
    """File count per part."""
    return {name: len(files) for name, files in parts.items()}


_PART_GRAPH_SUFFIX = ".knowledge-graph.json"


def part_to_filename(part: str) -> str:
    """Filesystem-safe filename for a part's graph (``/`` → ``~``).

    The real part name is always stored in the graph's ``part`` field; the
    filename only needs to be unique and path-safe.
    """
    return part.replace("/", "~") + _PART_GRAPH_SUFFIX


def filename_to_part(filename: str) -> str:
    """Inverse of :func:`part_to_filename` (``~`` → ``/``)."""
    stem = filename
    if stem.endswith(_PART_GRAPH_SUFFIX):
        stem = stem[: -len(_PART_GRAPH_SUFFIX)]
    return stem.replace("~", "/")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _scan_paths(project_root: Path) -> list[str]:
    scan_path = project_root / ".understand-anything" / "intermediate" / "scan-result.json"
    data = json.loads(scan_path.read_text(encoding="utf-8"))
    files = data.get("files", [])
    return [f["path"] for f in files if isinstance(f, dict) and f.get("path")]


def _parse_args(argv: list[str]) -> tuple[Path, list[str] | None, int | None]:
    if not argv:
        raise SystemExit(
            "Usage: python -m understand_core.partition_files <project-root> "
            "[--source=a,b] [--depth=N]"
        )
    project_root = Path(argv[0]).resolve()
    sources: list[str] | None = None
    depth: int | None = None
    for arg in argv[1:]:
        if arg.startswith("--source="):
            sources = [s for s in arg[len("--source="):].split(",") if s.strip()]
        elif arg.startswith("--depth="):
            depth = int(arg[len("--depth="):])
    return project_root, sources, depth


def write_part_file_lists(project_root: Path, parts: dict[str, list[str]]) -> Path:
    """Write one newline-delimited file list per part for ``--changed-files``.

    Returns the directory holding ``<part>.txt`` files (encoded filenames).
    """
    out_dir = project_root / ".understand-anything" / "intermediate" / "part-files"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Clear stale lists so a re-partition never leaves an orphaned part.
    for stale in out_dir.glob("*.txt"):
        stale.unlink()
    for name, files in parts.items():
        list_path = out_dir / (name.replace("/", "~") + ".txt")
        list_path.write_text("\n".join(files) + "\n", encoding="utf-8")
    return out_dir


def main(argv: list[str] | None = None) -> None:
    project_root, sources, depth = _parse_args(list(sys.argv[1:] if argv is None else argv))
    paths = _scan_paths(project_root)
    parts = partition_files(paths, sources=sources, depth=depth)

    out: dict[str, Any] = {"parts": parts, "counts": part_counts(parts)}
    out_path = project_root / ".understand-anything" / "intermediate" / "partitions.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    write_part_file_lists(project_root, parts)

    print(f"Partitioned {len(paths)} files into {len(parts)} parts:", file=sys.stderr)
    for name, count in sorted(out["counts"].items()):
        print(f"  {count:>5}  {name}", file=sys.stderr)


if __name__ == "__main__":
    main()
