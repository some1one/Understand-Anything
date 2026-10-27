#!/usr/bin/env python3
"""Print portable agent guidance or update only its marked AGENTS.md section."""
import argparse
from pathlib import Path

START = b"<!-- understand-anything:agent-instructions:start -->"
END = b"<!-- understand-anything:agent-instructions:end -->"
TEMPLATE = Path(__file__).resolve().parents[1] / "assets/agent-instructions.md"


def integrate(existing: bytes, section: bytes) -> bytes:
    starts, ends = existing.count(START), existing.count(END)
    if not starts and not ends:
        separator = b"" if not existing else b"\n" if existing.endswith(b"\n") else b"\n\n"
        return existing + separator + section + b"\n"
    if starts != 1 or ends != 1:
        raise ValueError("AGENTS.md has incomplete or duplicate Understand Anything markers")
    start, end = existing.index(START), existing.index(END)
    if end < start:
        raise ValueError("AGENTS.md has reversed Understand Anything markers")
    return existing[:start] + section + existing[end + len(END):]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--write", action="store_true", help="add or update the dedicated AGENTS.md section")
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    if not root.is_dir():
        parser.error(f"Project directory does not exist: {root}")
    section = TEMPLATE.read_bytes().rstrip(b"\n")
    if not args.write:
        print(section.decode("utf-8"))
        return 0
    destination = root / "AGENTS.md"
    if destination.is_symlink():
        parser.error("AGENTS.md is a symlink; integrate into its intended target explicitly")
    try:
        existing = destination.read_bytes() if destination.exists() else b""
        updated = integrate(existing, section)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if updated == existing:
        print(f"Unchanged: {destination}")
    else:
        destination.write_bytes(updated)
        print(f"Updated: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
