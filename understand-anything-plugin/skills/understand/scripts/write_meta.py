#!/usr/bin/env python3
"""Write .understand-anything/meta.json after fingerprints succeed."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        sys.stderr.write("Usage: write_meta.py <project-root> <git-commit-hash> <analyzed-files>\n")
        return 1

    project_root = Path(args[0]).resolve()
    commit_hash = args[1]
    try:
        analyzed_files = int(args[2])
    except ValueError:
        sys.stderr.write(f"analyzed-files must be an integer: {args[2]}\n")
        return 1

    payload = {
        "lastAnalyzedAt": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "gitCommitHash": commit_hash,
        "version": "1.0.0",
        "analyzedFiles": analyzed_files,
    }
    path = project_root / ".understand-anything" / "meta.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    sys.stdout.write(str(path) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
