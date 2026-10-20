"""Compatibility API for the native cache reader; no downloads."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from native_engine import request


def cached_words(graph_path, graph_bytes):
    return set(request('helper_request', {'operation': 'cached_words',
        'path': str(graph_path), 'raw': graph_bytes.decode('utf-8')}))
