"""Tests for the JSON Schema files and validator."""

from __future__ import annotations

import pytest

from arch_analysis.analyze import analyze
from arch_analysis.models import AnalysisInput, AnalysisResult
from arch_analysis.models import LayersOutput
from arch_analysis.schema import (
    INPUT_SCHEMA_PATH,
    LAYERS_SCHEMA_PATH,
    OUTPUT_SCHEMA_PATH,
    SchemaValidationError,
    build_schema,
    load_schema,
    validate_input,
    validate_output,
)

from .test_analyze import SAMPLE


def test_schema_files_exist():
    assert INPUT_SCHEMA_PATH.exists()
    assert OUTPUT_SCHEMA_PATH.exists()
    assert LAYERS_SCHEMA_PATH.exists()


def test_stored_schemas_match_models():
    # Guards against drift: the on-disk files must equal what the models emit.
    assert load_schema(INPUT_SCHEMA_PATH) == build_schema(AnalysisInput)
    assert load_schema(OUTPUT_SCHEMA_PATH) == build_schema(AnalysisResult)
    assert load_schema(LAYERS_SCHEMA_PATH) == build_schema(LayersOutput)


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
