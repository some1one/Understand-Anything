#!/usr/bin/env python3
"""Check plugin updates on session start; never install or start graph work."""

import json
from pathlib import Path
import subprocess
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from data_directory import data_dir

def check_plugin_update():
    from update_plugin import check_plugin_update as check
    return check()

def read_object(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def context_for(event):
    if not isinstance(event, dict):
        return None
    name = event.get("hook_event_name")
    if name != "SessionStart":
        return None
    cwd = event.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return None
    # Do not parse or execute the user's shell command. Compare actual repository
    # state so aliases, merges, and commits made outside the host are covered.
    root = Path(subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
        check=True, capture_output=True, text=True, timeout=3,
    ).stdout.strip())
    graph_dir = data_dir(root)
    if read_object(graph_dir / "config.json").get("autoUpdate") is not True:
        return None
    if not (graph_dir / "knowledge-graph.json").is_file():
        return None
    previous = read_object(graph_dir / "meta.json").get("gitCommitHash")
    if not isinstance(previous, str) or not previous:
        return None
    current = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, timeout=3,
    ).stdout.strip()
    if not current or current == previous:
        return None
    prompt = Path(__file__).resolve().with_name("auto-update-prompt.md")
    return {
        "hookSpecificOutput": {
            "hookEventName": name,
            "additionalContext": (
                "[understand-anything] Auto-update is enabled and the graph's "
                f"commit differs from HEAD. Project root: {json.dumps(str(root))}. "
                f"To refresh it, use understand for this project (workflow: {json.dumps(str(prompt))}). "
                "Ask for confirmation before starting graph maintenance unless the user already requested that update. "
                "If analysis is already running, let that run finish first. "
                "Graph maintenance stays offline. Dictionary downloads belong to "
                "marketplace setup or explicit plugin maintenance via /understand-update."
            ),
        }
    }


def main():
    try:
        event = json.load(sys.stdin)
    except (OSError, ValueError):
        return
    if not isinstance(event, dict) or event.get("hook_event_name") != "SessionStart":
        return
    try:
        plugin_message = check_plugin_update()
    except Exception as error:
        # Optional maintenance must never abort an agent session.
        plugin_message = f"[understand-anything] Plugin update check skipped: {type(error).__name__}: {error}"
    try:
        result = context_for(event)
    except Exception:
        # Unborn/non-Git projects, missing files and malformed config are harmless.
        result = None
    if plugin_message:
        if result:
            result["hookSpecificOutput"]["additionalContext"] = plugin_message + "\n" + result["hookSpecificOutput"]["additionalContext"]
        else:
            result = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": plugin_message}}
        result["systemMessage"] = plugin_message
    if result:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
