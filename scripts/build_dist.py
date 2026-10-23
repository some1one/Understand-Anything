#!/usr/bin/env python3
"""Build a plugin payload with the native Rust engine and dashboard bundle."""

from __future__ import annotations

import argparse
import json
import platform as _platform
import shutil
import subprocess
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "understand-anything-plugin"
PKGS = PLUGIN / "packages"
BUILD = REPO / "build"
DIST = REPO / "dist"
DEB_SRC = REPO / "packaging" / "deb"

IGNORE = shutil.ignore_patterns(
    "__pycache__", ".pytest_cache", "node_modules", "dist",
    "build_test_dist", "*.pyc", ".DS_Store", "*.tsbuildinfo",
)

MAINTAINER = "Justin Phillips <justin.phillips@trucesoftware.com>"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("  $", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def read_version() -> str:
    return json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["version"]


def platform_tag() -> str:
    sysname = {"linux": "linux", "darwin": "macos", "windows": "win"}.get(
        _platform.system().lower(), _platform.system().lower())
    mach = _platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(mach, mach)
    return f"{sysname}_{arch}"


def deb_arch() -> str:
    return {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
        _platform.machine().lower(), _platform.machine().lower())


# --------------------------------------------------------------------------- #
# Native engine
# --------------------------------------------------------------------------- #

def build_rust() -> Path:
    rust = PKGS / "rust"
    run(["cargo", "+stable", "build", "--locked", "--release"], cwd=rust)
    binary = rust / "target/release/understand-anything-rs"
    if not binary.is_file():
        raise FileNotFoundError(binary)
    return binary


def build_dashboard() -> None:
    print("• Building static dashboard bundle…")
    dash = PKGS / "dashboard"
    pnpm = shutil.which("pnpm") or _die("pnpm not found — needed to build the dashboard.")
    run([pnpm, "install", "--frozen-lockfile"], cwd=dash)
    run([pnpm, "build"], cwd=dash)


def _die(msg: str):
    raise SystemExit(msg)


# --------------------------------------------------------------------------- #
# Payload (copied/source artifacts only)
# --------------------------------------------------------------------------- #

def assemble_payload(payload: Path, binary: Path) -> None:
    print("• Assembling native plugin payload…")
    if payload.exists():
        shutil.rmtree(payload)
    payload.mkdir(parents=True)
    for d in (".claude-plugin", ".codex-plugin", "agents", "hooks", "skills", "tools", "scripts"):
        shutil.copytree(PLUGIN / d, payload / d, ignore=IGNORE)
    for name in ("README.md", "HOSTS.md", "AGENTS.md"):
        shutil.copy2(PLUGIN / name, payload / name)
    pkgs = payload / "packages"
    rust = pkgs / "rust"
    (rust / "bin").mkdir(parents=True)
    shutil.copy2(PKGS / "rust/run.sh", rust / "run.sh")
    shutil.copy2(binary, rust / "bin/understand-anything-rs")
    shutil.copytree(PKGS / "rust/schemas", rust / "schemas")
    shutil.copy2(PKGS / "rust/README.md", rust / "README.md")
    dash = pkgs / "dashboard"
    dash.mkdir()
    for name in ("serve.mjs", "freshness-server.mjs", "package.json"):
        shutil.copy2(PKGS / "dashboard" / name, dash / name)


def agents_md() -> str:
    return (PLUGIN / "AGENTS.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Archives
# --------------------------------------------------------------------------- #

def tar_dir(src: Path, arcname: str, out: Path) -> Path:
    with tarfile.open(out, "w:gz") as tar:
        tar.add(src, arcname=arcname, recursive=True)
    return out


def make_archives(payload: Path, version: str, do_dashboard: bool) -> list[Path]:
    made = [tar_dir(payload, "understand-anything-plugin",
                    DIST / f"understand-anything-plugin-{platform_tag()}-{version}.tar.gz")]
    built = PKGS / "dashboard" / "dist"
    if do_dashboard and built.exists():
        made.append(tar_dir(built, "dist",
                            DIST / f"understand-anything-dashboard-{version}.tar.gz"))
    return made


# --------------------------------------------------------------------------- #
# Debian package
# --------------------------------------------------------------------------- #

def build_deb(version: str, archives: list[Path]) -> Path:
    print("• Building Debian package…")
    if not shutil.which("dpkg-deb"):
        raise SystemExit("dpkg-deb not found — cannot build the .deb.")
    arch = deb_arch()
    stage = BUILD / f"deb/understand-anything_{version}_{arch}"
    if stage.exists():
        shutil.rmtree(stage)
    share = stage / "usr/share/understand-anything"
    debian = stage / "DEBIAN"
    (stage / "usr/bin").mkdir(parents=True)
    share.mkdir(parents=True)
    debian.mkdir(parents=True)

    # Ship the archives + the per-user linker; postinst assembles them.
    for a in archives:
        shutil.copy2(a, share / a.name)
    shutil.copy2(DEB_SRC / "understand-anything", stage / "usr/bin/understand-anything")
    (stage / "usr/bin/understand-anything").chmod(0o755)

    # The per-user linker generates host-specific local catalogs at install time.

    (debian / "control").write_text(
        f"""Package: understand-anything
Version: {version}
Section: devel
Priority: optional
Architecture: {arch}
Depends: python3
Recommends: nodejs (>= 22)
Maintainer: {MAINTAINER}
Description: AI-powered codebase understanding — analyze, visualize, explain any project.
 Ships the Understand-Anything plugin (skills, agents, hooks), the deterministic
 Rust analysis engine, and a pre-built dashboard.
 After install, run `understand-anything <platform>` to enable it for your user.
""")

    (debian / "postinst").write_text(
        """#!/bin/sh
set -e
SHARE=/usr/share/understand-anything
PLUGIN="$SHARE/understand-anything-plugin"
rm -rf "$PLUGIN"
tar -xzf "$SHARE"/understand-anything-plugin-*.tar.gz -C "$SHARE"
if ls "$SHARE"/understand-anything-dashboard-*.tar.gz >/dev/null 2>&1; then
  tar -xzf "$SHARE"/understand-anything-dashboard-*.tar.gz -C "$PLUGIN/packages/dashboard"
fi
echo "Understand-Anything installed. Enable it for your user with:"
echo "    understand-anything <platform>              (claude | codex | opencode | agents | vscode | jetbrains | kilo | kiro)"
echo "    understand-anything cursor --local <dir>    (cursor is project-only)"
echo "    understand-anything <platform> --local <dir>"
exit 0
""")

    (debian / "postrm").write_text(
        """#!/bin/sh
set -e
case "$1" in
  remove|purge)
    rm -rf /usr/share/understand-anything/understand-anything-plugin
    ;;
esac
exit 0
""")
    for f in ("postinst", "postrm"):
        (debian / f).chmod(0o755)

    out = DIST / f"understand-anything_{version}_{arch}.deb"
    run(["dpkg-deb", "--root-owner-group", "--build", str(stage), str(out)])
    return out


# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-dashboard", action="store_true")
    ap.add_argument("--deb", action="store_true", help="also build the Debian package")
    ap.add_argument("--clean", action="store_true")
    args = ap.parse_args()

    version = read_version()
    if args.clean:
        shutil.rmtree(BUILD, ignore_errors=True)
        shutil.rmtree(DIST, ignore_errors=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)

    binary = build_rust()
    if not args.skip_dashboard:
        build_dashboard()

    payload = BUILD / "payload"
    assemble_payload(payload, binary)
    archives = make_archives(payload, version, do_dashboard=not args.skip_dashboard)
    deb = build_deb(version, archives) if args.deb else None

    print("\n✓ dist/ artifacts:")
    for f in archives + ([deb] if deb else []):
        print(f"   {f.name}  ({f.stat().st_size / (1024*1024):.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
