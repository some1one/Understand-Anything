"""Tests for the JSON Schema files and validator."""

from __future__ import annotations

import pytest

from arch_analysis.analyze import analyze
from arch_analysis.models import (
    AnalysisInput,
    AnalysisResult,
    ImportMapInput,
    ImportMapResult,
    LayersOutput,
    ScanResult,
    StructureInput,
    StructureOutput,
)
from arch_analysis.schema import (
    IMPORT_MAP_INPUT_SCHEMA_PATH,
    IMPORT_MAP_OUTPUT_SCHEMA_PATH,
    INPUT_SCHEMA_PATH,
    LAYERS_SCHEMA_PATH,
    OUTPUT_SCHEMA_PATH,
    SCAN_RESULT_SCHEMA_PATH,
    STRUCTURE_INPUT_SCHEMA_PATH,
    STRUCTURE_OUTPUT_SCHEMA_PATH,
    SchemaValidationError,
    _SCHEMA_MODELS,
    build_schema,
    load_schema,
    validate_input,
    validate_output,
    validate_scan_result,
)

from .test_analyze import SAMPLE


def test_schema_files_exist():
    assert INPUT_SCHEMA_PATH.exists()
    assert OUTPUT_SCHEMA_PATH.exists()
    assert LAYERS_SCHEMA_PATH.exists()
    assert SCAN_RESULT_SCHEMA_PATH.exists()
    assert IMPORT_MAP_INPUT_SCHEMA_PATH.exists()
    assert IMPORT_MAP_OUTPUT_SCHEMA_PATH.exists()
    assert STRUCTURE_INPUT_SCHEMA_PATH.exists()
    assert STRUCTURE_OUTPUT_SCHEMA_PATH.exists()


def test_stored_schemas_match_models():
    # Guards against drift: every on-disk file must equal what its model emits.
    for path, model in _SCHEMA_MODELS.items():
        assert load_schema(path) == build_schema(model), f"schema drift: {path.name}"


def test_scan_result_schema_validates_real_output(tmp_path):
    from arch_analysis.scan_project import scan_project

    (tmp_path / "a.ts").write_text("export const a = 1;\n")
    validate_scan_result(scan_project(tmp_path))


def test_valid_input_passes():
    validate_input(SAMPLE)  # should not raise


def test_invalid_input_rejected():
    bad = {"importEdges": []}  # missing required fileNodes
    with pytest.raises(SchemaValidationError):
        validate_input(bad)


def test_input_with_bad_field_type_rejected():
    bad = {"fileNodes": "not-a-list"}
    with pytest.raises(SchemaValidationError):
        validate_input(bad)


def test_analyze_output_validates_against_schema():
    result = analyze(AnalysisInput.model_validate(SAMPLE))
    validate_output(result)  # should not raise


def test_output_missing_required_key_rejected():
    result = analyze(AnalysisInput.model_validate(SAMPLE))
    del result["fileStats"]
    with pytest.raises(SchemaValidationError):
        validate_output(result)
