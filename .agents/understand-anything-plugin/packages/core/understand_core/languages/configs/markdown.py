"""Port of ``configs/markdown.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

markdown_config = LanguageConfig(
    id="markdown",
    displayName="Markdown",
    extensions=[".md", ".mdx"],
    concepts=["headings", "links", "code blocks", "front matter", "lists", "tables", "images"],
    filePatterns={
        "entryPoints": ["README.md"],
        "barrels": [],
        "tests": [],
        "config": [],
    },
)
