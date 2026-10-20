//! Keep dictionary tests independent of downloads and machine configuration.
pub fn with_dictionaries(test: &str) -> bool {
    if std::env::var("UA_DICTIONARY_TEST_CHILD").as_deref() == Ok(test) {
        return false;
    }
    let temp = tempfile::tempdir().unwrap();
    let config = temp.path().join("dictionary-config.json");
    std::fs::write(&config, r#"{"version":1}"#).unwrap();
    let output = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact", test, "--nocapture"])
        .env("UA_DICTIONARY_TEST_CHILD", test)
        .env("UA_DICTIONARY_CONFIG", config)
        .env(
            "UA_DICTIONARY_DIR",
            concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/dictionaries"),
        )
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    true
}
