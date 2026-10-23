use std::fs;
use understand_anything::{ignore_generator, scan::IgnoreFilter};

#[test]
fn suggestions_cover_language_conventions_without_activating_exclusions() {
    let tmp = tempfile::tempdir().unwrap();
    for dir in ["benchmarks", "benches", "spec", "MyAppTests", "Contests"] {
        fs::create_dir(tmp.path().join(dir)).unwrap();
    }
    let starter = ignore_generator::generate_starter_ignore_file(tmp.path());
    assert!(
        starter
            .lines()
            .all(|line| line.is_empty() || line.starts_with('#'))
    );
    for pattern in [
        "**/*_test.cpp",
        "**/conftest.py",
        "**/tests.rs",
        "**/*_spec.rb",
        "benchmarks/",
        "benches/",
        "spec/",
        "MyAppTests/",
        "Contests/",
    ] {
        assert!(
            starter.lines().any(|line| line == format!("# {pattern}")),
            "{pattern}"
        );
    }
    // Swift suggestions must not swallow production filenames that end in test/spec.
    let swift = starter.split("# Swift\n").nth(1).unwrap();
    let patterns: Vec<_> = swift
        .lines()
        .filter_map(|line| line.strip_prefix("# "))
        .map(str::to_owned)
        .collect();
    let filter = IgnoreFilter::new(&patterns).unwrap();
    for path in [
        "Sources/Contest.swift",
        "Sources/Contests.swift",
        "Sources/Inspec.swift",
        "Contests/App.swift",
    ] {
        assert!(!filter.is_ignored(path), "{path}");
    }
    for path in [
        "Tests/AppTests.swift",
        "Modules/Feature/Tests/App.swift",
        "Specs/AppSpec.swift",
    ] {
        assert!(filter.is_ignored(path), "{path}");
    }
}
