#!/usr/bin/env bash
# Launcher for the deterministic arch_analysis pipeline.
#
# Usage:  run.sh <module> [args...]
#   e.g.  run.sh scan_project "$PROJECT_ROOT" out.json
#         run.sh analyze input.json results.json
#
# Runs `python -m arch_analysis.<module> [args...]` using the package's own
# virtualenv, with the parent `packages/` directory on PYTHONPATH so
# `import arch_analysis` resolves. It does NOT change the working directory,
# so relative path arguments resolve against the caller's cwd.
#
# On first use it creates the virtualenv and installs dependencies (PDM
# preferred; falls back to `python3 -m venv` + pip).
set -euo pipefail

ARCH_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)   # .../packages/arch_analysis
PACKAGES_DIR=$(cd "$ARCH_DIR/.." && pwd -P)                 # .../packages
VENV_PY="$ARCH_DIR/.venv/bin/python"

if [ $# -lt 1 ]; then
  echo "Usage: run.sh <arch_analysis-module> [args...]" >&2
  exit 1
fi

_install_online() {
  # PDM (dev checkout) or pip-from-index (needs network). Returns non-zero on failure.
  if command -v pdm >/dev/null 2>&1 && [ -f "$ARCH_DIR/pyproject.toml" ]; then
    ( cd "$ARCH_DIR" && pdm install >&2 ) && return 0
  fi
  command -v python3 >/dev/null 2>&1 || return 1
  python3 -m venv "$ARCH_DIR/.venv" >&2 || return 1
  "$VENV_PY" -m pip install --upgrade pip >&2 || return 1
  "$VENV_PY" -m pip install \
    "orjson>=3.11.9" "pydantic>=2.13.4" "networkx>=3.6" "numpy>=2.5.0" \
    "pandas>=3.0.3" "scipy>=1.18.0" "jsonschema>=4.26.0" "pathspec>=1.1.1" \
    "tree-sitter>=0.23.0" "tree-sitter-language-pack>=0.7.0" "pyyaml>=6.0" >&2
}

ensure_env() {
  [ -x "$VENV_PY" ] && return 0
  echo "[arch_analysis] Setting up Python environment (first run)…" >&2
  # Prefer an offline install from the bundled wheelhouse (no package index).
  # The wheelhouse is CPU/OS + Python-version specific; if it can't satisfy this
  # interpreter, fall back to an online install.
  if [ -d "$ARCH_DIR/wheelhouse" ] && ls "$ARCH_DIR/wheelhouse"/*.whl >/dev/null 2>&1 \
     && command -v python3 >/dev/null 2>&1; then
    if python3 -m venv "$ARCH_DIR/.venv" >&2 \
       && "$VENV_PY" -m pip install --upgrade pip >&2 \
       && "$VENV_PY" -m pip install --no-index --find-links "$ARCH_DIR/wheelhouse" \
            "understand-anything-arch-analysis" >&2; then
      return 0
    fi
    echo "[arch_analysis] Offline wheelhouse install did not match this environment; trying online…" >&2
    rm -rf "$ARCH_DIR/.venv"
  fi
  if ! _install_online; then
    rm -rf "$ARCH_DIR/.venv"
    echo "Error: could not set up the Python environment. Install Python >= 3.14 (and ideally PDM), then re-run." >&2
    exit 1
  fi
}

ensure_env

# `run.sh --ensure` just sets up the virtualenv and exits (used by the
# skill/hook setup phase to warm the environment once up front).
if [ "$1" = "--ensure" ]; then
  exit 0
fi

MODULE="$1"
shift
PYTHONPATH="$PACKAGES_DIR${PYTHONPATH:+:$PYTHONPATH}" exec "$VENV_PY" -m "arch_analysis.$MODULE" "$@"
