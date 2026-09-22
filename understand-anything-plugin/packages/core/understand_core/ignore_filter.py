"""Ignore filtering — thin wrapper over ``understand_core.languages``.

The full IgnoreFilter (pathspec gitwildmatch, layered defaults +
``.understandignore`` loading) already lives in understand_core. We re-export it
and adapt the public names the TS ``ignore-filter.ts`` exported (``IsIgnored``
method, ``createIgnoreFilter``, ``DEFAULT_IGNORE_PATTERNS``).
"""

from __future__ import annotations

from understand_core.languages import (
    DEFAULT_IGNORE_PATTERNS,
    IgnoreFilter,
    create_ignore_filter,
)

__all__ = ["DEFAULT_IGNORE_PATTERNS", "IgnoreFilter", "create_ignore_filter"]
