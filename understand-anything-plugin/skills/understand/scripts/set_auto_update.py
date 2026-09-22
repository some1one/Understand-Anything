#!/usr/bin/env python3
"""Set only autoUpdate, preserving partition selection and other config keys."""
import json
from pathlib import Path
import sys


def main():
    path = Path(sys.argv[1]) / ".understand-anything" / "config.json"
    config = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(config, dict):
        raise ValueError("config.json must contain an object")
    config["autoUpdate"] = sys.argv[2] == "true"
    path.write_text(json.dumps(config, indent=2) + "\n")


if __name__ == "__main__":
    main()
