"""Compatibility transport only; deterministic behavior lives in Rust."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys

PLUGIN = Path(__file__).resolve().parents[1]


def command(name):
    override = os.environ.get('UA_ENGINE_BINARY')
    return [override or str(PLUGIN / 'packages/rust/run.sh'), name]


def run(name, args=None):
    return subprocess.run(command(name) + list(sys.argv[1:] if args is None else map(str, args))).returncode


def request(name, value):
    result = subprocess.run(command(name), input=json.dumps(value), text=True, capture_output=True)
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f'Native engine exited {result.returncode}')
    return json.loads(result.stdout)
