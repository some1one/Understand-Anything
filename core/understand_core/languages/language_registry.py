"""Port of ``language-registry.ts``.

Registry mapping language ids and file extensions to ``LanguageConfig`` objects.
"""

from __future__ import annotations

from .configs import builtin_language_configs
from .types import LanguageConfig


class LanguageRegistry:
    """Maps language ids, extensions, and filenames to ``LanguageConfig``."""

    def __init__(self) -> None:
        self._by_id: dict[str, LanguageConfig] = {}
        self._by_extension: dict[str, LanguageConfig] = {}
        self._by_filename: dict[str, LanguageConfig] = {}

    def register(self, config: LanguageConfig) -> None:
        # Re-validate (mirror zod ``.parse()`` on register).
        parsed = LanguageConfig.model_validate(
            config.model_dump(by_alias=True)
        )
        self._by_id[parsed.id] = parsed
        for ext in parsed.extensions:
            # Normalize: ensure a leading dot for lookup consistency.
            key = ext if ext.startswith(".") else f".{ext}"
            self._by_extension[key] = parsed
        if parsed.filenames:
            for filename in parsed.filenames:
                self._by_filename[filename.lower()] = parsed

    def get_by_id(self, lang_id: str) -> LanguageConfig | None:
        return self._by_id.get(lang_id)

    def get_by_extension(self, ext: str) -> LanguageConfig | None:
        key = (ext if ext.startswith(".") else f".{ext}").lower()
        return self._by_extension.get(key)

    def get_for_file(self, file_path: str) -> LanguageConfig | None:
        # Filename-based lookup first (more specific: docker-compose.yml, etc.).
        basename = file_path.split("/")[-1] if "/" in file_path else file_path
        filename_match = self._by_filename.get(basename.lower())
        if filename_match is not None:
            return filename_match
        # Fall back to extension-based lookup.
        last_dot = file_path.rfind(".")
        if last_dot == -1:
            return None
        ext = file_path[last_dot:].lower()
        return self.get_by_extension(ext)

    def get_all_languages(self) -> list[LanguageConfig]:
        return list(self._by_id.values())

    @staticmethod
    def create_default() -> LanguageRegistry:
        """Create a registry pre-populated with all built-in language configs."""
        registry = LanguageRegistry()
        for config in builtin_language_configs:
            registry.register(config)
        return registry
