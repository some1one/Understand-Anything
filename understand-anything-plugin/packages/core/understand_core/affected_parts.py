"""Map changed files to the parts that must be re-analyzed (incremental runs).

Reads the persisted partition config (``sourceFolders`` / ``splitDepth`` /
``includedParts``) and a changed-files list, partitions the changed files with
the same rules, and prints the affected part names — intersected with the
included selection (a change to an excluded part is ignored).

Usage:
    python -m understand_core.affected_parts <project-root> <changed-files.txt>
"""

from __future__ import annotations

import sys
from pathlib import Path

from .partition_files import partition_files
from .persistence import load_config


def affected_parts(
    changed_files: list[str],
    *,
    sources: list[str] | None,
    depth: int | None,
    included: list[str] | None,
) -> list[str]:
    """Return the sorted parts touched by ``changed_files`` (∩ ``included``)."""
    if not changed_files:
        return []
    parts = partition_files(changed_files, sources=sources, depth=depth)
    names = set(parts.keys())
    if included:
        names &= set(included)
    return sorted(names)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        sys.stderr.write(
            "Usage: python -m understand_core.affected_parts "
            "<project-root> <changed-files.txt>\n"
        )
        return 1

    project_root = Path(args[0]).resolve()
    changed_path = Path(args[1])
    changed = [
        line.strip()
        for line in changed_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    config = load_config(project_root)
    names = affected_parts(
        changed,
        sources=config.get("sourceFolders"),
        depth=config.get("splitDepth"),
        included=config.get("includedParts") or None,
    )
    for name in names:
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
