#!/usr/bin/env python3
"""Compatibility launcher for the native prune_incremental_batch command."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from native_engine import request, run


def main(argv=None):
    return run('prune_incremental_batch', argv)


if __name__ == '__main__':
    raise SystemExit(main())
