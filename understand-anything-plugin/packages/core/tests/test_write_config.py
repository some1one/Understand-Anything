"""Tests for understand_core.write_config."""

from __future__ import annotations

import json
from pathlib import Path

from understand_core.write_config import apply_updates
from understand_core.write_config import main as write_config_main


def test_apply_updates_sets_fields():
    cfg = apply_updates(
        {"autoUpdate": False},
        ["--source=src", "--depth=2", "--parts=src/api,src/ui"],
    )
    assert cfg["sourceFolders"] == ["src"]
    assert cfg["splitDepth"] == 2
    assert cfg["includedParts"] == ["src/api", "src/ui"]
    assert cfg["autoUpdate"] is False


def test_apply_updates_clears_and_toggles():
    cfg = apply_updates(
        {"sourceFolders": ["src"], "splitDepth": 1},
        ["--source=", "--auto-update=true"],
    )
    assert cfg["sourceFolders"] is None
    assert cfg["splitDepth"] == 1
    assert cfg["autoUpdate"] is True


def test_preserves_unknown_keys():
    cfg = apply_updates({"future": "x"}, ["--depth=1"])
    assert cfg["future"] == "x"


def test_main_round_trip_and_validation(tmp_path: Path):
    rc = write_config_main([str(tmp_path), "--source=src", "--depth=1", "--parts=src"])
    assert rc == 0
    config = json.loads((tmp_path / ".understand-anything" / "config.json").read_text())
    assert config["sourceFolders"] == ["src"]
    assert config["includedParts"] == ["src"]


def test_main_rejects_no_partition_config(tmp_path: Path):
    rc = write_config_main([str(tmp_path), "--source=", "--depth="])
    assert rc == 1
