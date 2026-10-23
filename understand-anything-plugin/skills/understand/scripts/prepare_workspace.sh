#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: prepare_workspace.sh <project-root> [arguments...]" >&2
  exit 1
fi

PROJECT_ROOT="$1"
shift || true
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)

DATA_SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
UA_DIR=$(python3 "$DATA_SCRIPT_DIR/../../../scripts/data_directory.py" "$PROJECT_ROOT")

mkdir -p "$UA_DIR/intermediate"
mkdir -p "$UA_DIR/tmp"

for arg in "$@"; do
  case "$arg" in
    --auto-update)
      python3 "$SCRIPT_DIR/set_auto_update.py" "$PROJECT_ROOT" true
      ;;
    --no-auto-update)
      python3 "$SCRIPT_DIR/set_auto_update.py" "$PROJECT_ROOT" false
      ;;
  esac
done
