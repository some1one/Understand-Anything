#!/usr/bin/env python3
"""Write changed files between a stored commit and HEAD."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.stderr.write("Usage: write_changed_files.py <project-root> <last-commit-hash>\n")
        return 1

    project_root = Path(args[0]).resolve()
    last_commit = args[1]
    result = subprocess.run(
        ["git", "diff", f"{last_commit}..HEAD", "--name-only"],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return result.returncode

    out_path = project_root / ".understand-anything" / "tmp" / "changed-files.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result.stdout, encoding="utf-8")
    sys.stdout.write(str(out_path) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
