#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: cleanup_intermediate.sh <project-root>" >&2
  exit 1
fi

PROJECT_ROOT="$1"
DATA_SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
UA_DIR=$(python3 "$DATA_SCRIPT_DIR/../../../scripts/data_directory.py" "$PROJECT_ROOT")

TRASH="$UA_DIR/.trash-$(date +%s)"
INTER="$UA_DIR/intermediate"

mkdir -p "$TRASH"
if [ -d "$INTER" ]; then
  find "$INTER" -mindepth 1 -maxdepth 1 -not -name 'scan-result.json' -not -name 'save-summary.json' -exec mv {} "$TRASH/" \; 2>/dev/null || true
fi
mv "$UA_DIR/tmp" "$TRASH/" 2>/dev/null || true
