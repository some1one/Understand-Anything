"""Language & framework configuration registries (port of ``languages/index.ts``).

Re-exports the registries, the pydantic schemas / types, and the built-in
config lists.
"""

from __future__ import annotations

from .configs import builtin_language_configs
from .framework_registry import FrameworkRegistry
from .frameworks import builtin_framework_configs
from .language_registry import LanguageRegistry
from .types import (
    FilePatternConfig,
    FrameworkConfig,
    LanguageConfig,
    StrictLanguageConfig,
    TreeSitterConfig,
)

__all__ = [
    # Types / schemas
    "LanguageConfig",
    "StrictLanguageConfig",
    "TreeSitterConfig",
    "FilePatternConfig",
    "FrameworkConfig",
    # Registries
    "LanguageRegistry",
    "FrameworkRegistry",
    # Built-in configs
    "builtin_language_configs",
    "builtin_framework_configs",
]
