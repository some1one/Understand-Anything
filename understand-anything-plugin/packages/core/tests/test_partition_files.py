"""Tests for understand_core.partition_files."""

from __future__ import annotations

import pytest

from understand_core.partition_files import (
    ROOT_PART,
    filename_to_part,
    part_counts,
    part_to_filename,
    partition_files,
)

FILES = [
    "README.md",
    "scripts/build.sh",
    "src/main.ts",
    "src/api/handler.ts",
    "src/api/routes.ts",
    "src/ui/button.tsx",
    "src/ui/theme/colors.ts",
]


def test_requires_source_or_depth():
    with pytest.raises(ValueError):
        partition_files(FILES)


def test_rejects_zero_depth():
    with pytest.raises(ValueError):
        partition_files(FILES, depth=0)


def test_depth_only_top_level():
    parts = partition_files(FILES, depth=1)
    assert parts == {
        ROOT_PART: ["README.md"],
        "scripts": ["scripts/build.sh"],
        "src": [
            "src/api/handler.ts",
            "src/api/routes.ts",
            "src/main.ts",
            "src/ui/button.tsx",
            "src/ui/theme/colors.ts",
        ],
    }


def test_depth_two():
    parts = partition_files(FILES, depth=2)
    # depth-1 folders keep their own part; depth-2 paths split further.
    assert parts[ROOT_PART] == ["README.md"]
    assert parts["scripts"] == ["scripts/build.sh"]
    assert parts["src"] == ["src/main.ts"]
    assert parts["src/api"] == ["src/api/handler.ts", "src/api/routes.ts"]
    assert parts["src/ui"] == ["src/ui/button.tsx", "src/ui/theme/colors.ts"]


def test_source_only_subfolders_are_parts_root_is_outside():
    parts = partition_files(FILES, sources=["src"])
    # Everything outside src → single _root part.
    assert set(parts[ROOT_PART]) == {"README.md", "scripts/build.sh"}
    # Files directly in src → the "src" part; each subfolder its own part.
    assert parts["src"] == ["src/main.ts"]
    assert parts["src/api"] == ["src/api/handler.ts", "src/api/routes.ts"]
    assert parts["src/ui"] == ["src/ui/button.tsx", "src/ui/theme/colors.ts"]


def test_source_and_depth_expands_under_source():
    parts = partition_files(FILES, sources=["src"], depth=2)
    assert set(parts[ROOT_PART]) == {"README.md", "scripts/build.sh"}
    assert parts["src"] == ["src/main.ts"]
    assert parts["src/api"] == ["src/api/handler.ts", "src/api/routes.ts"]
    assert parts["src/ui"] == ["src/ui/button.tsx"]
    assert parts["src/ui/theme"] == ["src/ui/theme/colors.ts"]


def test_multiple_sources_longest_prefix_wins():
    files = ["packages/a/x.ts", "packages/a/sub/y.ts", "packages/b/z.ts", "top.md"]
    parts = partition_files(files, sources=["packages/a", "packages/b"])
    assert parts[ROOT_PART] == ["top.md"]
    assert parts["packages/a"] == ["packages/a/x.ts"]
    assert parts["packages/a/sub"] == ["packages/a/sub/y.ts"]
    assert parts["packages/b"] == ["packages/b/z.ts"]


def test_normalizes_paths_and_is_deterministic():
    parts = partition_files(["./src/a.ts", "src\\b.ts"], depth=1)
    assert parts == {"src": ["src/a.ts", "src/b.ts"]}
    # keys are sorted
    assert list(partition_files(FILES, depth=1).keys()) == sorted(
        partition_files(FILES, depth=1).keys()
    )


def test_part_counts():
    parts = partition_files(FILES, depth=1)
    counts = part_counts(parts)
    assert counts["src"] == 5
    assert counts[ROOT_PART] == 1


def test_filename_round_trip():
    for part in ["src", "src/api", "packages/a/sub", ROOT_PART]:
        fname = part_to_filename(part)
        assert fname.endswith(".knowledge-graph.json")
        assert "/" not in fname
        assert filename_to_part(fname) == part
