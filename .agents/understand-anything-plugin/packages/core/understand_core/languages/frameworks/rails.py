"""Port of ``frameworks/rails.ts``."""

from __future__ import annotations

from ..types import FrameworkConfig

rails_config = FrameworkConfig(
    id="rails",
    displayName="Ruby on Rails",
    languages=["ruby"],
    detectionKeywords=["rails", "railties", "actionpack", "activerecord", "actionview"],
    manifestFiles=["Gemfile"],
    promptSnippetPath="skills/understand-framework/prompts/rails.md",
    entryPoints=["config.ru", "bin/rails"],
    layerHints={
        "controllers": "api",
        "models": "data",
        "views": "ui",
        "helpers": "utility",
        "mailers": "service",
        "jobs": "service",
        "channels": "service",
        "middleware": "middleware",
        "lib": "service",
    },
)
