//! Starter ignore-file suggestions. Existing files are never overwritten by the CLI.
use std::{fs, path::Path};
pub fn generate_starter_ignore_file(root: &Path) -> String {
    let header = "# .understandignore — patterns for files/dirs to exclude from analysis\n# Syntax: same as .gitignore (globs, # comments, ! negation, trailing / for dirs)\n# Lines below are suggestions — uncomment to activate.\n# Use ! prefix to force-include something excluded by defaults.\n#\n# Built-in defaults (always excluded unless negated):\n#   node_modules/, .git/, dist/, build/, obj/, *.lock, *.min.js, etc.\n#\n";
    let mut out = vec![header.to_owned()];
    let defaults = crate::scan::default_patterns();
    let gitignore = fs::read_to_string(root.join(".gitignore")).unwrap_or_default();
    let patterns: Vec<_> = gitignore
        .lines()
        .map(str::trim)
        .filter(|s| {
            !s.is_empty()
                && !s.starts_with('#')
                && !defaults
                    .iter()
                    .any(|d| d.trim_end_matches('/') == s.trim_end_matches('/'))
        })
        .collect();
    if !patterns.is_empty() {
        out.push("# --- From .gitignore (uncomment to exclude) ---\n".into());
        out.extend(patterns.iter().map(|p| format!("# {p}")));
        out.push(String::new());
    }
    let mut detected = vec![];
    if let Ok(entries) = fs::read_dir(root) {
        for entry in entries.flatten() {
            if !entry.path().is_dir() {
                continue;
            }
            let name = entry.file_name().to_string_lossy().into_owned();
            let low = name.to_lowercase();
            if [
                "__tests__",
                "test",
                "tests",
                "fixtures",
                "testdata",
                "docs",
                "examples",
                "scripts",
                "migrations",
                ".storybook",
                "unittests",
                "integrationtests",
            ]
            .contains(&low.as_str())
                || [".tests", ".unittests", ".integrationtests"]
                    .iter()
                    .any(|s| low.ends_with(s))
            {
                detected.push(format!("{name}/"));
            }
        }
    }
    detected.sort();
    if !detected.is_empty() {
        out.push("# --- Detected directories (uncomment to exclude) ---\n".into());
        out.extend(detected.iter().map(|p| format!("# {p}")));
        out.push(String::new());
    }
    out.push("# --- Test file patterns (uncomment to exclude) ---\n".into());
    for (label, patterns) in [
        ("JS / TS", vec!["*.test.*", "*.spec.*", "*.snap"]),
        (
            "C# / .NET",
            vec![
                "**/*Tests.cs",
                "**/*Test.cs",
                "**/*Fixture.cs",
                "**/*.Tests.csproj",
            ],
        ),
        (
            "Java / Kotlin",
            vec![
                "**/src/test/**",
                "**/*Test.java",
                "**/*IT.java",
                "**/*Spec.kt",
            ],
        ),
        ("Go", vec!["**/*_test.go"]),
    ] {
        out.push(format!("# {label}"));
        out.extend(patterns.iter().map(|p| format!("# {p}")));
    }
    out.push(String::new());
    out.join("\n")
}
