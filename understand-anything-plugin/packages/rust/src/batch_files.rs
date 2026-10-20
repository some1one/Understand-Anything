//! Serialized access to batch sets. Staging and recovery directories are never
//! discovered by mergers; failed replacements restore the previous successful set.
use crate::{Error, Result, persistence::write_json};
use serde_json::Value;
use std::{
    fs::{self, File, OpenOptions},
    path::Path,
};

pub fn lock(dir: &Path) -> Result<File> {
    fs::create_dir_all(dir)?;
    // Outside intermediate: legacy finalization cleans files in that directory.
    let file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(dir.parent().unwrap_or(dir).join(".batch-files.lock"))?;
    file.lock()?;
    Ok(file)
}

pub fn replace(dir: &Path, index: i64, fragments: &[Value]) -> Result<Vec<String>> {
    replace_with(dir, index, fragments, write_json, |from, to| {
        fs::rename(from, to)
    })
}

fn replace_with(
    dir: &Path,
    index: i64,
    fragments: &[Value],
    mut write: impl FnMut(&Path, &Value) -> Result<()>,
    mut rename: impl FnMut(&Path, &Path) -> std::io::Result<()>,
) -> Result<Vec<String>> {
    if index < 0 || fragments.is_empty() {
        return Err(Error::Invalid(
            "batch index must be nonnegative and fragments nonempty".into(),
        ));
    }
    let _lock = lock(dir)?;
    let unique = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|e| Error::Invalid(e.to_string()))?
        .as_nanos();
    let staging = dir.join(format!(
        ".batch-retry-{index}-{}-{unique}",
        std::process::id()
    ));
    fs::create_dir(&staging)?;
    let backup = staging.join("previous");
    fs::create_dir(&backup)?;
    let names: Vec<_> = (0..fragments.len())
        .map(|i| {
            if fragments.len() == 1 {
                format!("batch-{index}.json")
            } else {
                format!("batch-{index}-part-{}.json", i + 1)
            }
        })
        .collect();
    // Complete every staged write before moving any existing file.
    for (name, fragment) in names.iter().zip(fragments) {
        write(&staging.join(name), fragment)?;
    }
    let pattern = regex::Regex::new(&format!(r"^batch-{index}(?:-part-[0-9]+)?\.json$")).unwrap();
    let mut previous = vec![];
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let name = entry.file_name().to_string_lossy().into_owned();
        if pattern.is_match(&name) {
            if !entry.file_type()?.is_file() {
                return Err(Error::Invalid(format!(
                    "batch target is not a file: {name}"
                )));
            }
            previous.push(name);
        }
    }
    let mut retired = vec![];
    let mut installed = vec![];
    let result = (|| -> Result<()> {
        for name in &previous {
            rename(&dir.join(name), &backup.join(name))?;
            retired.push(name);
        }
        for name in &names {
            rename(&staging.join(name), &dir.join(name))?;
            installed.push(name);
        }
        Ok(())
    })();
    if let Err(error) = result {
        let rollback = (|| -> Result<()> {
            for name in installed.iter().rev() {
                rename(&dir.join(name), &staging.join(name))?;
            }
            for name in retired.iter().rev() {
                rename(&backup.join(name), &dir.join(name))?;
            }
            Ok(())
        })();
        if let Err(recovery) = rollback {
            return Err(Error::Invalid(format!(
                "{error}; rollback failed: {recovery}; recovery files: {}",
                staging.display()
            )));
        }
        return Err(error);
    }
    // Only our obsolete fragments and staging files are removed.
    if let Err(error) = fs::remove_dir_all(&staging) {
        eprintln!("batch replacement succeeded; staging cleanup failed: {error}");
    }
    Ok(names)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn staged_write_failure_preserves_previous_set() {
        let tmp = tempfile::tempdir().unwrap();
        let dir = tmp.path().join("intermediate");
        replace(&dir, 1, &[json!({"nodes":[1]}), json!({"nodes":[2]})]).unwrap();
        let before = fs::read(dir.join("batch-1-part-1.json")).unwrap();
        let mut calls = 0;
        let result = replace_with(
            &dir,
            1,
            &[json!({}), json!({})],
            |path, value| {
                calls += 1;
                if calls == 2 {
                    return Err(Error::Invalid("injected staged write failure".into()));
                }
                write_json(path, value)
            },
            |from, to| fs::rename(from, to),
        );
        assert!(result.is_err());
        assert_eq!(fs::read(dir.join("batch-1-part-1.json")).unwrap(), before);
        assert!(dir.join("batch-1-part-2.json").is_file());
        assert!(!dir.join("batch-1.json").exists());
    }
    #[test]
    fn replacement_errors_roll_back_every_retired_and_installed_file() {
        // Two old files and two new files: fail each rename in turn, including
        // after the first new fragment has become visible on disk.
        for failure in 1..=4 {
            let tmp = tempfile::tempdir().unwrap();
            let dir = tmp.path().join("intermediate");
            replace(&dir, 1, &[json!({"nodes":[1]}), json!({"nodes":[2]})]).unwrap();
            let before: Vec<_> = (1..=2)
                .map(|i| fs::read(dir.join(format!("batch-1-part-{i}.json"))).unwrap())
                .collect();
            let mut calls = 0;
            let result = replace_with(
                &dir,
                1,
                &[json!({"nodes":[3]}), json!({"nodes":[4]})],
                write_json,
                |from, to| {
                    calls += 1;
                    if calls == failure {
                        return Err(std::io::Error::other("injected rename failure"));
                    }
                    fs::rename(from, to)
                },
            );
            assert!(result.is_err());
            for i in 1..=2 {
                assert_eq!(
                    fs::read(dir.join(format!("batch-1-part-{i}.json"))).unwrap(),
                    before[i - 1]
                );
            }
        }
    }
    #[test]
    fn merger_waits_until_batch_replacement_releases_lock() {
        let tmp = tempfile::tempdir().unwrap();
        let dir = tmp.path().join(".understand-anything/intermediate");
        replace(&dir, 1, &[json!({"nodes":[],"edges":[]})]).unwrap();
        let held = lock(&dir).unwrap();
        let (send, recv) = std::sync::mpsc::channel();
        let root = tmp.path().to_owned();
        let worker = std::thread::spawn(move || {
            send.send(crate::batch_merge::merge_batch_directory(&root))
                .unwrap();
        });
        assert!(
            recv.recv_timeout(std::time::Duration::from_millis(100))
                .is_err()
        );
        drop(held);
        assert!(
            recv.recv_timeout(std::time::Duration::from_secs(5))
                .unwrap()
                .is_ok()
        );
        worker.join().unwrap();
    }
}
