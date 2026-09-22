"""Persist partition config into ``.understand-anything/config.json``.

Merges the provided fields into the existing config (preserving unknown keys),
so ``/understand`` can remember the user's part selection across updates and the
add-part / load-graph skills can read it back.

Usage:
    python -m understand_core.write_config <project-root> \
        [--source=a,b] [--depth=N] [--parts=x,y] [--auto-update=true|false]

``--source=`` (empty) clears sourceFolders; ``--parts=`` clears includedParts.
At least one of sourceFolders / splitDepth must remain set after the update.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .models import partition_config_valid
from .persistence import load_config, save_config


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def apply_updates(config: dict[str, Any], args: list[str]) -> dict[str, Any]:
    """Apply ``--source/--depth/--parts/--auto-update`` flags to a config dict."""
    updated = dict(config)
    for arg in args:
        if arg.startswith("--source="):
            updated["sourceFolders"] = _csv(arg[len("--source="):]) or None
        elif arg.startswith("--depth="):
            raw = arg[len("--depth="):].strip()
            updated["splitDepth"] = int(raw) if raw else None
        elif arg.startswith("--parts="):
            updated["includedParts"] = _csv(arg[len("--parts="):])
        elif arg.startswith("--auto-update="):
            updated["autoUpdate"] = arg[len("--auto-update="):].strip().lower() == "true"
        else:
            raise SystemExit(f"Unknown argument: {arg}")
    return updated


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        sys.stderr.write(
            "Usage: python -m understand_core.write_config <project-root> "
            "[--source=a,b] [--depth=N] [--parts=x,y] [--auto-update=true|false]\n"
        )
        return 1

    project_root = Path(args[0]).resolve()
    config = apply_updates(load_config(project_root), args[1:])

    sources = config.get("sourceFolders")
    depth = config.get("splitDepth")
    if not partition_config_valid(sources, depth):
        sys.stderr.write(
            "Error: at least one of sourceFolders / splitDepth must be set.\n"
        )
        return 1

    save_config(project_root, config)
    sys.stdout.write(json.dumps(config, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
