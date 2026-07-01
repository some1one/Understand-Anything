"""Port of ``configs/env.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

env_config = LanguageConfig(
    id="env",
    displayName="Environment Variables",
    extensions=[".env"],
    filenames=[".env", ".env.local", ".env.development", ".env.production", ".env.test", ".env.example"],
    concepts=["key-value pairs", "variable interpolation", "secrets", "environment-specific config"],
    filePatterns={
        "entryPoints": [],
        "barrels": [],
        "tests": [],
        "config": [".env", ".env.*"],
    },
)
