"""Port of ``configs/json-schema.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

# Note: JSON Schema files have no unique extension -- *.schema.json files match json_config_config by the .json extension. Detection requires content-based heuristics; a future pass could re-classify them.
json_schema_config = LanguageConfig(
    id="json-schema",
    displayName="JSON Schema",
    extensions=[],
    concepts=["types", "properties", "required fields", "$ref", "$defs", "allOf/anyOf/oneOf", "patterns", "validation"],
    filePatterns={
        "entryPoints": [],
        "barrels": [],
        "tests": [],
        "config": [],
    },
)
