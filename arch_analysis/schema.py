"""JSON Schema generation and validation.

The canonical schemas are the pydantic models in :mod:`arch_analysis.models`.
This module renders them to standalone JSON Schema files (``schemas/*.json``)
and validates arbitrary JSON payloads against those files with ``jsonschema``.

Regenerate the on-disk schemas after changing the models::

    pdm run python -m arch_analysis.schema
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel

from .models import (
    AnalysisInput,
    AnalysisResult,
    ImportMapInput,
    ImportMapResult,
    LayersOutput,
    ScanResult,
    StructureInput,
    StructureOutput,
)

SCHEMA_DIR = Path(__file__).parent / "schemas"
INPUT_SCHEMA_PATH = SCHEMA_DIR / "input.schema.json"
OUTPUT_SCHEMA_PATH = SCHEMA_DIR / "output.schema.json"
LAYERS_SCHEMA_PATH = SCHEMA_DIR / "layers.schema.json"
SCAN_RESULT_SCHEMA_PATH = SCHEMA_DIR / "scan-result.schema.json"
IMPORT_MAP_INPUT_SCHEMA_PATH = SCHEMA_DIR / "import-map-input.schema.json"
IMPORT_MAP_OUTPUT_SCHEMA_PATH = SCHEMA_DIR / "import-map-output.schema.json"
STRUCTURE_INPUT_SCHEMA_PATH = SCHEMA_DIR / "structure-input.schema.json"
STRUCTURE_OUTPUT_SCHEMA_PATH = SCHEMA_DIR / "structure-output.schema.json"

# Maps each on-disk schema to the pydantic model that defines it.
_SCHEMA_MODELS: dict[Path, type[BaseModel]] = {
    INPUT_SCHEMA_PATH: AnalysisInput,
    OUTPUT_SCHEMA_PATH: AnalysisResult,
    LAYERS_SCHEMA_PATH: LayersOutput,
    SCAN_RESULT_SCHEMA_PATH: ScanResult,
    IMPORT_MAP_INPUT_SCHEMA_PATH: ImportMapInput,
    IMPORT_MAP_OUTPUT_SCHEMA_PATH: ImportMapResult,
    STRUCTURE_INPUT_SCHEMA_PATH: StructureInput,
    STRUCTURE_OUTPUT_SCHEMA_PATH: StructureOutput,
}


class SchemaValidationError(ValueError):
    """Raised when a payload does not conform to its JSON Schema."""


def build_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Render a pydantic model to a JSON Schema dict."""
    return model.model_json_schema()


def generate_schemas() -> list[Path]:
    """Write fresh JSON Schema files from the pydantic models."""
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for path, model in _SCHEMA_MODELS.items():
        path.write_text(json.dumps(build_schema(model), indent=2) + "\n")
        written.append(path)
    return written


def load_schema(path: Path) -> dict[str, Any]:
    """Load a JSON Schema file from disk."""
    return json.loads(path.read_text())


def _validate(data: Any, schema_path: Path) -> None:
    validator = Draft202012Validator(load_schema(schema_path))
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        detail = "; ".join(
            f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors
        )
        raise SchemaValidationError(detail)


def validate_input(data: Any) -> None:
    """Validate an input payload against ``input.schema.json``."""
    _validate(data, INPUT_SCHEMA_PATH)


def validate_output(data: Any) -> None:
    """Validate a result payload against ``output.schema.json``."""
    _validate(data, OUTPUT_SCHEMA_PATH)


def validate_layers(data: Any) -> None:
    """Validate a Phase 2 layers array against ``layers.schema.json``."""
    _validate(data, LAYERS_SCHEMA_PATH)


def validate_scan_result(data: Any) -> None:
    """Validate a scan-result payload against ``scan-result.schema.json``."""
    _validate(data, SCAN_RESULT_SCHEMA_PATH)


def validate_import_map_input(data: Any) -> None:
    """Validate an import-map input against ``import-map-input.schema.json``."""
    _validate(data, IMPORT_MAP_INPUT_SCHEMA_PATH)


def validate_import_map_output(data: Any) -> None:
    """Validate an import-map result against ``import-map-output.schema.json``."""
    _validate(data, IMPORT_MAP_OUTPUT_SCHEMA_PATH)


def validate_structure_input(data: Any) -> None:
    """Validate a structure input against ``structure-input.schema.json``."""
    _validate(data, STRUCTURE_INPUT_SCHEMA_PATH)


def validate_structure_output(data: Any) -> None:
    """Validate a structure output against ``structure-output.schema.json``."""
    _validate(data, STRUCTURE_OUTPUT_SCHEMA_PATH)


if __name__ == "__main__":
    for p in generate_schemas():
        print(f"wrote {p}")
