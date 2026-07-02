"""Port of packages/core/src/__tests__/ignore-filter.test.ts."""

from __future__ import annotations

from understand_core.ignore_filter import DEFAULT_IGNORE_PATTERNS, create_ignore_filter


def _ua_dir(root):
    d = root / ".understand-anything"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- DEFAULT_IGNORE_PATTERNS ---


def test_defaults_contain_node_modules():
    assert "node_modules/" in DEFAULT_IGNORE_PATTERNS


def test_defaults_contain_git():
    assert ".git/" in DEFAULT_IGNORE_PATTERNS


def test_defaults_contain_obj():
    assert "obj/" in DEFAULT_IGNORE_PATTERNS


def test_defaults_do_not_contain_bin():
    assert "bin/" not in DEFAULT_IGNORE_PATTERNS


def test_defaults_contain_build_dirs():
    for d in ("dist/", "build/", "out/", "coverage/"):
        assert d in DEFAULT_IGNORE_PATTERNS


# --- createIgnoreFilter with no user file ---


def test_ignores_default_patterns(tmp_path):
    f = create_ignore_filter(str(tmp_path))
    assert f.is_ignored("node_modules/foo/bar.js")
    assert f.is_ignored("dist/index.js")
    assert f.is_ignored(".git/config")
    assert f.is_ignored("obj/Release/net8.0/app.dll")


def test_does_not_ignore_source(tmp_path):
    f = create_ignore_filter(str(tmp_path))
    assert not f.is_ignored("src/index.ts")
    assert not f.is_ignored("README.md")
    assert not f.is_ignored("package.json")


def test_ignores_lock_files(tmp_path):
    f = create_ignore_filter(str(tmp_path))
    assert f.is_ignored("pnpm-lock.yaml")
    assert f.is_ignored("package-lock.json")
    assert f.is_ignored("yarn.lock")


def test_ignores_binary_assets(tmp_path):
    f = create_ignore_filter(str(tmp_path))
    assert f.is_ignored("logo.png")
    assert f.is_ignored("font.woff2")
    assert f.is_ignored("doc.pdf")


def test_ignores_generated_files(tmp_path):
    f = create_ignore_filter(str(tmp_path))
    assert f.is_ignored("bundle.min.js")
    assert f.is_ignored("style.min.css")
    assert f.is_ignored("source.map")


def test_ignores_ide_dirs(tmp_path):
    f = create_ignore_filter(str(tmp_path))
    assert f.is_ignored(".idea/workspace.xml")
    assert f.is_ignored(".vscode/settings.json")


# --- createIgnoreFilter with user .understandignore ---


def test_reads_project_ua_ignore(tmp_path):
    (_ua_dir(tmp_path) / ".understandignore").write_text("# Exclude tests\n__tests__/\n*.test.ts\n")
    f = create_ignore_filter(str(tmp_path))
    assert f.is_ignored("__tests__/foo.test.ts")
    assert f.is_ignored("src/utils.test.ts")
    assert not f.is_ignored("src/utils.ts")


def test_reads_root_ignore(tmp_path):
    (tmp_path / ".understandignore").write_text("docs/\n")
    f = create_ignore_filter(str(tmp_path))
    assert f.is_ignored("docs/README.md")
    assert not f.is_ignored("src/index.ts")


def test_handles_comments_and_blanks(tmp_path):
    (_ua_dir(tmp_path) / ".understandignore").write_text(
        "# This is a comment\n\n\nfixtures/\n\n# Another comment\n"
    )
    f = create_ignore_filter(str(tmp_path))
    assert f.is_ignored("fixtures/data.json")
    assert not f.is_ignored("src/index.ts")


def test_supports_negation(tmp_path):
    (_ua_dir(tmp_path) / ".understandignore").write_text("!dist/\n")
    f = create_ignore_filter(str(tmp_path))
    assert not f.is_ignored("dist/index.js")


def test_supports_recursive_glob(tmp_path):
    (_ua_dir(tmp_path) / ".understandignore").write_text("**/snapshots/\n")
    f = create_ignore_filter(str(tmp_path))
    assert f.is_ignored("src/components/snapshots/Button.snap")
    assert f.is_ignored("snapshots/foo.snap")


def test_merges_both_ignore_files(tmp_path):
    (_ua_dir(tmp_path) / ".understandignore").write_text("__tests__/\n")
    (tmp_path / ".understandignore").write_text("fixtures/\n")
    f = create_ignore_filter(str(tmp_path))
    assert f.is_ignored("__tests__/foo.ts")
    assert f.is_ignored("fixtures/data.json")
    assert not f.is_ignored("src/index.ts")
