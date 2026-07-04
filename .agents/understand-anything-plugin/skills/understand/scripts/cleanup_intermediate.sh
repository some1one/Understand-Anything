#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: cleanup_intermediate.sh <project-root>" >&2
  exit 1
fi

PROJECT_ROOT="$1"
TRASH="$PROJECT_ROOT/.understand-anything/.trash-$(date +%s)"
INTER="$PROJECT_ROOT/.understand-anything/intermediate"

mkdir -p "$TRASH"
if [ -d "$INTER" ]; then
  find "$INTER" -mindepth 1 -maxdepth 1 -not -name 'scan-result.json' -exec mv {} "$TRASH/" \; 2>/dev/null || true
fi
mv "$PROJECT_ROOT/.understand-anything/tmp" "$TRASH/" 2>/dev/null || true
