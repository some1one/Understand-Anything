"""Port of ``configs/json-config.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

json_config_config = LanguageConfig(
    id="json",
    displayName="JSON",
    extensions=[".json", ".jsonc"],
    concepts=["objects", "arrays", "nesting", "schema references", "comments (JSONC)"],
    filePatterns={
        "entryPoints": ["package.json"],
        "barrels": [],
        "tests": [],
        "config": ["tsconfig.json", "package.json", ".eslintrc.json"],
    },
)
