#!/usr/bin/env python3
"""Compatibility launcher for the native query_graph command."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from native_engine import request, run

MAX_PAYLOAD_BYTES = 32 * 1024


def serialize(payload):
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def build_payload(graph, query, technical_words=None):
    return request('query_payload', {'graph': graph, 'query': query, 'cachedWords': sorted(technical_words or [])})


def main(argv=None):
    return run('query_graph', argv)


if __name__ == '__main__':
    raise SystemExit(main())
