#!/usr/bin/env bash
# Run the native analysis engine from a source checkout or packaged plugin.
set -euo pipefail

RUST_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
PACKAGED_BINARY="$RUST_DIR/bin/understand-anything-rs"
SOURCE_BINARY="$RUST_DIR/target/release/understand-anything-rs"
PARSER_ARGS=()
PARSER_CACHE="${UA_PARSER_CACHE_DIR:-}"
if [ -z "$PARSER_CACHE" ] && [ -f "$RUST_DIR/parser-cache-dir" ]; then
  IFS= read -r PARSER_CACHE < "$RUST_DIR/parser-cache-dir" || true
fi
if [ -n "$PARSER_CACHE" ]; then
  PARSER_ARGS=(--parser-cache-dir "$PARSER_CACHE")
fi
if [ -x "$PACKAGED_BINARY" ]; then
  exec "$PACKAGED_BINARY" "${PARSER_ARGS[@]}" "$@"
fi

if [ -x "$SOURCE_BINARY" ] && [ -z "$(find "$RUST_DIR/src" "$RUST_DIR/schemas" "$RUST_DIR/reference" "$RUST_DIR/Cargo.toml" "$RUST_DIR/Cargo.lock" -type f -newer "$SOURCE_BINARY" -print -quit 2>/dev/null)" ]; then
  exec "$SOURCE_BINARY" "${PARSER_ARGS[@]}" "$@"
fi

if [ ! -f "$RUST_DIR/Cargo.toml" ] || ! command -v cargo >/dev/null 2>&1; then
  echo "Understand Anything's Rust executable is missing. Install the packaged binary or build packages/rust with cargo +stable build --locked --release." >&2
  exit 1
fi

(cd "$RUST_DIR" && cargo +stable build --locked --release >&2)
exec "$RUST_DIR/target/release/understand-anything-rs" "${PARSER_ARGS[@]}" "$@"
