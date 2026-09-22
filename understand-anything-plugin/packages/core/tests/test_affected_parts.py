"""Tests for understand_core.affected_parts and per-part file lists."""

from __future__ import annotations

from pathlib import Path

from understand_core.affected_parts import affected_parts
from understand_core.partition_files import partition_files, write_part_file_lists


def test_affected_parts_depth():
    changed = ["src/api/h.ts", "docs/readme.md"]
    parts = affected_parts(changed, sources=None, depth=1, included=None)
    assert parts == ["docs", "src"]


def test_affected_parts_intersect_included():
    changed = ["src/api/h.ts", "src/ui/b.tsx"]
    parts = affected_parts(
        changed, sources=["src"], depth=1, included=["src/api"]
    )
    assert parts == ["src/api"]  # src/ui excluded


def test_affected_parts_empty():
    assert affected_parts([], sources=None, depth=1, included=None) == []


def test_write_part_file_lists_and_clears_stale(tmp_path: Path):
    parts = partition_files(["src/a.ts", "src/api/b.ts", "top.md"], depth=1)
    out_dir = write_part_file_lists(tmp_path, parts)
    assert (out_dir / "src.txt").read_text().split() == ["src/a.ts", "src/api/b.ts"]
    assert (out_dir / "_root.txt").read_text().strip() == "top.md"

    # Re-partition with fewer parts → stale list removed.
    write_part_file_lists(tmp_path, partition_files(["src/a.ts"], depth=1))
    assert not (out_dir / "_root.txt").exists()
    assert (out_dir / "src.txt").exists()
