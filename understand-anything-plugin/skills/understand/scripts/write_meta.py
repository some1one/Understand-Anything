#!/usr/bin/env python3
"""Write meta.json in the selected project data directory after fingerprints succeed."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from data_directory import data_dir

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
    layout_path = data_dir(project_root) / "partition-layout.json"
    if layout_path.exists():
        try:
            payload["partitionLayout"] = json.loads(layout_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            sys.stderr.write(f"Cannot read partition layout: {err}\n")
            return 1
    scan_path = data_dir(project_root) / "intermediate" / "scan-result.json"
    if scan_path.exists():
        try:
            scan = json.loads(scan_path.read_text(encoding="utf-8"))
            patterns = scan.get("excludePatterns", [])
            if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
                raise ValueError("excludePatterns must be an array of strings")
        except (OSError, ValueError, AttributeError) as err:
            sys.stderr.write(f"Cannot read analysis scope: {err}\n")
            return 1
        if patterns:
            payload["excludePatterns"] = patterns
    path = data_dir(project_root) / "meta.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    sys.stdout.write(str(path) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
