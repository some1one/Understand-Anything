#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: launch_dashboard.sh <project-dir>" >&2
  exit 1
fi

PROJECT_DIR=$(cd "$1" && pwd -P)
if [ ! -f "$PROJECT_DIR/.understand-anything/knowledge-graph.json" ]; then
  echo "No knowledge graph found. Run /understand first to analyze this project." >&2
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
eval "$("$SCRIPT_DIR/resolve_dashboard.sh")"

if ! command -v pnpm >/dev/null 2>&1; then
  echo "Install Node.js >= 22 and pnpm >= 10, then re-run /understand-dashboard." >&2
  exit 1
fi

(cd "$DASHBOARD_DIR" && (pnpm install --frozen-lockfile 2>/dev/null || pnpm install))
(cd "$PLUGIN_ROOT" && pnpm --filter @understand-anything/core build)

LOG_DIR="$PROJECT_DIR/.understand-anything/tmp"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/dashboard.log"

cd "$DASHBOARD_DIR"
GRAPH_DIR="$PROJECT_DIR" npx vite --host 127.0.0.1 >"$LOG_FILE" 2>&1 &
PID=$!

URL=""
for _ in $(seq 1 60); do
  URL=$(grep -Eo 'http://127\.0\.0\.1:[0-9]+\?token=[^[:space:]]+' "$LOG_FILE" | tail -1 || true)
  if [ -n "$URL" ]; then
    break
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "Dashboard server exited early. Log:" >&2
    cat "$LOG_FILE" >&2
    exit 1
  fi
  sleep 1
done

if [ -z "$URL" ]; then
  echo "Dashboard started, but no token URL was detected yet." >&2
  echo "PID: $PID" >&2
  echo "Log: $LOG_FILE" >&2
  exit 2
fi

cat <<EOF
Dashboard started at $URL
Viewing: $PROJECT_DIR/.understand-anything/knowledge-graph.json
PID: $PID
Log: $LOG_FILE
EOF
