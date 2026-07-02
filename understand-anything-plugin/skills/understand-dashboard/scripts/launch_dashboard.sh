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

LOG_DIR="$PROJECT_DIR/.understand-anything/tmp"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/dashboard.log"

if ! command -v node >/dev/null 2>&1; then
  echo "Install Node.js >= 22, then re-run /understand-dashboard." >&2
  exit 1
fi

cd "$DASHBOARD_DIR"

if [ -f "$DASHBOARD_DIR/serve.mjs" ] && [ -f "$DASHBOARD_DIR/dist/index.html" ]; then
  # Bundled / pre-built dashboard: serve the static build with the zero-dependency
  # Node server (no install step, no pnpm required).
  GRAPH_DIR="$PROJECT_DIR" node serve.mjs >"$LOG_FILE" 2>&1 &
  PID=$!
else
  # Source checkout: run the Vite dev server (needs pnpm + a one-time install).
  if ! command -v pnpm >/dev/null 2>&1; then
    echo "Install Node.js >= 22 and pnpm >= 10 (or build the dashboard: make build-dashboard), then re-run /understand-dashboard." >&2
    exit 1
  fi
  (pnpm install --frozen-lockfile 2>/dev/null || pnpm install)
  GRAPH_DIR="$PROJECT_DIR" npx vite --host 127.0.0.1 >"$LOG_FILE" 2>&1 &
  PID=$!
fi

URL=""
for _ in $(seq 1 60); do
  URL=$(grep -Eo 'http://127\.0\.0\.1:[0-9]+/?\?token=[^[:space:]]+' "$LOG_FILE" | tail -1 || true)
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
