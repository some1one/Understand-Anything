"""Port of ``configs/yaml.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

yaml_config = LanguageConfig(
    id="yaml",
    displayName="YAML",
    extensions=[".yaml", ".yml"],
    concepts=["mappings", "sequences", "anchors", "aliases", "multi-document", "tags"],
    filePatterns={
        "entryPoints": [],
        "barrels": [],
        "tests": [],
        "config": ["*.yaml", "*.yml"],
    },
)
