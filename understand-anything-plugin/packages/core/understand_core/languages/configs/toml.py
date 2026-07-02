"""Port of ``configs/toml.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

toml_config = LanguageConfig(
    id="toml",
    displayName="TOML",
    extensions=[".toml"],
    concepts=["tables", "inline tables", "arrays of tables", "key-value pairs", "dotted keys"],
    filePatterns={
        "entryPoints": [],
        "barrels": [],
        "tests": [],
        "config": ["Cargo.toml", "pyproject.toml", "netlify.toml"],
    },
)
