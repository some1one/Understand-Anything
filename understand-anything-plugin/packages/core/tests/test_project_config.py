"""Tests for the ProjectConfig model and partition-config validation."""

from __future__ import annotations

from understand_core.models import ProjectConfig, partition_config_valid


def test_legacy_config_parses():
    cfg = ProjectConfig.model_validate({"autoUpdate": True})
    assert cfg.autoUpdate is True
    assert cfg.sourceFolders is None
    assert cfg.splitDepth is None
    assert cfg.includedParts == []
    assert cfg.is_partitioned is False


def test_partitioned_config():
    cfg = ProjectConfig.model_validate(
        {"sourceFolders": ["src"], "splitDepth": 2, "includedParts": ["src/api", "src/ui"]}
    )
    assert cfg.is_partitioned is True
    assert cfg.includedParts == ["src/api", "src/ui"]


def test_depth_only_is_partitioned():
    assert ProjectConfig(splitDepth=1).is_partitioned is True


def test_extra_fields_preserved():
    cfg = ProjectConfig.model_validate({"autoUpdate": False, "future": "x"})
    assert cfg.model_dump(by_alias=True).get("future") == "x"


def test_partition_config_valid():
    assert partition_config_valid(["src"], None) is True
    assert partition_config_valid(None, 2) is True
    assert partition_config_valid([], None) is False
    assert partition_config_valid(None, None) is False
