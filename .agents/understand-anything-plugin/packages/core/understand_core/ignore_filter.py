"""Ignore filtering — thin wrapper over ``arch_analysis.languages``.

The full IgnoreFilter (pathspec gitwildmatch, layered defaults +
``.understandignore`` loading) already lives in arch_analysis. We re-export it
and adapt the public names the TS ``ignore-filter.ts`` exported (``IsIgnored``
method, ``createIgnoreFilter``, ``DEFAULT_IGNORE_PATTERNS``).
"""

from __future__ import annotations

from arch_analysis.languages import (
    DEFAULT_IGNORE_PATTERNS,
    IgnoreFilter,
    create_ignore_filter,
)

__all__ = ["DEFAULT_IGNORE_PATTERNS", "IgnoreFilter", "create_ignore_filter"]
