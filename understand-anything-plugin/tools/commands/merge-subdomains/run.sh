#!/usr/bin/env bash
# merge-subdomains — merge *-knowledge-graph.json fragments into a single
# knowledge-graph.json. Wraps: understand-anything-rs merge_subdomain_graphs
#
# Usage: run.sh <project-root> [fragment.json ...]
#   With no fragment args, auto-discovers *knowledge-graph*.json in
#   <project-root>/.understand-anything/ (excluding knowledge-graph.json).
set -euo pipefail

CMD_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
PLUGIN_ROOT=$(cd "$CMD_DIR/../../.." && pwd -P)
ARCH="$PLUGIN_ROOT/packages/rust/run.sh"

if [ $# -lt 1 ]; then
  echo "Usage: $(basename "$0") <project-root> [fragment.json ...]" >&2
  exit 1
fi

PROJECT_ROOT=$(cd "$1" && pwd -P)
shift
exec "$ARCH" merge_subdomain_graphs "$PROJECT_ROOT" "$@"
