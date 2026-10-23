//! Read-only graph freshness against a bounded, project-scoped Git snapshot.
use serde_json::{Value, json};
use std::{
    collections::BTreeSet,
    io::Read,
    path::Path,
    process::{Command, Stdio},
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};
const PATHSPEC: &[&str] = &[
    "--",
    ".",
    ":(exclude).ua",
    ":(exclude).ua/**",
    ":(exclude).understand-anything",
    ":(exclude).understand-anything/**",
];
const LIMIT: u64 = 4 * 1024 * 1024;
#[derive(Debug)]
enum Failure {
    Timeout,
    Command,
    Exit(i32),
}
fn run(mut command: Command, timeout: Duration) -> Result<Vec<u8>, Failure> {
    let started = Instant::now();
    let mut child = command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| Failure::Command)?;
    let stdout = child.stdout.take().ok_or(Failure::Command)?;
    let (tx, rx) = mpsc::channel();
    thread::spawn(move || {
        let mut bytes = vec![];
        let result = stdout
            .take(LIMIT + 1)
            .read_to_end(&mut bytes)
            .map(|_| bytes);
        let _ = tx.send(result);
    });
    let status = loop {
        if started.elapsed() >= timeout {
            let _ = child.kill();
            let _ = child.wait();
            return Err(Failure::Timeout);
        }
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) => thread::sleep(Duration::from_millis(5)),
            Err(_) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(Failure::Command);
            }
        }
    };
    if !status.success() {
        return Err(Failure::Exit(status.code().unwrap_or(-1)));
    }
    let remaining = timeout.saturating_sub(started.elapsed());
    let bytes = rx
        .recv_timeout(remaining)
        .map_err(|_| Failure::Timeout)?
        .map_err(|_| Failure::Command)?;
    if bytes.len() as u64 > LIMIT {
        return Err(Failure::Command);
    }
    Ok(bytes)
}
fn git(root: &Path, args: &[&str], scoped: bool) -> Result<Vec<u8>, Failure> {
    let mut cmd = Command::new("git");
    cmd.current_dir(root)
        .args(args)
        .env("GIT_TERMINAL_PROMPT", "0")
        .env("GIT_OPTIONAL_LOCKS", "0");
    if scoped {
        cmd.args(PATHSPEC);
    }
    run(cmd, Duration::from_secs(5))
}
fn scalar(bytes: Vec<u8>) -> Result<String, Failure> {
    String::from_utf8(bytes)
        .map(|s| s.trim().to_owned())
        .map_err(|_| Failure::Command)
}
fn paths(bytes: Vec<u8>) -> Result<BTreeSet<String>, Failure> {
    Ok(String::from_utf8(bytes)
        .map_err(|_| Failure::Command)?
        .split('\0')
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .collect())
}
struct Snapshot {
    head: String,
    dirty: BTreeSet<String>,
}
fn snapshot(root: &Path) -> Result<Snapshot, Failure> {
    git(root, &["rev-parse", "--show-toplevel"], false)?;
    let head = scalar(git(
        root,
        &["rev-parse", "--verify", "HEAD^{commit}"],
        false,
    )?)?;
    let mut dirty = BTreeSet::new();
    for args in [
        vec![
            "diff",
            "--cached",
            "--no-ext-diff",
            "--no-renames",
            "--name-only",
            "-z",
            "--relative",
        ],
        vec![
            "diff",
            "--no-ext-diff",
            "--no-renames",
            "--name-only",
            "-z",
            "--relative",
        ],
        vec!["ls-files", "--others", "--exclude-standard", "-z"],
    ] {
        dirty.extend(paths(git(root, &args, true)?)?);
    }
    Ok(Snapshot { head, dirty })
}
fn ancestor(root: &Path, a: &str, b: &str) -> Result<bool, Failure> {
    match git(root, &["merge-base", "--is-ancestor", a, b], false) {
        Ok(_) => Ok(true),
        Err(Failure::Exit(1)) => Ok(false),
        Err(e) => Err(e),
    }
}
fn unknown(mut base: Value, error: &Failure, reason: &str) -> Value {
    base["status"] = json!("unknown");
    base["reason"] = json!(if matches!(error, Failure::Timeout) {
        "git-command-timeout"
    } else {
        reason
    });
    base
}
fn evaluate(root: &Path, snapshot: &Snapshot, requested: &str, mut base: Value) -> Value {
    base["headCommitHash"] = json!(snapshot.head);
    let graph = match git(
        root,
        &[
            "rev-parse",
            "--verify",
            "--end-of-options",
            &format!("{requested}^{{commit}}"),
        ],
        false,
    )
    .and_then(scalar)
    {
        Ok(graph) => graph,
        Err(e) => return unknown(base, &e, "graph-commit-unavailable"),
    };
    base["graphCommitHash"] = json!(graph);
    let committed = match git(
        root,
        &[
            "diff",
            "--no-ext-diff",
            "--no-renames",
            "--name-only",
            "-z",
            "--relative",
            &graph,
            &snapshot.head,
        ],
        true,
    )
    .and_then(paths)
    {
        Ok(files) => files,
        Err(e) => return unknown(base, &e, "graph-commit-unavailable"),
    };
    let (status, ahead, behind) = if committed.is_empty() {
        (
            if snapshot.dirty.is_empty() {
                "fresh"
            } else {
                "dirty"
            },
            0,
            0,
        )
    } else {
        let relation = (|| {
            let counts = scalar(git(
                root,
                &[
                    "rev-list",
                    "--left-right",
                    "--count",
                    &format!("{graph}...{}", snapshot.head),
                ],
                true,
            )?)?;
            let counts: Vec<u64> = counts
                .split_whitespace()
                .map(str::parse)
                .collect::<Result<_, _>>()
                .map_err(|_| Failure::Command)?;
            if counts.len() != 2 {
                return Err(Failure::Command);
            }
            let relation = if ancestor(root, &graph, &snapshot.head)? {
                "behind"
            } else if ancestor(root, &snapshot.head, &graph)? {
                "ahead"
            } else {
                "diverged"
            };
            Ok((relation, counts[0], counts[1]))
        })();
        match relation {
            Ok((relation, ahead, behind)) => {
                base["relation"] = json!(relation);
                ("stale", ahead, behind)
            }
            Err(e) => return unknown(base, &e, "graph-commit-unavailable"),
        }
    };
    let changed: BTreeSet<_> = committed.union(&snapshot.dirty).cloned().collect();
    base["status"] = json!(status);
    base["changedFileCount"] = json!(changed.len());
    base["changedFiles"] = json!(changed);
    base["commitsAhead"] = json!(ahead);
    base["commitsBehind"] = json!(behind);
    base
}
/// Each input contains graphCommitHash and optional lastAnalyzedAt. All graphs
/// share one HEAD/worktree snapshot; neither artifacts nor metadata are written.
pub fn batch(root: &Path, inputs: &Value) -> Value {
    let mut result = json!({});
    let mut snapshot_result = None;
    if let Some(inputs) = inputs.as_object() {
        for (key, input) in inputs {
            let mut base = json!({});
            if let Some(time) = input.get("lastAnalyzedAt") {
                base["lastAnalyzedAt"] = time.clone();
            }
            let requested = input["graphCommitHash"].as_str().unwrap_or("").trim();
            result[key] = if requested.is_empty() {
                unknown(base, &Failure::Command, "missing-graph-commit")
            } else {
                base["graphCommitHash"] = json!(requested);
                match snapshot_result.get_or_insert_with(|| snapshot(root)) {
                    Ok(snapshot) => evaluate(root, snapshot, requested, base),
                    Err(e) => unknown(base, e, "git-head-unavailable"),
                }
            };
        }
    }
    result
}
pub fn check(root: &Path, input: &Value) -> Value {
    batch(root, &json!({"graph":input}))["graph"].clone()
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    #[test]
    fn git_processes_have_a_wall_clock_deadline_and_output_limit() {
        let mut cmd = Command::new("sh");
        cmd.args(["-c", "exec sleep 2"]);
        let start = Instant::now();
        assert!(matches!(
            run(cmd, Duration::from_millis(40)),
            Err(Failure::Timeout)
        ));
        assert!(start.elapsed() < Duration::from_secs(1));
        let mut cmd = Command::new("python3");
        cmd.args([
            "-c",
            "import sys; sys.stdout.buffer.write(b'x' * (4 * 1024 * 1024 + 1))",
        ]);
        assert!(run(cmd, Duration::from_secs(2)).is_err());
    }
}
