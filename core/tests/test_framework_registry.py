"""Port of ``__tests__/framework-registry.test.ts``."""

from __future__ import annotations

from understand_core.languages.framework_registry import FrameworkRegistry
from understand_core.languages.frameworks.django import django_config
from understand_core.languages.frameworks.react import react_config


def test_registers_and_retrieves_by_id() -> None:
    registry = FrameworkRegistry()
    registry.register(django_config)
    assert registry.get_by_id("django").display_name == "Django"


def test_retrieves_frameworks_for_a_language() -> None:
    registry = FrameworkRegistry()
    registry.register(django_config)
    registry.register(react_config)
    python_frameworks = registry.get_for_language("python")
    assert len(python_frameworks) == 1
    assert python_frameworks[0].id == "django"


def test_returns_empty_for_unknown_language() -> None:
    registry = FrameworkRegistry()
    registry.register(django_config)
    assert registry.get_for_language("haskell") == []


class TestDetectFrameworks:
    def test_detects_django_from_requirements(self) -> None:
        registry = FrameworkRegistry()
        registry.register(django_config)
        detected = registry.detect_frameworks(
            {"requirements.txt": "django==4.2\ncelery==5.3\n"}
        )
        assert len(detected) == 1
        assert detected[0].id == "django"

    def test_detects_react_from_package_json(self) -> None:
        registry = FrameworkRegistry()
        registry.register(react_config)
        detected = registry.detect_frameworks(
            {
                "package.json": '{"dependencies": {"react": "^18.2.0", '
                '"react-dom": "^18.2.0"}}'
            }
        )
        assert len(detected) == 1
        assert detected[0].id == "react"

    def test_detection_is_case_insensitive(self) -> None:
        registry = FrameworkRegistry()
        registry.register(django_config)
        detected = registry.detect_frameworks({"requirements.txt": "Django==4.2\n"})
        assert len(detected) == 1

    def test_returns_empty_when_no_match(self) -> None:
        registry = FrameworkRegistry()
        registry.register(django_config)
        detected = registry.detect_frameworks({"requirements.txt": "requests==2.31\n"})
        assert detected == []

    def test_returns_empty_for_empty_manifests(self) -> None:
        registry = FrameworkRegistry()
        registry.register(django_config)
        assert registry.detect_frameworks({}) == []

    def test_does_not_duplicate_detected(self) -> None:
        registry = FrameworkRegistry()
        registry.register(django_config)
        detected = registry.detect_frameworks(
            {
                "requirements.txt": "django==4.2\ndjango==4.2\n",
                "pyproject.toml": '[project]\ndependencies = ["django>=4.0"]',
            }
        )
        assert len(detected) == 1


def test_returns_frameworks_for_all_listed_languages() -> None:
    registry = FrameworkRegistry.create_default()
    ts_frameworks = registry.get_for_language("typescript")
    js_frameworks = registry.get_for_language("javascript")
    assert any(f.id == "react" for f in ts_frameworks)
    assert any(f.id == "react" for f in js_frameworks)


def test_does_not_duplicate_on_re_registration() -> None:
    registry = FrameworkRegistry()
    registry.register(django_config)
    registry.register(django_config)
    assert len(registry.get_for_language("python")) == 1


def test_get_for_language_returns_a_copy() -> None:
    registry = FrameworkRegistry()
    registry.register(django_config)
    result = registry.get_for_language("python")
    result.append(react_config)
    assert len(registry.get_for_language("python")) == 1


class TestCreateDefault:
    def test_registers_all_builtin_framework_configs(self) -> None:
        registry = FrameworkRegistry.create_default()
        assert len(registry.get_all_frameworks()) == 10

    def test_includes_frameworks_for_multiple_languages(self) -> None:
        registry = FrameworkRegistry.create_default()
        assert len(registry.get_for_language("python")) >= 3
        assert len(registry.get_for_language("typescript")) >= 2
        assert len(registry.get_for_language("java")) >= 1
        assert len(registry.get_for_language("ruby")) >= 1
        assert len(registry.get_for_language("go")) >= 1
