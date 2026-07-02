#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
SKILL_DIR=$(cd "$SCRIPT_DIR/.." && pwd -P)

SKILL_REAL=$(realpath "$SKILL_DIR" 2>/dev/null || readlink -f "$SKILL_DIR" 2>/dev/null || echo "")
SELF_RELATIVE=$([ -n "$SKILL_REAL" ] && cd "$SKILL_REAL/../.." 2>/dev/null && pwd -P || echo "")
AGENTS_SKILL_REAL=$(realpath ~/.agents/skills/understand-domain 2>/dev/null || readlink -f ~/.agents/skills/understand-domain 2>/dev/null || echo "")
AGENTS_SELF_RELATIVE=$([ -n "$AGENTS_SKILL_REAL" ] && cd "$AGENTS_SKILL_REAL/../.." 2>/dev/null && pwd -P || echo "")
COPILOT_SKILL_REAL=$(realpath ~/.copilot/skills/understand-domain 2>/dev/null || readlink -f ~/.copilot/skills/understand-domain 2>/dev/null || echo "")
COPILOT_SELF_RELATIVE=$([ -n "$COPILOT_SKILL_REAL" ] && cd "$COPILOT_SKILL_REAL/../.." 2>/dev/null && pwd -P || echo "")

PLUGIN_ROOT=""
for candidate in \
  "${CLAUDE_PLUGIN_ROOT:-}" \
  "$HOME/.understand-anything-plugin" \
  "$SELF_RELATIVE" \
  "$AGENTS_SELF_RELATIVE" \
  "$COPILOT_SELF_RELATIVE" \
  "$HOME/.codex/understand-anything/understand-anything-plugin" \
  "$HOME/.opencode/understand-anything/understand-anything-plugin" \
  "$HOME/.pi/understand-anything/understand-anything-plugin" \
  "$HOME/understand-anything/understand-anything-plugin"; do
  if [ -n "$candidate" ] && [ -f "$candidate/.claude-plugin/plugin.json" ] && [ -d "$candidate/packages/arch_analysis" ]; then
    PLUGIN_ROOT="$candidate"
    break
  fi
done

if [ -z "$PLUGIN_ROOT" ]; then
  echo "Error: Cannot find the understand-anything plugin root." >&2
  echo "Make sure the plugin is installed correctly." >&2
  exit 1
fi

printf '%s\n' "$PLUGIN_ROOT"
