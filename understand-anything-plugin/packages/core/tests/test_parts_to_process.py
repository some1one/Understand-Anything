"""Tests for understand_core.parts_to_process."""

from __future__ import annotations

import json
from pathlib import Path

from understand_core.parts_to_process import parts_to_process


def _config(tmp_path: Path, **fields) -> None:
    ua = tmp_path / ".understand-anything"
    ua.mkdir(parents=True, exist_ok=True)
    (ua / "config.json").write_text(json.dumps(fields))


def _partition_file(tmp_path: Path, part: str) -> None:
    d = tmp_path / ".understand-anything" / "partitions"
    d.mkdir(parents=True, exist_ok=True)
    (d / (part.replace("/", "~") + ".knowledge-graph.json")).write_text("{}")


def test_full_returns_all_included(tmp_path):
    _config(tmp_path, sourceFolders=["src"], splitDepth=1,
            includedParts=["src/api", "src/ui"])
    assert parts_to_process(tmp_path, full=True, changed_files=None) == [
        "src/api", "src/ui"
    ]


def test_incremental_affected_plus_pending(tmp_path):
    _config(tmp_path, sourceFolders=["src"], splitDepth=1,
            includedParts=["src/api", "src/ui"])
    # src/api already has a partition graph; src/ui does not (pending).
    _partition_file(tmp_path, "src/api")
    result = parts_to_process(
        tmp_path, full=False, changed_files=["src/api/handler.ts"]
    )
    # affected {src/api} ∪ pending {src/ui}
    assert result == ["src/api", "src/ui"]


def test_incremental_only_affected_when_none_pending(tmp_path):
    _config(tmp_path, sourceFolders=["src"], splitDepth=1,
            includedParts=["src/api", "src/ui"])
    _partition_file(tmp_path, "src/api")
    _partition_file(tmp_path, "src/ui")
    result = parts_to_process(
        tmp_path, full=False, changed_files=["src/ui/button.tsx"]
    )
    assert result == ["src/ui"]
