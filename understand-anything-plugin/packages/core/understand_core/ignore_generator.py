"""Starter ``.understandignore`` generation — wrapper over
``understand_core.generate_ignore``.

The whole generator (header, directory detection, .gitignore merge, test-pattern
groups) is already a faithful Python port in understand_core. We re-export it under
the name the TS ``ignore-generator.ts`` exported (``generateStarterIgnoreFile``
→ ``generate_starter_ignore_file``).
"""

from __future__ import annotations

from understand_core.generate_ignore import generate_starter_ignore_file

__all__ = ["generate_starter_ignore_file"]
