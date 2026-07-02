# Understand-Anything

AI-powered codebase understanding — analyze, visualize, and explain any project. It
combines LLM intelligence with deterministic static analysis to produce an interactive
knowledge-graph dashboard and a set of agent skills (`/understand`, `/understand-dashboard`,
`/understand-chat`, `/understand-diff`, `/understand-explain`, `/understand-onboard`,
`/understand-domain`).

It installs as a set of **Agent Skills** for whichever AI coding tool you use, plus a
bundled Python analysis engine (`arch_analysis`) and a pre-built dashboard.

## Prerequisites

- **Python ≥ 3.14** — required by the analysis pipeline. The bundled offline wheels are
  built for CPython 3.14; on other versions the installer falls back to an online install.
- **Node.js ≥ 22** — only for `/understand-dashboard` (the interactive graph viewer).
- **git** — for the clone-based install.

## Supported platforms

| Install id  | Tool(s) | How it installs |
|-------------|---------|-----------------|
| `claude`    | Claude Code | **native CLI** (`claude plugin install`); scripted fallback → `~/.claude/skills` |
| `codex`     | OpenAI Codex | **native CLI** (`codex plugin add`, global only); scripted fallback → `~/.agents/skills` |
| `opencode`  | opencode | `~/.agents/skills` |
| `agents`    | Zed, VSCodium, and any tool using the cross-client convention | `~/.agents/skills` |
| `vscode`    | GitHub Copilot (VS Code) | `~/.copilot/skills` |
| `jetbrains` | JetBrains Junie (IntelliJ, PyCharm, …) | `~/.junie/skills` |
| `kilo`      | Kilo Code | `~/.kilo/skills` |
| `kiro`      | AWS Kiro | `~/.kiro/skills` (+ agent config) |
| `cursor`    | Cursor | **project-only** (`.cursor/skills`) — requires `--local <PATH>` |

The installer **prefers each target's native plugin CLI and falls back to the scripted
symlink installer** — today Claude Code and Codex install via their marketplace CLIs
(`claude plugin` / `codex plugin`), and everything else drops skill files into the paths
above. (opencode's `plugin` command installs npm modules, not skills, so opencode uses the
filesystem path.) Every platform except `cursor` installs globally by default; add
`--local <PATH>` to install into a specific project instead. `cursor` is project-only, so
it always needs `--local <PATH>`. Set `UA_NO_NATIVE=1` to force the scripted path.

---

## Option A — Clone the repository

Best for trying it out, developing, or keeping the plugin updated via `git pull`.

```bash
git clone <repo-url> understand-anything
cd understand-anything

# Install for your tool (see the table above).
./install.sh claude                # Claude Code — uses the native `claude plugin` CLI
./install.sh codex                 # Codex — uses the native `codex plugin` CLI
./install.sh agents                # Zed / VSCodium / … — links into ~/.agents/skills
# …or with the Makefile (`make install-<TAB>` completes the platform):
make install-claude
```

For scripted platforms this symlinks the skills from the checkout into your tool's skills
directory and links `~/.understand-anything-plugin` to the repo, so `git pull` updates
everything in place. For Claude Code it registers the local marketplace and installs the
plugin natively. The Python virtualenv is created automatically on first use (or warmed
during install if the network is available).

Other commands:

```bash
./install.sh                       # interactive platform picker
./install.sh cursor --local .      # install into the current project (cursor is project-only)
./install.sh claude --local .      # install into a project instead of globally
./install.sh --uninstall agents    # remove the install for a platform
./install.sh --help

LOCAL=. make install-cursor        # same, via the Makefile (LOCAL given inline, up front)
make uninstall-agents
```

> Running `./install.sh` from inside the checkout links directly to the repo. If you instead
> have only the standalone `install.sh` plus the release archives
> (`understand-anything-plugin-*.tar.gz`, `…-wheelhouse-*.tar.gz`, `…-dashboard-*.tar.gz`),
> put them beside the script (or set `UA_ASSET_DIR`) and it will assemble them offline.

---

## Option B — Debian package (`.deb`)

Best for a system-wide install on Linux x86-64. Assumes you already have the
`understand-anything_<version>_amd64.deb` file.

```bash
sudo apt install ./understand-anything_2.8.1_amd64.deb
# or: sudo dpkg -i understand-anything_2.8.1_amd64.deb && sudo apt-get -f install
```

The package pulls in its dependencies (`python3 ≥ 3.14`, `python3-venv`, `python3-pip`;
recommends `nodejs`), unpacks the plugin into `/usr/share/understand-anything/`, and warms
the Python environment **offline** from the bundled wheelhouse — no network or build step
required.

Then enable it for **your user** (the package is system-wide; linking is per-user):

```bash
understand-anything claude              # native install; or: codex | opencode | agents | vscode | jetbrains | kilo | kiro
understand-anything cursor --local .    # cursor is project-only
understand-anything --uninstall agents  # remove your user's links
```

> The `.deb` targets **Linux x86-64 + Python 3.14** because the offline wheelhouse ships
> CPython-3.14 wheels. On other architectures/versions, use Option A.

To remove the package:

```bash
sudo apt remove understand-anything
```

---

## After installing

Restart your CLI/IDE so it picks up the new skills, then run `/understand` in a project to
build its knowledge graph, and `/understand-dashboard` to open the interactive viewer.

## Building the distributables yourself

From a checkout (see [`CLAUDE.md`](CLAUDE.md) for details):

```bash
make           # default goal = build all artifacts (same as `make package`) → dist/
make package   # wheels + wheelhouse + dashboard + the release archives → dist/
make deb       # the above + the Debian package → dist/
make deps      # install every subproject's dependencies (for development)
```
