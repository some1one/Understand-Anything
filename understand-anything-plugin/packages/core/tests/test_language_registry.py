"""Port of ``__tests__/language-registry.test.ts``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from understand_core.languages.configs.python import python_config
from understand_core.languages.configs.typescript import typescript_config
from understand_core.languages.language_registry import LanguageRegistry
from understand_core.languages.types import StrictLanguageConfig


def test_registers_and_retrieves_by_id() -> None:
    registry = LanguageRegistry()
    registry.register(typescript_config)
    assert registry.get_by_id("typescript") == typescript_config


def test_retrieves_config_by_extension() -> None:
    registry = LanguageRegistry()
    registry.register(typescript_config)
    assert registry.get_by_extension(".ts").id == "typescript"
    assert registry.get_by_extension(".tsx").id == "typescript"


def test_retrieves_config_for_a_file_path() -> None:
    registry = LanguageRegistry()
    registry.register(typescript_config)
    registry.register(python_config)
    assert registry.get_for_file("src/index.ts").id == "typescript"
    assert registry.get_for_file("app/models.py").id == "python"


def test_returns_none_for_unknown_extensions() -> None:
    registry = LanguageRegistry()
    registry.register(typescript_config)
    assert registry.get_by_extension(".xyz") is None
    assert registry.get_for_file("file.unknown") is None


def test_returns_none_for_files_without_extension_no_filename_match() -> None:
    registry = LanguageRegistry()
    assert registry.get_for_file("SOMEFILE") is None


def test_lists_all_registered_languages() -> None:
    registry = LanguageRegistry()
    registry.register(typescript_config)
    registry.register(python_config)
    all_configs = registry.get_all_languages()
    assert len(all_configs) == 2
    ids = [c.id for c in all_configs]
    assert "typescript" in ids
    assert "python" in ids


class TestCreateDefault:
    # NOTE: the upstream TS test asserts 41 but the builtin list (and the TS
    # source's own `builtinLanguageConfigs` array) contains 39 entries, so the
    # upstream assertion is currently failing. We assert the faithful count.
    def test_registers_all_builtin_language_configs(self) -> None:
        registry = LanguageRegistry.create_default()
        assert len(registry.get_all_languages()) == 39

    def test_maps_all_expected_extensions(self) -> None:
        registry = LanguageRegistry.create_default()
        expected = {
            ".ts": "typescript",
            ".py": "python",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".rb": "ruby",
            ".php": "php",
            ".swift": "swift",
            ".kt": "kotlin",
            ".cs": "csharp",
            ".cpp": "cpp",
            ".c": "c",
            ".h": "c",
            ".lua": "lua",
            ".js": "javascript",
        }
        for ext, lang_id in expected.items():
            assert registry.get_by_extension(ext).id == lang_id

    def test_no_duplicate_extension_mappings(self) -> None:
        registry = LanguageRegistry.create_default()
        all_extensions: list[str] = []
        for config in registry.get_all_languages():
            all_extensions.extend(config.extensions)
        assert len(set(all_extensions)) == len(all_extensions)

    def test_every_config_has_at_least_one_concept(self) -> None:
        registry = LanguageRegistry.create_default()
        for config in registry.get_all_languages():
            assert len(config.concepts) > 0


class TestNonCodeLanguageConfigs:
    def test_detects_non_code_file_types_via_extension(self) -> None:
        registry = LanguageRegistry.create_default()
        expectations = [
            ("README.md", "markdown"),
            ("config.yaml", "yaml"),
            ("package.json", "json"),
            ("config.toml", "toml"),
            (".env", "env"),
            ("pom.xml", "xml"),
            ("Dockerfile", "dockerfile"),
            ("schema.sql", "sql"),
            ("schema.graphql", "graphql"),
            ("types.proto", "protobuf"),
            ("main.tf", "terraform"),
            ("Makefile", "makefile"),
            ("deploy.sh", "shell"),
            ("index.html", "html"),
            ("styles.css", "css"),
            ("data.csv", "csv"),
        ]
        for file, expected_id in expectations:
            config = registry.get_for_file(file)
            assert config is not None, f"{file} should be detected"
            assert config.id == expected_id, f"{file} should be {expected_id}"

    def test_detects_filename_based_configs(self) -> None:
        registry = LanguageRegistry.create_default()
        assert registry.get_for_file("Dockerfile").id == "dockerfile"
        assert registry.get_for_file("Makefile").id == "makefile"
        assert registry.get_for_file("Jenkinsfile").id == "jenkinsfile"
        assert registry.get_for_file("src/Dockerfile").id == "dockerfile"
        assert registry.get_for_file("build/Makefile").id == "makefile"

    def test_detects_filename_based_configs_for_docker_compose(self) -> None:
        registry = LanguageRegistry.create_default()
        assert registry.get_for_file("docker-compose.yml").id == "docker-compose"
        assert registry.get_for_file("docker-compose.yaml").id == "docker-compose"
        assert registry.get_for_file("compose.yml").id == "docker-compose"

    def test_detects_env_file_variants(self) -> None:
        registry = LanguageRegistry.create_default()
        assert registry.get_for_file(".env").id == "env"
        assert registry.get_for_file(".env.local").id == "env"
        assert registry.get_for_file(".env.production").id == "env"


class TestStrictLanguageConfigRefinement:
    def _base(self, **overrides: object) -> dict[str, object]:
        cfg: dict[str, object] = {
            "id": "empty-lang",
            "displayName": "Empty",
            "extensions": [],
            "concepts": ["nothing"],
            "filePatterns": {
                "entryPoints": [],
                "barrels": [],
                "tests": [],
                "config": [],
            },
        }
        cfg.update(overrides)
        return cfg

    def test_rejects_empty_extensions_and_no_filenames(self) -> None:
        with pytest.raises(ValidationError) as exc:
            StrictLanguageConfig.model_validate(self._base())
        assert "at least one extension or filename" in str(exc.value)

    def test_rejects_empty_extensions_and_empty_filenames(self) -> None:
        with pytest.raises(ValidationError):
            StrictLanguageConfig.model_validate(self._base(filenames=[]))

    def test_accepts_extensions_but_no_filenames(self) -> None:
        cfg = self._base(id="ext-lang", displayName="ExtLang", extensions=[".ext"])
        result = StrictLanguageConfig.model_validate(cfg)
        assert result.id == "ext-lang"

    def test_accepts_filenames_but_empty_extensions(self) -> None:
        cfg = self._base(
            id="filename-lang", displayName="FilenameLang", filenames=["Specialfile"]
        )
        result = StrictLanguageConfig.model_validate(cfg)
        assert result.id == "filename-lang"
