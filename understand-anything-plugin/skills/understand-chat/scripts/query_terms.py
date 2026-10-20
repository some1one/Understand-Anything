"""Compatibility API; tokenization and filtering are implemented in Rust."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from native_engine import request


def query_terms(query, graph_words=None, cached_words=None):
    return [frozenset(words) for words in request('query_terms', {
        'query': query, 'graphWords': sorted(graph_words or []), 'cachedWords': sorted(cached_words or [])})]


def graph_vocabulary(nodes):
    return set(request('helper_request', {'operation': 'graph_vocabulary', 'graph': {'nodes': nodes}}))
