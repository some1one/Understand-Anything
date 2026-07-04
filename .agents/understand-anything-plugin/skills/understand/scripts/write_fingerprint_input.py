#!/usr/bin/env python3
"""Write build_fingerprints input from scan-result.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SOURCE_EXTENSIONS = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".py", ".go", ".rs", ".java", ".rb",
    ".cpp", ".cc", ".c", ".h", ".hpp",
    ".cs", ".swift", ".kt", ".php",
}


def is_source(path: str) -> bool:
    return Path(path).suffix.lower() in SOURCE_EXTENSIONS


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.stderr.write("Usage: write_fingerprint_input.py <project-root> <git-commit-hash>\n")
        return 1

    project_root = Path(args[0]).resolve()
    commit_hash = args[1]
    scan_path = project_root / ".understand-anything" / "intermediate" / "scan-result.json"
    out_path = project_root / ".understand-anything" / "intermediate" / "fingerprint-input.json"
    try:
        scan = json.loads(scan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        sys.stderr.write(f"Cannot read scan result {scan_path}: {err}\n")
        return 1

    files = scan.get("files", [])
    source_paths = sorted(
        f["path"]
        for f in files
        if isinstance(f, dict) and isinstance(f.get("path"), str) and is_source(f["path"])
    )
    payload = {
        "projectRoot": str(project_root),
        "sourceFilePaths": source_paths,
        "gitCommitHash": commit_hash,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    sys.stdout.write(str(out_path) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
