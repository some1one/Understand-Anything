"""Pytest conftest. Re-exports the shared parser helper for convenience."""

from __future__ import annotations

from tests._ts_helper import get_parser, parse_source  # noqa: F401
