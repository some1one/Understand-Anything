#!/usr/bin/env python3
"""Pull plugin source on session start and suggest opt-in project graph upkeep."""

import json
from pathlib import Path
import subprocess
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from data_directory import data_dir
from update_plugin import update_plugin

def read_object(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def context_for(event):
    if not isinstance(event, dict):
        return None
    name = event.get("hook_event_name")
    if not isinstance(name, str) or name not in {"SessionStart", "PostToolUse"}:
        return None
    if name == "PostToolUse":
        tool_name = event.get("tool_name")
        if not isinstance(tool_name, str) or tool_name not in {"Bash", "exec_command", "shell", "shell_command"}:
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
                f"Read {json.dumps(str(prompt))} and follow its update workflow "
                "for this project within the current task's permissions. "
                "If analysis is already running, let that run finish first. "
                "Graph maintenance stays offline. Dictionary downloads run only "
                "during explicit plugin maintenance via /understand-update."
            ),
        }
    }


def main():
    try:
        event = json.load(sys.stdin)
    except (OSError, ValueError):
        return
    plugin_message = None
    if isinstance(event, dict) and event.get("hook_event_name") == "SessionStart":
        plugin_message = update_plugin()
    try:
        result = context_for(event)
    except (OSError, ValueError, subprocess.SubprocessError):
        # Missing config, unborn/non-Git repositories, or malformed input should
        # never block a session or turn a successful tool call into a failure.
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
