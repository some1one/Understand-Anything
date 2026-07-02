"""Port of packages/core/src/__tests__/ignore-generator.test.ts."""

from __future__ import annotations

from understand_core.ignore_generator import generate_starter_ignore_file


def gen(tmp_path):
    return generate_starter_ignore_file(str(tmp_path))


def _uncommented(content):
    return [line for line in content.split("\n") if line.strip() and not line.startswith("#")]


def test_includes_header(tmp_path):
    content = gen(tmp_path)
    assert ".understandignore" in content
    assert "same as .gitignore" in content
    assert "Built-in defaults" in content


def test_all_suggestions_commented(tmp_path):
    (tmp_path / "__tests__").mkdir()
    (tmp_path / "docs").mkdir()
    assert _uncommented(gen(tmp_path)) == []


def test_suggests_tests_dir(tmp_path):
    (tmp_path / "__tests__").mkdir()
    assert "# __tests__/" in gen(tmp_path)


def test_suggests_docs(tmp_path):
    (tmp_path / "docs").mkdir()
    assert "# docs/" in gen(tmp_path)


def test_suggests_test_and_tests(tmp_path):
    (tmp_path / "test").mkdir()
    (tmp_path / "tests").mkdir()
    content = gen(tmp_path)
    assert "# test/" in content
    assert "# tests/" in content


def test_suggests_fixtures(tmp_path):
    (tmp_path / "fixtures").mkdir()
    assert "# fixtures/" in gen(tmp_path)


def test_suggests_examples(tmp_path):
    (tmp_path / "examples").mkdir()
    assert "# examples/" in gen(tmp_path)


def test_suggests_storybook(tmp_path):
    (tmp_path / ".storybook").mkdir()
    assert "# .storybook/" in gen(tmp_path)


def test_suggests_migrations(tmp_path):
    (tmp_path / "migrations").mkdir()
    assert "# migrations/" in gen(tmp_path)


def test_suggests_scripts(tmp_path):
    (tmp_path / "scripts").mkdir()
    assert "# scripts/" in gen(tmp_path)


def test_always_includes_generic_test_patterns(tmp_path):
    content = gen(tmp_path)
    assert "# *.snap" in content
    assert "# *.test.*" in content
    assert "# *.spec.*" in content


def test_does_not_suggest_missing_dirs(tmp_path):
    content = gen(tmp_path)
    assert "# __tests__/" not in content
    assert "# .storybook/" not in content
    assert "# fixtures/" not in content


# --- multi-language test directory detection ---


def test_suggests_pascalcase_tests(tmp_path):
    (tmp_path / "Tests").mkdir()
    assert "# Tests/" in gen(tmp_path)


def test_suggests_unittests(tmp_path):
    (tmp_path / "UnitTests").mkdir()
    assert "# UnitTests/" in gen(tmp_path)


def test_suggests_integrationtests(tmp_path):
    (tmp_path / "IntegrationTests").mkdir()
    assert "# IntegrationTests/" in gen(tmp_path)


def test_suggests_csharp_tests_suffix(tmp_path):
    (tmp_path / "MyApp.Tests").mkdir()
    assert "# MyApp.Tests/" in gen(tmp_path)


def test_suggests_csharp_unittests_suffix(tmp_path):
    (tmp_path / "MyApp.UnitTests").mkdir()
    assert "# MyApp.UnitTests/" in gen(tmp_path)


def test_suggests_csharp_integrationtests_suffix(tmp_path):
    (tmp_path / "MyApp.IntegrationTests").mkdir()
    assert "# MyApp.IntegrationTests/" in gen(tmp_path)


def test_ignores_file_sharing_detected_name(tmp_path):
    (tmp_path / "tests").write_text("not a directory")
    assert "# tests/" not in gen(tmp_path)


# --- language-grouped test file patterns ---


def test_csharp_patterns(tmp_path):
    content = gen(tmp_path)
    assert "# C# / .NET" in content
    assert "# **/*Tests.cs" in content
    assert "# **/*Test.cs" in content
    assert "# **/*Fixture.cs" in content
    assert "# **/*.Tests.csproj" in content


def test_java_kotlin_patterns(tmp_path):
    content = gen(tmp_path)
    assert "# Java / Kotlin" in content
    assert "# **/*Test.java" in content
    assert "# **/*IT.java" in content
    assert "# **/*Spec.kt" in content
    assert "# **/src/test/**" in content


def test_go_patterns(tmp_path):
    content = gen(tmp_path)
    assert "# Go" in content
    assert "# **/*_test.go" in content


def test_js_ts_subheader(tmp_path):
    assert "# JS / TS" in gen(tmp_path)


def test_language_group_order(tmp_path):
    content = gen(tmp_path)
    js_idx = content.index("# JS / TS")
    cs_idx = content.index("# C# / .NET")
    java_idx = content.index("# Java / Kotlin")
    go_idx = content.index("# Go")
    assert js_idx > -1
    assert cs_idx > js_idx
    assert java_idx > cs_idx
    assert go_idx > java_idx


def test_suggestions_commented_no_dirs(tmp_path):
    assert _uncommented(gen(tmp_path)) == []


def test_ignores_file_matching_suffix_glob(tmp_path):
    (tmp_path / "MyApp.Tests").write_text("not a directory")
    assert "# MyApp.Tests/" not in gen(tmp_path)


# --- .gitignore integration ---


def test_includes_gitignore_patterns(tmp_path):
    (tmp_path / ".gitignore").write_text(".env\nsecrets/\n*.pyc\n")
    content = gen(tmp_path)
    assert "From .gitignore" in content
    assert "# .env" in content
    assert "# secrets/" in content
    assert "# *.pyc" in content


def test_excludes_gitignore_covered_by_defaults(tmp_path):
    (tmp_path / ".gitignore").write_text("node_modules/\ndist/\n.env\n")
    content = gen(tmp_path)
    assert "# .env" in content
    section = content.split("From .gitignore")[1].split("---")[0] if "From .gitignore" in content else ""
    assert "node_modules" not in section
    assert "dist" not in section


def test_skips_gitignore_comments_and_blanks(tmp_path):
    (tmp_path / ".gitignore").write_text("# a comment\n\n.env\n  \n")
    content = gen(tmp_path)
    assert "# .env" in content
    section = content.split("From .gitignore")[1].split("---")[0] if "From .gitignore" in content else ""
    assert "a comment" not in section


def test_trailing_slash_normalization(tmp_path):
    (tmp_path / ".gitignore").write_text("dist\ncoverage\n.env\n")
    content = gen(tmp_path)
    assert "From .gitignore" in content
    lines = content.split("\n")
    header_idx = next(i for i, ln in enumerate(lines) if "From .gitignore" in ln)
    next_section = next((i for i, ln in enumerate(lines) if i > header_idx and ln.startswith("# ---")), None)
    section_lines = lines[header_idx + 1: next_section]
    patterns = [ln[2:] for ln in section_lines if ln.startswith("# ") and not ln.startswith("# ---")]
    assert ".env" in patterns
    assert "dist" not in patterns
    assert "coverage" not in patterns


def test_omits_gitignore_section_when_none(tmp_path):
    assert "From .gitignore" not in gen(tmp_path)


def test_omits_gitignore_section_when_all_covered(tmp_path):
    (tmp_path / ".gitignore").write_text("node_modules/\ndist/\n*.lock\n")
    assert "From .gitignore" not in gen(tmp_path)


def test_all_gitignore_suggestions_commented(tmp_path):
    (tmp_path / ".gitignore").write_text(".env\nsecrets/\n*.pyc\n")
    assert _uncommented(gen(tmp_path)) == []
