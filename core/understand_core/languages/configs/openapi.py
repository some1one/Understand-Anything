"""Port of ``configs/openapi.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

openapi_config = LanguageConfig(
    id="openapi",
    displayName="OpenAPI",
    extensions=[],
    filenames=["openapi.yaml", "openapi.json", "swagger.yaml", "swagger.json"],
    concepts=["paths", "operations", "schemas", "parameters", "responses", "security schemes", "tags", "servers"],
    filePatterns={
        "entryPoints": ["openapi.yaml", "swagger.yaml"],
        "barrels": [],
        "tests": [],
        "config": [],
    },
)
