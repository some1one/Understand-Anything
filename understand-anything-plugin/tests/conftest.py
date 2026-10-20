"""Offline dictionary fixtures for query migration tests."""
import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def query_dictionaries(request, tmp_path_factory, monkeypatch):
    if request.module.__name__ not in {'test_query_dictionary', 'test_review_fixes'}:
        return
    plugin = Path(__file__).resolve().parents[1]
    config = tmp_path_factory.mktemp('query-config') / 'dictionary-config.json'
    config.write_text(json.dumps({'version': 1}))
    monkeypatch.setenv('UA_DICTIONARY_CONFIG', str(config))
    monkeypatch.setenv('UA_DICTIONARY_DIR', str(plugin / 'packages/rust/tests/fixtures/dictionaries'))
