"""Fast-forward the plugin's own Git checkout, never the analyzed project's repo."""
import json
import os
from pathlib import Path
import signal
import subprocess


def git(root, *args, timeout=2):
    # Kill the whole fetch process group on timeout, including credential/SSH
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


def update_plugin():
    # Cached plugins and Debian/archive payloads need not be Git checkouts. An
    # explicit source path lets a cached hook update the original plugin repo.
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
        top = git(root, "rev-parse", "--show-toplevel")
        if top.returncode or Path(top.stdout.strip()).resolve() != root:
            return None
        status = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=normal")
        if status.returncode:
            return f"{label}: update skipped because Git status could not be checked."
        if status.stdout:
            return f"{label}: update skipped because it has local changes."
        branch = git(root, "symbolic-ref", "--quiet", "HEAD")
        tracking = git(root, "rev-parse", "--verify", "@{upstream}")
        if branch.returncode or tracking.returncode:
            return f"{label}: update skipped because it needs a branch with a configured upstream."
        before = git(root, "rev-parse", "HEAD")
        if before.returncode:
            return f"{label}: update skipped because HEAD could not be checked."
        result = git(root, "pull", "--ff-only", "--no-rebase", "--no-autostash",
                     "--no-recurse-submodules", timeout=8)
        if result.returncode:
            return f"{label}: fast-forward pull failed; check upstream, divergence, and network access."
        after = git(root, "rev-parse", "HEAD")
        if after.returncode:
            return f"{label}: pull completed but its resulting revision could not be checked."
        if before.stdout != after.stdout:
            return (f"{label}: updated {before.stdout.strip()[:12]} to {after.stdout.strip()[:12]}. "
                    "Reload the host/plugin to use the updated skills and hooks.")
    except subprocess.TimeoutExpired:
        return f"{label}: update timed out; retry the pull explicitly when connectivity is available."
    except OSError:
        return f"{label}: update could not run Git."
    return None
