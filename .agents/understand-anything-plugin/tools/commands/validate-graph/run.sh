#!/usr/bin/env bash
# validate-graph — validate the project's saved knowledge graph and write the
# review payload to the canonical intermediate/review.json (the same file the
# /understand skill's Phase 5 produces). Deterministic, no LLM.
# Wraps: arch_analysis.validate_graph
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
UA="$PROJECT_ROOT/.understand-anything"
GRAPH="$UA/knowledge-graph.json"
REVIEW="$UA/intermediate/review.json"
SCAN="$UA/intermediate/scan-result.json"

[ -f "$GRAPH" ] || { echo "No knowledge graph at $GRAPH — run /understand first." >&2; exit 1; }
mkdir -p "$UA/intermediate"

args=("$GRAPH" "$REVIEW")
[ -f "$SCAN" ] && args+=(--scan-result "$SCAN")
exec "$ARCH" validate_graph "${args[@]}"
