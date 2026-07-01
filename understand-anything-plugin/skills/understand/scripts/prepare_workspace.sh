#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: prepare_workspace.sh <project-root> [arguments...]" >&2
  exit 1
fi

PROJECT_ROOT="$1"
shift || true

mkdir -p "$PROJECT_ROOT/.understand-anything/intermediate"
mkdir -p "$PROJECT_ROOT/.understand-anything/tmp"

find "$PROJECT_ROOT/.understand-anything/" -maxdepth 1 -type d -name '.trash-*' -mtime +7 -exec rm -rf {} + 2>/dev/null || true

for arg in "$@"; do
  case "$arg" in
    --auto-update)
      printf '{"autoUpdate": true}\n' > "$PROJECT_ROOT/.understand-anything/config.json"
      ;;
    --no-auto-update)
      printf '{"autoUpdate": false}\n' > "$PROJECT_ROOT/.understand-anything/config.json"
      ;;
  esac
done
