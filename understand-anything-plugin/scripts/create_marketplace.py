#!/usr/bin/env python3
"""Create an installer-owned local marketplace for both supported hosts.

Usage: create_marketplace.py <marketplace-root> <plugin-root>
The caller chooses the destination; this does not edit host configuration.
"""
import json
from pathlib import Path
import sys


def create_marketplace(root, plugin):
    root, plugin = Path(root).resolve(), Path(plugin).resolve()
    manifest = json.loads((plugin / ".claude-plugin/plugin.json").read_text())
    if manifest.get("name") != "understand-anything":
        raise ValueError("Expected the understand-anything plugin")
    codex = json.loads((plugin / ".codex-plugin/plugin.json").read_text())
    if codex.get("name") != manifest["name"]:
        raise ValueError("Claude and Codex plugin names must match")
    marker = root / ".understand-anything-marketplace"
    if root.exists() and any(root.iterdir()) and not marker.is_file():
        raise ValueError(f"Refusing to replace an unowned marketplace: {root}")
    target = root / "plugins/understand-anything"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        if target.resolve() != plugin:
            target.unlink()
            target.symlink_to(plugin, target_is_directory=True)
    elif target.exists():
        raise ValueError(f"Plugin destination already exists: {target}")
    else:
        target.symlink_to(plugin, target_is_directory=True)
    marker.touch()
    shared = {"name": "understand-anything"}
    catalogs = {
        ".claude-plugin/marketplace.json": {
            **shared,
            "owner": {"name": "Understand Anything contributors"},
            "metadata": {"description": "Local Understand Anything skills, agents, and hooks."},
            "plugins": [{**shared, "source": "./plugins/understand-anything"}],
        },
        ".agents/plugins/marketplace.json": {
            **shared,
            "interface": {"displayName": "Understand Anything"},
            "plugins": [{
                **shared,
                "source": {"source": "local", "path": "./plugins/understand-anything"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Developer Tools",
            }],
        },
    }
    for relative, data in catalogs.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n")
    return root


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: create_marketplace.py <marketplace-root> <plugin-root>")
    print(create_marketplace(*sys.argv[1:]))
