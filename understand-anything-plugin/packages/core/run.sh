#!/usr/bin/env bash
# Launcher for the deterministic Understand-Anything pipeline (understand_core).
#
# Usage:  run.sh <module> [args...]
#   e.g.  run.sh scan_project "$PROJECT_ROOT" out.json
#         run.sh analyze input.json results.json
#
# Runs `python -m understand_core.<module> [args...]` using the package's own
# virtualenv, with `packages/core` on PYTHONPATH so `import understand_core`
# resolves. It does NOT change the working directory, so relative path arguments
# resolve against the caller's cwd.
#
# On first use it creates the virtualenv and installs dependencies. In a
# packaged plugin this is plain `python3 -m venv` + `pip install -r
# requirements.txt` (PDM is not required at install time). In a dev checkout
# (no requirements.txt) it falls back to `pdm install`.
set -euo pipefail

CORE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)   # .../packages/core
VENV_PY="$CORE_DIR/.venv/bin/python"
REQUIREMENTS="$CORE_DIR/requirements.txt"
WHEELHOUSE="$CORE_DIR/wheelhouse"

if [ $# -lt 1 ]; then
  echo "Usage: run.sh <understand_core-module> [args...]" >&2
  exit 1
fi

_preserve_venv() {
  if [ -e "$CORE_DIR/.venv" ] || [ -L "$CORE_DIR/.venv" ]; then
    local recovery
    recovery=$(mktemp -d "$CORE_DIR/.venv-recovery.XXXXXX") || return 1
    mv "$CORE_DIR/.venv" "$recovery/venv" || return 1
    echo "[understand_core] Previous environment retained at $recovery/venv" >&2
  fi
}

_fresh_venv() {
  # Do not upgrade pip here: a bundled wheelhouse must work without network.
  command -v python3 >/dev/null 2>&1 || return 1
  _preserve_venv || return 1
  python3 -m venv "$CORE_DIR/.venv" >&2
}

_install_from_requirements() {
  # understand_core runs from source (PYTHONPATH); only its third-party deps need
  # installing. Prefer the bundled offline wheelhouse, then fall back online.
  # The wheelhouse is CPU/OS + Python-version specific, so a mismatch is normal
  # and simply triggers the online path.
  if [ -d "$WHEELHOUSE" ] && ls "$WHEELHOUSE"/*.whl >/dev/null 2>&1; then
    if _fresh_venv && "$VENV_PY" -m pip install --no-index \
         --find-links "$WHEELHOUSE" -r "$REQUIREMENTS" >&2; then
      return 0
    fi
    echo "[understand_core] Offline wheelhouse install did not match this environment; trying online…" >&2
  fi
  _fresh_venv && "$VENV_PY" -m pip install -r "$REQUIREMENTS" >&2
}

_install_dev() {
  # Dev checkout only: PDM manages the venv. Not used by the packaged plugin
  # (which ships requirements.txt and never reaches this path).
  command -v pdm >/dev/null 2>&1 && [ -f "$CORE_DIR/pyproject.toml" ] || return 1
  # Plugin caches may copy .pdm-python from another checkout and omit venv
  # symlinks. Explicitly select this new interpreter, never the saved one.
  _fresh_venv || return 1
  ( cd "$CORE_DIR" && PDM_PYTHON="$VENV_PY" PDM_IGNORE_SAVED_PYTHON=1 \
      PDM_IGNORE_ACTIVE_VENV=1 PDM_VENV_IN_PROJECT=1 \
      pdm install --frozen-lockfile --prod --no-self >&2 )
}

ensure_env() {
  [ -x "$VENV_PY" ] && return 0
  echo "[understand_core] Setting up Python environment (first run)…" >&2
  if [ -f "$REQUIREMENTS" ]; then
    _install_from_requirements && [ -x "$VENV_PY" ] && return 0
  else
    _install_dev && [ -x "$VENV_PY" ] && return 0
  fi
  _preserve_venv || true
  echo "Error: could not set up the Python environment. Install Python >= 3.14 with pip and venv (Debian: python3-venv python3-pip), then re-run." >&2
  exit 1
}

ensure_env

# `run.sh --ensure` just sets up the virtualenv and exits (used by the
# skill/hook setup phase to warm the environment once up front).
if [ "$1" = "--ensure" ]; then
  exit 0
fi

MODULE="$1"
shift
PYTHONPATH="$CORE_DIR${PYTHONPATH:+:$PYTHONPATH}" exec "$VENV_PY" -m "understand_core.$MODULE" "$@"
