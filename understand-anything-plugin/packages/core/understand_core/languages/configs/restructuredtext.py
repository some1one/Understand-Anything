"""Port of ``configs/restructuredtext.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

restructuredtext_config = LanguageConfig(
    id="restructuredtext",
    displayName="reStructuredText",
    extensions=[".rst"],
    concepts=["headings", "directives", "roles", "cross-references", "toctree", "code blocks", "admonitions"],
    filePatterns={
        "entryPoints": ["index.rst"],
        "barrels": [],
        "tests": [],
        "config": [],
    },
)
