"""Port of ``configs/css.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

css_config = LanguageConfig(
    id="css",
    displayName="CSS",
    extensions=[".css", ".scss", ".less"],
    concepts=["selectors", "properties", "media queries", "flexbox", "grid", "variables", "animations", "specificity"],
    filePatterns={
        "entryPoints": [],
        "barrels": [],
        "tests": [],
        "config": [],
    },
)
