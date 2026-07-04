"""Port of ``configs/plaintext.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

plaintext_config = LanguageConfig(
    id="plaintext",
    displayName="Plain Text",
    extensions=[".txt", ".text"],
    concepts=["paragraphs", "lists", "sections"],
    filePatterns={
        "entryPoints": [],
        "barrels": [],
        "tests": [],
        "config": [],
    },
)
