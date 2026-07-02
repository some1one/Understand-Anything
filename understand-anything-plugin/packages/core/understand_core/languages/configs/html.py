"""Port of ``configs/html.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

html_config = LanguageConfig(
    id="html",
    displayName="HTML",
    extensions=[".html", ".htm"],
    concepts=["elements", "attributes", "semantic tags", "forms", "meta tags", "scripts", "stylesheets", "accessibility"],
    filePatterns={
        "entryPoints": ["index.html"],
        "barrels": [],
        "tests": [],
        "config": [],
    },
)
