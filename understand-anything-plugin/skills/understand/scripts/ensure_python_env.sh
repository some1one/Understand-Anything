#!/usr/bin/env bash
# Locate the installed plugin root and ensure the arch_analysis Python
# environment is ready. Prints PLUGIN_ROOT on stdout.
#
# The deterministic pipeline is Python (`arch_analysis`); this replaces the old
# Node/pnpm "build @understand-anything/core" step. All arch_analysis modules
# are then invoked via "$PLUGIN_ROOT/packages/arch_analysis/run.sh <module> …".
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
SKILL_DIR=$(cd "$SCRIPT_DIR/.." && pwd -P)

SKILL_REAL=$(realpath "$SKILL_DIR" 2>/dev/null || readlink -f "$SKILL_DIR" 2>/dev/null || echo "")
SELF_RELATIVE=$([ -n "$SKILL_REAL" ] && cd "$SKILL_REAL/../.." 2>/dev/null && pwd -P || echo "")
AGENTS_SKILL_REAL=$(realpath ~/.agents/skills/understand 2>/dev/null || readlink -f ~/.agents/skills/understand 2>/dev/null || echo "")
AGENTS_SELF_RELATIVE=$([ -n "$AGENTS_SKILL_REAL" ] && cd "$AGENTS_SKILL_REAL/../.." 2>/dev/null && pwd -P || echo "")
COPILOT_SKILL_REAL=$(realpath ~/.copilot/skills/understand 2>/dev/null || readlink -f ~/.copilot/skills/understand 2>/dev/null || echo "")
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
  echo "Checked:" >&2
  echo "  - ${CLAUDE_PLUGIN_ROOT:-<unset CLAUDE_PLUGIN_ROOT>}" >&2
  echo "  - $HOME/.understand-anything-plugin" >&2
  echo "  - ${SELF_RELATIVE:-<unresolved current skill path>}" >&2
  echo "  - ${AGENTS_SELF_RELATIVE:-<unresolved path derived from ~/.agents/skills/understand>}" >&2
  echo "  - ${COPILOT_SELF_RELATIVE:-<unresolved path derived from ~/.copilot/skills/understand>}" >&2
  echo "  - $HOME/.codex/understand-anything/understand-anything-plugin" >&2
  echo "  - $HOME/.opencode/understand-anything/understand-anything-plugin" >&2
  echo "  - $HOME/.pi/understand-anything/understand-anything-plugin" >&2
  echo "  - $HOME/understand-anything/understand-anything-plugin" >&2
  echo "Make sure the plugin is installed correctly." >&2
  exit 1
fi

# Warm the arch_analysis virtualenv (creates it + installs deps on first run).
if ! command -v pdm >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  echo "Install Python >= 3.14 (and ideally PDM), then re-run /understand." >&2
  exit 1
fi
"$PLUGIN_ROOT/packages/arch_analysis/run.sh" --ensure

printf '%s\n' "$PLUGIN_ROOT"
