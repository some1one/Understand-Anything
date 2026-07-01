"""Port of ``configs/sql.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

sql_config = LanguageConfig(
    id="sql",
    displayName="SQL",
    extensions=[".sql"],
    concepts=["tables", "columns", "indexes", "foreign keys", "views", "stored procedures", "triggers", "migrations"],
    filePatterns={
        "entryPoints": [],
        "barrels": [],
        "tests": [],
        "config": [],
    },
)
