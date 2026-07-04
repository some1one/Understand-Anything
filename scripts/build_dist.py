#!/usr/bin/env python3
"""Build distributable artifacts for Understand-Anything.

Layout of ``dist/``:

* ``python/`` — wheels + sdists for ``arch_analysis`` and ``core``.
* ``understand-anything-plugin-<ver>.tar.gz`` — the SINGLE archive of copied /
  source artifacts (the plugin payload: skills, agents, hooks, .claude-plugin,
  Python source + run.sh, dashboard serve.mjs). Platform-agnostic, no build output.
* Build-specific archives (extracted *onto* the payload by the installer):
  * ``understand-anything-wheelhouse-<plat>-<ver>.tar.gz`` — offline Python wheels
    (CPU/OS + Python-version specific; e.g. linux_x64).
  * ``understand-anything-dashboard-<ver>.tar.gz`` — pre-built static dashboard.
* ``understand-anything_<ver>_<arch>.deb`` — Debian package bundling the archives
  + a per-user linker (``--deb``).

Symlinks / moves / renames / per-platform layout are performed by the install
scripts (repo ``install.sh`` / the deb's ``/usr/bin/understand-anything``), never
baked into these archives.

Usage:
    python scripts/build_dist.py [--skip-python|--skip-wheelhouse|--skip-dashboard]
                                 [--python-only] [--deb] [--clean]
"""

from __future__ import annotations

import argparse
import json
import platform as _platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "understand-anything-plugin"
PKGS = PLUGIN / "packages"
BUILD = REPO / "build"
DIST = REPO / "dist"
DEB_SRC = REPO / "packaging" / "deb"

IGNORE = shutil.ignore_patterns(
    ".venv", "__pycache__", ".pytest_cache", "node_modules", "dist",
    "build_test_dist", "*.pyc", ".DS_Store", "*.tsbuildinfo", "wheelhouse",
)

MAINTAINER = "Justin Phillips <justin.phillips@trucesoftware.com>"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("  $", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def read_version() -> str:
    return json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["version"]


def find_python() -> str:
    for c in (PKGS / "arch_analysis" / ".venv" / "bin" / "python",
              PKGS / "core" / ".venv" / "bin" / "python"):
        if c.exists():
            return str(c)
    return shutil.which("python3") or sys.executable


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
# Python wheels + wheelhouse
# --------------------------------------------------------------------------- #

def build_python(out: Path) -> None:
    print("• Building Python wheels (arch_analysis, core)…")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    # core builds in place; --no-clean so the arch build (next) doesn't wipe it.
    run(["pdm", "build", "--no-clean", "--project", str(PKGS / "core"), "--dest", str(out)])
    # arch_analysis is flat — stage a normalized tree nested under arch_analysis/.
    stage = BUILD / "arch_build"
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "arch_analysis").mkdir(parents=True)
    src = PKGS / "arch_analysis"
    skip = {"tests", ".venv", "__pycache__", ".pytest_cache", "build_test_dist",
            "run.sh", "pyproject.toml", "pdm.lock", "pdm.toml", ".python-version",
            "README.md", "wheelhouse"}
    for item in src.iterdir():
        if item.name in skip:
            continue
        dest = stage / "arch_analysis" / item.name
        shutil.copytree(item, dest, ignore=IGNORE) if item.is_dir() else shutil.copy2(item, dest)
    shutil.copy2(src / "pyproject.toml", stage / "pyproject.toml")
    run(["pdm", "build", "--no-clean", "--project", str(stage), "--dest", str(out)])


def build_wheelhouse(pywheels: Path, wheelhouse: Path, requirements: Path) -> None:
    print("• Collecting offline wheelhouse (arch_analysis + core + all deps)…")
    if wheelhouse.exists():
        shutil.rmtree(wheelhouse)
    wheelhouse.mkdir(parents=True)
    # Pin from requirements.txt so the wheelhouse holds exactly the lock-pinned
    # versions run.sh's `pip install --no-index -r requirements.txt` will ask for.
    run([find_python(), "-m", "pip", "wheel", "--find-links", str(pywheels),
         "-r", str(requirements),
         "understand-anything-arch-analysis", "understand-anything-core",
         "-w", str(wheelhouse)])


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

def export_requirements(out: Path) -> Path:
    """Export arch_analysis's locked prod deps to a PDM-free requirements.txt.

    The wheelhouse is built from this file and it is shipped in the payload, so
    both agree on exact (lock-pinned) versions and the target's offline
    ``pip install --no-index -r requirements.txt`` always resolves.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["pdm", "export", "--project", str(PKGS / "arch_analysis"),
         "-f", "requirements", "--without-hashes", "--prod", "-o", str(out)])
    return out


def assemble_payload(payload: Path, requirements: Path) -> None:
    print("• Assembling copied/source payload…")
    if payload.exists():
        shutil.rmtree(payload)
    payload.mkdir(parents=True)
    shutil.copytree(PLUGIN / ".claude-plugin", payload / ".claude-plugin")
    for d in ("agents", "hooks", "skills", "tools"):
        shutil.copytree(PLUGIN / d, payload / d, ignore=IGNORE)
    if (PLUGIN / "README.md").exists():
        shutil.copy2(PLUGIN / "README.md", payload / "README.md")
    (payload / "AGENTS.md").write_text(agents_md())

    pkgs = payload / "packages"
    pkgs.mkdir()
    # arch_analysis: source + run.sh + pyproject (wheelhouse is a separate archive).
    arch = pkgs / "arch_analysis"
    shutil.copytree(PKGS / "arch_analysis", arch, ignore=IGNORE)
    for junk in ("pdm.lock", "pdm.toml", ".python-version"):
        (arch / junk).unlink(missing_ok=True)
    shutil.rmtree(arch / "tests", ignore_errors=True)
    # Ship the pre-generated, fully-pinned, PDM-free requirements.txt. run.sh
    # installs from it with plain pip (PDM is only a build-time tool); the
    # package itself runs from source via PYTHONPATH, so only the third-party
    # deps need installing.
    shutil.copy2(requirements, arch / "requirements.txt")
    # core: source + pyproject.
    core = pkgs / "core"
    shutil.copytree(PKGS / "core", core, ignore=IGNORE)
    for junk in ("pdm.lock", "pdm.toml", ".python-version", "CONVERSION_GUIDE.md"):
        (core / junk).unlink(missing_ok=True)
    shutil.rmtree(core / "tests", ignore_errors=True)
    # dashboard: standalone server + package.json (dist is a separate archive).
    dash = pkgs / "dashboard"
    dash.mkdir()
    shutil.copy2(PKGS / "dashboard" / "serve.mjs", dash / "serve.mjs")
    shutil.copy2(PKGS / "dashboard" / "package.json", dash / "package.json")
    (pkgs / "__init__.py").unlink(missing_ok=True)


def agents_md() -> str:
    return (
        "# Understand-Anything\n\n"
        "AI-powered codebase understanding — analyze, visualize, and explain any project.\n\n"
        "Skills live in `skills/` (`understand`, `understand-dashboard`, `understand-chat`,\n"
        "`understand-diff`, `understand-explain`, `understand-onboard`,\n"
        "`understand-language`, `understand-framework`).\n"
        "The deterministic pipeline runs via `packages/arch_analysis/run.sh <module> …`.\n"
    )


# --------------------------------------------------------------------------- #
# Archives
# --------------------------------------------------------------------------- #

def tar_dir(src: Path, arcname: str, out: Path) -> Path:
    with tarfile.open(out, "w:gz") as tar:
        tar.add(src, arcname=arcname, recursive=True)
    return out


def make_archives(payload: Path, wheelhouse: Path, version: str,
                  do_wheelhouse: bool, do_dashboard: bool) -> list[Path]:
    made = []
    made.append(tar_dir(payload, "understand-anything-plugin",
                        DIST / f"understand-anything-plugin-{version}.tar.gz"))
    if do_wheelhouse and wheelhouse.exists():
        made.append(tar_dir(wheelhouse, "wheelhouse",
                            DIST / f"understand-anything-wheelhouse-{platform_tag()}-{version}.tar.gz"))
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

    # Ship the marketplace manifest so `claude plugin marketplace add
    # /usr/share/understand-anything` works (source ./understand-anything-plugin
    # resolves to the payload postinst extracts). Enables the native Claude path.
    mp = REPO / ".claude-plugin" / "marketplace.json"
    if mp.exists():
        (share / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        shutil.copy2(mp, share / ".claude-plugin" / "marketplace.json")

    (debian / "control").write_text(
        f"""Package: understand-anything
Version: {version}
Section: devel
Priority: optional
Architecture: {arch}
Depends: python3 (>= 3.14~), python3-venv, python3-pip
Recommends: nodejs (>= 22)
Maintainer: {MAINTAINER}
Description: AI-powered codebase understanding — analyze, visualize, explain any project.
 Ships the Understand-Anything plugin (skills, agents, hooks), the deterministic
 arch_analysis Python engine with an offline wheelhouse, and a pre-built dashboard.
 After install, run `understand-anything <platform>` to enable it for your user.
""")

    (debian / "postinst").write_text(
        """#!/bin/sh
set -e
SHARE=/usr/share/understand-anything
PLUGIN="$SHARE/understand-anything-plugin"
rm -rf "$PLUGIN"
tar -xzf "$SHARE"/understand-anything-plugin-*.tar.gz -C "$SHARE"
if ls "$SHARE"/understand-anything-wheelhouse-*.tar.gz >/dev/null 2>&1; then
  tar -xzf "$SHARE"/understand-anything-wheelhouse-*.tar.gz -C "$PLUGIN/packages/arch_analysis"
fi
if ls "$SHARE"/understand-anything-dashboard-*.tar.gz >/dev/null 2>&1; then
  tar -xzf "$SHARE"/understand-anything-dashboard-*.tar.gz -C "$PLUGIN/packages/dashboard"
fi
# Warm the arch_analysis venv system-wide (offline, from the wheelhouse).
if [ -x "$PLUGIN/packages/arch_analysis/run.sh" ]; then
  "$PLUGIN/packages/arch_analysis/run.sh" --ensure || \
    echo "understand-anything: venv will be created on first use." >&2
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
    ap.add_argument("--skip-python", action="store_true")
    ap.add_argument("--skip-wheelhouse", action="store_true")
    ap.add_argument("--skip-dashboard", action="store_true")
    ap.add_argument("--python-only", action="store_true")
    ap.add_argument("--deb", action="store_true", help="also build the Debian package")
    ap.add_argument("--clean", action="store_true")
    args = ap.parse_args()

    version = read_version()
    if args.clean:
        shutil.rmtree(BUILD, ignore_errors=True)
        shutil.rmtree(DIST, ignore_errors=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)

    pywheels = DIST / "python"
    wheelhouse = BUILD / "wheelhouse"

    # Export the locked deps first — the wheelhouse is built from this file and
    # it ships in the payload, so both agree on exact versions.
    requirements = export_requirements(BUILD / "requirements.txt")

    if not args.skip_python:
        build_python(pywheels)
    if not args.skip_wheelhouse:
        build_wheelhouse(pywheels, wheelhouse, requirements)
    if args.python_only:
        print("\n✓ dist/python built.")
        return 0
    if not args.skip_dashboard:
        build_dashboard()

    payload = BUILD / "payload"
    assemble_payload(payload, requirements)
    archives = make_archives(payload, wheelhouse, version,
                             do_wheelhouse=not args.skip_wheelhouse,
                             do_dashboard=not args.skip_dashboard)
    deb = build_deb(version, archives) if args.deb else None

    print("\n✓ dist/ artifacts:")
    for f in sorted(pywheels.glob("*")) if pywheels.exists() else []:
        print(f"   python/{f.name}")
    for f in archives + ([deb] if deb else []):
        print(f"   {f.name}  ({f.stat().st_size / (1024*1024):.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
