#!/usr/bin/env python3
"""Compatibility launcher for the native diff_context command."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from native_engine import request, run

def changed_files(project_root, base=None):
    files, label = request('helper_request', {'operation': 'diff_files', 'root': str(project_root), 'base': base})
    return files, label


def default_base(project_root):
    return request('helper_request', {'operation': 'default_base', 'root': str(project_root)})


def main(argv=None):
    return run('diff_context', argv)


if __name__ == '__main__':
    raise SystemExit(main())
