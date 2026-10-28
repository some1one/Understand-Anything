"""Check the plugin's upstream revision without pulling or changing Git refs."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import shlex


def git(root, *args, timeout=2):
    # Kill the whole Git process group on timeout, including credential/SSH
    # children, so a hook cannot hold a session open after Git is terminated.
    process = subprocess.Popen(
        ["git", "-C", str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
        start_new_session=os.name == "posix",
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"},
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.communicate()
        raise
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def check_plugin_update():
    # One budget for all probes and the remote query, rather than a fresh timeout for
    # each command. Leave time for the host to start the session and read JSON.
    deadline = time.monotonic() + 8
    def bounded_git(root, *args, timeout=2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired('plugin update check', 8)
        return git(root, *args, timeout=min(timeout, remaining))
    # Cached plugins and Debian/archive payloads need not be Git checkouts. An
    # explicit source path lets a cached hook check the original plugin repo.
    configured = os.environ.get("UA_PLUGIN_REPO")
    root = Path(configured).expanduser().resolve() if configured else Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        return None
    manifest = root / "understand-anything-plugin/.claude-plugin/plugin.json"
    try:
        if json.loads(manifest.read_text()).get("name") != "understand-anything":
            return None
    except (OSError, ValueError, AttributeError):
        return None
    if not (root / "understand-anything-plugin/.claude-plugin/marketplace.json").is_file():
        return None
    label = f"[understand-anything] Plugin repository {root}"
    try:
        top = bounded_git(root, "rev-parse", "--show-toplevel")
        if top.returncode or Path(top.stdout.strip()).resolve() != root:
            return None
        branch = bounded_git(root, "symbolic-ref", "--quiet", "HEAD")
        if branch.returncode:
            return f"{label}: update check skipped because it needs an attached branch."
        tracking = bounded_git(root, "for-each-ref", "--format=%(upstream:remotename)%00%(upstream:remoteref)", branch.stdout.strip())
        fields = tracking.stdout.strip().split('\0')
        if tracking.returncode or len(fields) != 2 or not fields[0] or not fields[1]:
            return f"{label}: update check skipped because it needs a configured upstream."
        remote, ref = fields
        before = bounded_git(root, "rev-parse", "HEAD")
        if before.returncode:
            return f"{label}: update check skipped because HEAD could not be checked."
        # ls-remote contacts the remote without fetch, pull, ref writes, or hooks.
        result = bounded_git(root, "ls-remote", "--exit-code", "--refs", "--", remote, ref, timeout=8)
        if result.returncode:
            return f"{label}: update availability could not be checked; check upstream and network access."
        revisions = [row.split()[0] for row in result.stdout.splitlines() if len(row.split()) == 2 and row.split()[1] == ref]
        if len(revisions) != 1:
            return f"{label}: upstream revision was not found."
        latest = revisions[0]
        if latest != before.stdout.strip():
            # A locally ahead branch is already current with the remote. Unknown
            # remote objects are deliberately not fetched just to classify history.
            ancestor = bounded_git(root, "merge-base", "--is-ancestor", latest, "HEAD")
            if ancestor.returncode == 0:
                return None
            command = f"git -C {shlex.quote(str(root))} pull --ff-only --no-rebase --no-autostash --no-recurse-submodules"
            return (f"{label}: upstream has a different revision ({latest[:12]}; local {before.stdout.strip()[:12]}). "
                    "An update may be available. No checkout files or Git refs were changed. "
                    "Ask the user to confirm before updating, or give these instructions: "
                    f"from a clean checkout, run `{command}`, then run understand-setup and reload/reinstall the plugin as needed. "
                    "Do not start the update or setup automatically.")
    except subprocess.TimeoutExpired:
        return f"{label}: update check timed out; retry explicitly when connectivity is available. No update was started."
    except OSError:
        return f"{label}: update check could not run Git."
    return None
