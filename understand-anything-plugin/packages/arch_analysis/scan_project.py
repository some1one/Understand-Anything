"""Deterministic file enumeration + language/category detection.

Python port of ``skills/understand/scan-project.mjs``. Owns:
  - File enumeration (git ls-files preferred, recursive walk fallback)
  - ``.understandignore`` filtering (via :mod:`arch_analysis.languages`)
  - Per-file language + category detection and line counting
  - Complexity estimation

Usage:
    python -m arch_analysis.scan_project <projectRoot> <outputPath>

Logging is stderr only (stdout reserved for piped tooling). Per-file read/stat
failures emit a ``Warning: scan-project: ...`` line and drop the file; the rest
of the scan completes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .languages import (
    create_ignore_filter,
    build_defaults_only_filter,
    detect_category,
    detect_language,
    enumerate_files,
    estimate_complexity,
    has_user_ignore_file,
    is_unsupported_file,
)


def _count_lines(abs_path: Path, posix_path: str) -> int | None:
    """Count ``\\n`` bytes (wc -l semantics). None on read failure (+ warning)."""
    try:
        data = abs_path.read_bytes()
    except OSError as err:
        sys.stderr.write(
            f"Warning: scan-project: {posix_path} — line count failed "
            f"({err}) — file skipped from output\n"
        )
        return None
    return data.count(b"\n")


def scan_project(project_root: str | Path) -> dict[str, Any]:
    """Scan ``project_root`` and return the scan-result payload dict."""
    root = Path(project_root)

    candidates = enumerate_files(root)

    combined = create_ignore_filter(root)
    user_ignores_present = has_user_ignore_file(root)
    defaults_only = build_defaults_only_filter() if user_ignores_present else combined

    filtered_by_ignore = 0
    kept: list[str] = []
    for rel in candidates:
        if not combined.is_ignored(rel):
            kept.append(rel)
            continue
        # Dropped by combined filter; attribute to the user only if the
        # defaults-only filter would have kept it.
        if user_ignores_present and not defaults_only.is_ignored(rel):
            filtered_by_ignore += 1

    file_entries: list[dict[str, Any]] = []
    for rel in kept:
        if is_unsupported_file(rel):
            continue
        abs_path = root / rel
        try:
            st = abs_path.stat()
        except OSError as err:
            sys.stderr.write(
                f"Warning: scan-project: {rel} — stat failed ({err}) "
                f"— file skipped from output\n"
            )
            continue
        if not abs_path.is_file():
            # Symlink-to-dir / special files — skip silently.
            continue
        _ = st
        size_lines = _count_lines(abs_path, rel)
        if size_lines is None:
            continue
        file_entries.append(
            {
                "path": rel,
                "language": detect_language(rel),
                "sizeLines": size_lines,
                "fileCategory": detect_category(rel),
            }
        )

    # Determinism: stable code-point sort by path.
    file_entries.sort(key=lambda f: f["path"])

    by_category: dict[str, int] = {}
    by_language: dict[str, int] = {}
    for f in file_entries:
        by_category[f["fileCategory"]] = by_category.get(f["fileCategory"], 0) + 1
        by_language[f["language"]] = by_language.get(f["language"], 0) + 1

    estimated_complexity = estimate_complexity(len(file_entries))

    return {
        "scriptCompleted": True,
        "files": file_entries,
        "totalFiles": len(file_entries),
        "filteredByIgnore": filtered_by_ignore,
        "estimatedComplexity": estimated_complexity,
        "stats": {
            "filesScanned": len(file_entries),
            "byCategory": by_category,
            "byLanguage": by_language,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2:
        sys.stderr.write(
            "Usage: python -m arch_analysis.scan_project <projectRoot> <outputPath>\n"
        )
        return 1

    project_root, output_path = args[0], args[1]
    root = Path(project_root)
    if not root.exists():
        sys.stderr.write(
            f"scan_project failed: projectRoot does not exist: {project_root}\n"
        )
        return 1
    if not root.is_dir():
        sys.stderr.write(
            f"scan_project failed: projectRoot is not a directory: {project_root}\n"
        )
        return 1

    output = scan_project(root)
    Path(output_path).write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    sys.stderr.write(
        f"scan-project: filesScanned={output['totalFiles']} "
        f"filteredByIgnore={output['filteredByIgnore']} "
        f"complexity={output['estimatedComplexity']}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
