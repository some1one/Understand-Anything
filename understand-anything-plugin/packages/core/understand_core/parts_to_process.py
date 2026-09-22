"""Decide which parts ``/understand`` should (re)analyze on this run.

Centralises the selection so the skill makes one call:

  * **Full** (``--full``, ``--all``, first run, or no changed-files list)
    → every included part.
  * **Incremental** → parts **affected** by the changed files, PLUS any included
    part that has no ``partitions/<part>.knowledge-graph.json`` yet (e.g. a part
    just added via ``/understand-add-part``). Everything intersected with the
    included selection.

Prints the part names one per line.

Usage:
    python -m understand_core.parts_to_process <project-root> \
        [--full] [--changed=<changed-files.txt>]
"""

from __future__ import annotations

import sys
from pathlib import Path

from .affected_parts import affected_parts
from .partition_files import part_to_filename
from .persistence import load_config


def parts_to_process(
    project_root: Path,
    *,
    full: bool,
    changed_files: list[str] | None,
) -> list[str]:
    config = load_config(project_root)
    included = config.get("includedParts") or []
    if full or not changed_files:
        return list(included)

    affected = affected_parts(
        changed_files,
        sources=config.get("sourceFolders"),
        depth=config.get("splitDepth"),
        included=included or None,
    )
    partitions_dir = project_root / ".understand-anything" / "partitions"
    pending = [
        p for p in included if not (partitions_dir / part_to_filename(p)).exists()
    ]
    return sorted(set(affected) | set(pending))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        sys.stderr.write(
            "Usage: python -m understand_core.parts_to_process <project-root> "
            "[--full] [--changed=<file>]\n"
        )
        return 1

    project_root = Path(args[0]).resolve()
    full = "--full" in args
    changed_files: list[str] | None = None
    for arg in args[1:]:
        if arg.startswith("--changed="):
            path = Path(arg[len("--changed="):])
            if path.exists():
                changed_files = [
                    line.strip()
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]

    for name in parts_to_process(project_root, full=full, changed_files=changed_files):
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
