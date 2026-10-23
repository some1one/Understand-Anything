"""Small offline contracts for the opt-in native benchmark."""
import importlib.util
import json
from pathlib import Path
import sys

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from benchmark.contract import digest, new_report

SCHEMA = json.loads((ROOT / 'docs/benchmarks/large-repo-report-2.0.0.schema.json').read_text())


def validate(report):
    jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker()).validate(report)


def test_partial_failure_contract():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    validate(new_report())
    report = new_report()
    report['status'] = 'ok'
    with pytest.raises(jsonschema.ValidationError):
        validate(report)


def test_semantic_digest_uses_canonical_json():
    assert digest({'a': 1, 'b': 2}) == digest({'b': 2, 'a': 1})
    assert digest({'a': 1}) != digest({'a': 2})
