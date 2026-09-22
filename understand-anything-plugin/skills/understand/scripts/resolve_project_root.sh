#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${1:-$PWD}"
if [ ! -d "$PROJECT_ROOT" ]; then
  echo "Error: project path does not exist or is not a directory: $PROJECT_ROOT" >&2
  exit 1
fi

PROJECT_ROOT=$(cd "$PROJECT_ROOT" && pwd -P)

printf '%s\n' "$PROJECT_ROOT"
