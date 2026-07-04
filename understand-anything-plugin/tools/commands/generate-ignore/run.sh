#!/usr/bin/env bash
# generate-ignore — generate a starter .understandignore from .gitignore +
# built-in defaults. Wraps: arch_analysis.generate_ignore
#
# Usage: run.sh <project-root>
set -euo pipefail

CMD_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
PLUGIN_ROOT=$(cd "$CMD_DIR/../../.." && pwd -P)
ARCH="$PLUGIN_ROOT/packages/arch_analysis/run.sh"

if [ $# -lt 1 ]; then
  echo "Usage: $(basename "$0") <project-root>" >&2
  exit 1
fi

PROJECT_ROOT=$(cd "$1" && pwd -P)
exec "$ARCH" generate_ignore "$PROJECT_ROOT"
