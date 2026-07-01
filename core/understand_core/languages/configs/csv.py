"""Port of ``configs/csv.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

csv_config = LanguageConfig(
    id="csv",
    displayName="CSV",
    extensions=[".csv", ".tsv"],
    concepts=["headers", "rows", "delimiters", "quoting", "escaping"],
    filePatterns={
        "entryPoints": [],
        "barrels": [],
        "tests": [],
        "config": [],
    },
)
