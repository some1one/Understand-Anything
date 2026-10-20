#!/usr/bin/env python3
"""Compatibility launcher for the native write_changed_files command."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from native_engine import request, run


def main(argv=None):
    return run('write_changed_files', argv)


if __name__ == '__main__':
    raise SystemExit(main())
