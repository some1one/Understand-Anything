"""Port of ``framework-registry.ts``.

Registry providing framework detection from manifest contents and lookup by
id or language.
"""

from __future__ import annotations

from .frameworks import builtin_framework_configs
from .types import FrameworkConfig


class FrameworkRegistry:
    """Detects frameworks from manifest contents; looks up by id / language."""

    def __init__(self) -> None:
        self._by_id: dict[str, FrameworkConfig] = {}
        self._by_language: dict[str, list[FrameworkConfig]] = {}

    def register(self, config: FrameworkConfig) -> None:
        parsed = FrameworkConfig.model_validate(
            config.model_dump(by_alias=True)
        )
        # Prevent duplicate registration.
        if parsed.id in self._by_id:
            return
        self._by_id[parsed.id] = parsed
        for lang in parsed.languages:
            self._by_language.setdefault(lang, []).append(parsed)

    def get_by_id(self, framework_id: str) -> FrameworkConfig | None:
        return self._by_id.get(framework_id)

    def get_for_language(self, lang_id: str) -> list[FrameworkConfig]:
        # Return a copy so callers can't mutate the internal list.
        return list(self._by_language.get(lang_id, []))

    def get_all_frameworks(self) -> list[FrameworkConfig]:
        return list(self._by_id.values())

    def detect_frameworks(
        self, manifests: dict[str, str]
    ) -> list[FrameworkConfig]:
        """Detect frameworks from manifest file contents.

        ``manifests`` maps filename to file content (e.g.
        ``{"requirements.txt": "django==4.2\\n..."}``). Matching is by basename
        and case-insensitive keyword containment.
        """
        detected: set[str] = set()
        results: list[FrameworkConfig] = []

        for config in self._by_id.values():
            if config.id in detected:
                continue
            for manifest_file in config.manifest_files:
                content: str | None = None
                for key, value in manifests.items():
                    if key == manifest_file or key.endswith(f"/{manifest_file}"):
                        content = value
                        break
                if not content:
                    continue
                content_lower = content.lower()
                found = any(
                    keyword.lower() in content_lower
                    for keyword in config.detection_keywords
                )
                if found:
                    detected.add(config.id)
                    results.append(config)
                    break

        return results

    @staticmethod
    def create_default() -> FrameworkRegistry:
        """Create a registry pre-populated with all built-in framework configs."""
        registry = FrameworkRegistry()
        for config in builtin_framework_configs:
            registry.register(config)
        return registry
