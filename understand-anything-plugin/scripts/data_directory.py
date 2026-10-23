#!/usr/bin/env python3
"""Resolve project artifacts without creating directories or mixing snapshots."""
from pathlib import Path
import sys


def data_dir(project_root: Path) -> Path:
    current = project_root / ".ua"
    legacy = project_root / ".understand-anything"
    return current if current.is_dir() or not legacy.is_dir() else legacy


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: data_directory.py <project-root>")
    print(data_dir(Path(sys.argv[1]).resolve()))
