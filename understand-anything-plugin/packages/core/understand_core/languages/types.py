"""Pydantic models for language and framework configuration.

Port of ``languages/types.ts`` (zod schemas). The JSON wire format uses
camelCase keys (``displayName``, ``treeSitter``, ``filePatterns``,
``detectionKeywords`` ...); models expose camelCase aliases and accept either
the alias or the snake_case attribute name via ``populate_by_name=True``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TreeSitterConfig(BaseModel):
    """Tree-sitter grammar configuration for a language.

    Only ``wasmPackage`` and ``wasmFile`` are needed for grammar loading.
    """

    model_config = ConfigDict(populate_by_name=True)

    wasm_package: str = Field(alias="wasmPackage")
    wasm_file: str = Field(alias="wasmFile")


class FilePatternConfig(BaseModel):
    """File-pattern conventions for a language."""

    model_config = ConfigDict(populate_by_name=True)

    entry_points: list[str] = Field(alias="entryPoints")
    barrels: list[str]
    tests: list[str]
    config: list[str]


class LanguageConfig(BaseModel):
    """Complete language configuration.

    Base model used by ``LanguageRegistry.register()``. Mirrors the base zod
    schema (no detection refinement). ``id`` and ``display_name`` must be
    non-empty.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(min_length=1)
    display_name: str = Field(alias="displayName", min_length=1)
    extensions: list[str]
    filenames: list[str] | None = None
    tree_sitter: TreeSitterConfig | None = Field(default=None, alias="treeSitter")
    concepts: list[str]
    file_patterns: FilePatternConfig = Field(alias="filePatterns")


class StrictLanguageConfig(LanguageConfig):
    """Strict variant: at least one extension or filename for detectability.

    Use for validating new / user-supplied configs. Some builtin configs
    (kubernetes, github-actions, json-schema) intentionally lack both and rely
    on future content-based detection, so they use the base ``LanguageConfig``.
    """

    @model_validator(mode="after")
    def _require_detection_key(self) -> StrictLanguageConfig:
        has_ext = len(self.extensions) > 0
        has_filename = self.filenames is not None and len(self.filenames) > 0
        if not (has_ext or has_filename):
            raise ValueError(
                "LanguageConfig must have at least one extension or filename "
                "for detection"
            )
        return self


class FrameworkConfig(BaseModel):
    """Framework configuration."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(min_length=1)
    display_name: str = Field(alias="displayName", min_length=1)
    languages: list[str] = Field(min_length=1)
    detection_keywords: list[str] = Field(alias="detectionKeywords", min_length=1)
    manifest_files: list[str] = Field(alias="manifestFiles", min_length=1)
    prompt_snippet_path: str = Field(alias="promptSnippetPath", min_length=1)
    entry_points: list[str] | None = Field(default=None, alias="entryPoints")
    layer_hints: dict[str, str] | None = Field(default=None, alias="layerHints")

    @model_validator(mode="after")
    def _validate_languages_nonempty(self) -> FrameworkConfig:
        if any(len(lang) < 1 for lang in self.languages):
            raise ValueError("framework languages must be non-empty strings")
        return self
