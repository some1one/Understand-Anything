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
# On first use it creates the virtualenv and installs dependencies. In a
# packaged plugin this is plain `python3 -m venv` + `pip install -r
# requirements.txt` (PDM is not required at install time). In a dev checkout
# (no requirements.txt) it falls back to `pdm install`.
set -euo pipefail

ARCH_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)   # .../packages/arch_analysis
PACKAGES_DIR=$(cd "$ARCH_DIR/.." && pwd -P)                 # .../packages
VENV_PY="$ARCH_DIR/.venv/bin/python"
REQUIREMENTS="$ARCH_DIR/requirements.txt"
WHEELHOUSE="$ARCH_DIR/wheelhouse"

if [ $# -lt 1 ]; then
  echo "Usage: run.sh <arch_analysis-module> [args...]" >&2
  exit 1
fi

_fresh_venv() {
  # (Re)create a clean venv with an up-to-date pip. Returns non-zero on failure.
  command -v python3 >/dev/null 2>&1 || return 1
  rm -rf "$ARCH_DIR/.venv"
  python3 -m venv "$ARCH_DIR/.venv" >&2 || return 1
  "$VENV_PY" -m pip install --upgrade pip >&2
}

_install_from_requirements() {
  # arch_analysis runs from source (PYTHONPATH); only its third-party deps need
  # installing. Prefer the bundled offline wheelhouse, then fall back online.
  # The wheelhouse is CPU/OS + Python-version specific, so a mismatch is normal
  # and simply triggers the online path.
  if [ -d "$WHEELHOUSE" ] && ls "$WHEELHOUSE"/*.whl >/dev/null 2>&1; then
    if _fresh_venv && "$VENV_PY" -m pip install --no-index \
         --find-links "$WHEELHOUSE" -r "$REQUIREMENTS" >&2; then
      return 0
    fi
    echo "[arch_analysis] Offline wheelhouse install did not match this environment; trying online…" >&2
  fi
  _fresh_venv && "$VENV_PY" -m pip install -r "$REQUIREMENTS" >&2
}

_install_dev() {
  # Dev checkout only: PDM manages the venv. Not used by the packaged plugin
  # (which ships requirements.txt and never reaches this path).
  command -v pdm >/dev/null 2>&1 && [ -f "$ARCH_DIR/pyproject.toml" ] || return 1
  ( cd "$ARCH_DIR" && pdm install >&2 )
}

ensure_env() {
  [ -x "$VENV_PY" ] && return 0
  echo "[arch_analysis] Setting up Python environment (first run)…" >&2
  if [ -f "$REQUIREMENTS" ]; then
    _install_from_requirements && return 0
  else
    _install_dev && return 0
  fi
  rm -rf "$ARCH_DIR/.venv"
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
PYTHONPATH="$PACKAGES_DIR${PYTHONPATH:+:$PYTHONPATH}" exec "$VENV_PY" -m "arch_analysis.$MODULE" "$@"
