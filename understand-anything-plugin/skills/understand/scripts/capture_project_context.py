#!/usr/bin/env python3
"""Compatibility launcher for the native capture_project_context command."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from native_engine import request, run

def _dir_tree(root):
    return request('helper_request', {'operation': 'shallow_tree', 'root': str(root)})


def main(argv=None):
    return run('capture_project_context', argv)


if __name__ == '__main__':
    raise SystemExit(main())
