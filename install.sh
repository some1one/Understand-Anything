#!/usr/bin/env bash
# Understand-Anything installer (macOS / Linux) — standalone (archives or git).
#
# Prefers a target's *native* plugin CLI (e.g. `claude plugin install`) and only
# falls back to the scripted symlink installer when no native command applies.
#
# Usage:
#   ./install.sh [<platform>]                  Install for <platform> (prompts if omitted)
#   ./install.sh <platform> --local <PATH>     Install into the project at <PATH>
#   ./install.sh --uninstall <platform> [--local <PATH>]
#   ./install.sh --assemble [<dir>]            Only assemble the plugin payload
#   ./install.sh --update                      Update (git checkout) / re-assemble
#   ./install.sh --help
#
# Platforms:  claude codex opencode agents vscode jetbrains kilo kiro cursor
#   * claude / codex prefer their native plugin CLI (marketplace install); the
#     rest are filesystem skill-drops. opencode's `plugin` command installs npm
#     modules (not skills), so it uses the scripted path like `agents`.
#   * cursor is project-only  → requires --local <PATH>
#   * every other platform installs globally by default; --local <PATH> is optional
#
# Distribution:
#   * If the payload archives are found next to this script (or in $UA_ASSET_DIR,
#     ./dist, or /usr/share/understand-anything), they are assembled — no network.
#       - understand-anything-plugin-*.tar.gz         (copied/source payload)
#       - understand-anything-wheelhouse-*.tar.gz     (offline Python wheels)
#       - understand-anything-dashboard-*.tar.gz       (pre-built static dashboard)
#   * Otherwise it falls back to a git checkout (set UA_REPO_URL).
#
# Environment:
#   UA_REPO_URL   Repo clone URL (git fallback only)
#   UA_DIR        Install/assemble home (default: $HOME/.understand-anything)
#   UA_ASSET_DIR  Directory holding the payload archives
#   UA_NO_NATIVE  If set, skip native CLIs and always use the scripted installer

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
UA_HOME="${UA_DIR:-$HOME/.understand-anything}"
PLUGIN_LINK="$HOME/.understand-anything-plugin"
MARKETPLACE="understand-anything"
PLUGIN_NAME="understand-anything"

info() { printf -- '→ %s\n' "$*"; }
ok()   { printf -- '  ✓ %s\n' "$*"; }
warn() { printf -- '  ! %s\n' "$*" >&2; }
die()  { printf 'Error: %s\n' "$*" >&2; exit 1; }

# --- platform table (kept in sync with scripts/build_dist.py) ---------------
# Columns:  id | global-skills-dir | style | project-local-skills-dir | local-flag | native-cli
#   global-skills-dir empty  → platform is project-only (local-flag = required)
#   local-flag ∈ required|optional|none
#   native-cli  ∈ claude|-   (a built-in CLI tried before the scripted installer)
# "agents" is the cross-client ~/.agents/skills (Codex, opencode, Zed, VSCodium, …).
platforms_table() {
  cat <<EOF
claude|$HOME/.claude/skills|per-skill|.claude/skills|optional|claude
codex|$HOME/.agents/skills|per-skill|.agents/skills|optional|codex
opencode|$HOME/.agents/skills|per-skill|.agents/skills|optional|-
agents|$HOME/.agents/skills|per-skill|.agents/skills|optional|-
vscode|$HOME/.copilot/skills|per-skill|.github/skills|optional|-
jetbrains|$HOME/.junie/skills|per-skill|.junie/skills|optional|-
kilo|$HOME/.kilo/skills|per-skill|.kilo/skills|optional|-
kiro|$HOME/.kiro/skills|per-skill|.kiro/skills|optional|-
cursor||per-skill|.cursor/skills|required|-
EOF
}
platform_ids()  { platforms_table | cut -d'|' -f1; }
global_ids()    { platforms_table | awk -F'|' '$2!=""{print $1}'; }
row_for()       { platforms_table | awk -F'|' -v id="$1" '$1==id{print;exit}'; }
field()         { cut -d'|' -f"$2" <<<"$1"; }

# --- asset discovery + assembly ---------------------------------------------
CORE_TGZ="" WHEELHOUSE_TGZ="" DASH_TGZ=""
find_assets() {
  local d found=""
  for d in "${UA_ASSET_DIR:-}" "$SCRIPT_DIR" "$SCRIPT_DIR/dist" \
           "/usr/share/understand-anything" "$PWD/dist"; do
    [ -n "$d" ] && [ -d "$d" ] || continue
    local core; core="$(ls "$d"/understand-anything-plugin-*.tar.gz 2>/dev/null | head -1 || true)"
    [ -n "$core" ] || continue
    CORE_TGZ="$core"
    WHEELHOUSE_TGZ="$(ls "$d"/understand-anything-wheelhouse-*.tar.gz 2>/dev/null | head -1 || true)"
    DASH_TGZ="$(ls "$d"/understand-anything-dashboard-*.tar.gz 2>/dev/null | head -1 || true)"
    found="$d"; break
  done
  [ -n "$found" ]
}

# Assemble the plugin payload into <parent>/understand-anything-plugin, overlaying
# the wheelhouse + dashboard build archives. Echoes the plugin dir path.
assemble_into() {
  local parent="$1" plugin="$1/understand-anything-plugin"
  mkdir -p "$parent"
  rm -rf "$plugin"
  info "Assembling plugin payload → $plugin"
  tar -xzf "$CORE_TGZ" -C "$parent"
  if [ -n "$WHEELHOUSE_TGZ" ]; then
    tar -xzf "$WHEELHOUSE_TGZ" -C "$plugin/packages/arch_analysis"
    ok "wheelhouse (offline Python deps)"
  fi
  if [ -n "$DASH_TGZ" ]; then
    tar -xzf "$DASH_TGZ" -C "$plugin/packages/dashboard"
    ok "dashboard (pre-built static bundle)"
  fi
  printf '%s\n' "$plugin"
}

# Resolve (assembling if needed) the plugin dir to link against. Echoes its path.
resolve_plugin_home() {
  # Running from a repo checkout: link straight to the in-tree plugin (the venv
  # is created on first use; the dashboard falls back to the Vite dev server).
  if [ -f "$SCRIPT_DIR/understand-anything-plugin/.claude-plugin/plugin.json" ]; then
    printf '%s\n' "$SCRIPT_DIR/understand-anything-plugin"; return 0
  fi
  if [ -d "/usr/share/understand-anything/understand-anything-plugin" ]; then
    printf '%s\n' "/usr/share/understand-anything/understand-anything-plugin"; return 0
  fi
  if find_assets; then
    assemble_into "$UA_HOME" | tail -1; return 0
  fi
  # git fallback
  local repo="$UA_HOME/repo"
  if [ -d "$repo/.git" ]; then
    info "Updating git checkout at $repo"; git -C "$repo" pull --ff-only >&2 || true
  else
    [ -n "${UA_REPO_URL:-}" ] || die "No payload archives found and UA_REPO_URL is unset. Provide the archives or set UA_REPO_URL."
    info "Cloning $UA_REPO_URL → $repo"; mkdir -p "$repo"; git clone "$UA_REPO_URL" "$repo" >&2
  fi
  printf '%s\n' "$repo/understand-anything-plugin"
}

# Directory holding a .claude-plugin/marketplace.json (for `claude plugin marketplace add`).
marketplace_source() {
  local d
  for d in "$SCRIPT_DIR" "$UA_HOME" "/usr/share/understand-anything" "$PWD"; do
    [ -n "$d" ] && [ -f "$d/.claude-plugin/marketplace.json" ] && { printf '%s\n' "$d"; return 0; }
  done
  return 1
}

# --- prerequisites ----------------------------------------------------------
check_prereqs() {
  if command -v python3 >/dev/null 2>&1; then
    local v; v="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo '?')"
    case "$v" in 3.1[4-9]|3.[2-9][0-9]|[4-9].*) : ;; *) warn "Python $v detected; the pipeline targets >= 3.14 (bundled wheels are 3.14). It will fall back to an online install if the wheelhouse doesn't match." ;; esac
  else
    warn "python3 not found — the analysis pipeline needs Python >= 3.14."
  fi
  command -v pdm >/dev/null 2>&1 || true  # optional (only for dev checkouts)
  command -v node >/dev/null 2>&1 || warn "node not found — /understand-dashboard needs Node.js >= 22."
}

# Warm the arch_analysis venv so the first /understand run isn't a cold install.
warm_env() {
  local plugin="$1" runsh="$1/packages/arch_analysis/run.sh"
  [ -f "$runsh" ] || return 0
  if [ ! -w "$1/packages/arch_analysis" ]; then
    info "Plugin payload is read-only (system install); skipping env warm-up."
    return 0
  fi
  info "Preparing the Python environment (first-run setup)…"
  "$runsh" --ensure >/dev/null 2>&1 && ok "arch_analysis venv ready" || \
    warn "Could not pre-build the venv now; it will be created on first /understand run."
}

# --- native CLIs (preferred over the scripted installer) --------------------
# native_available <native> [project]
# Whether a built-in CLI can handle this request. Codex's marketplace install is
# global-only, so it declines when a project dir (--local) is given.
native_available() {
  local native="$1" project="${2:-}"
  [ -z "${UA_NO_NATIVE:-}" ] || return 1
  case "$native" in
    claude) command -v claude >/dev/null 2>&1 && marketplace_source >/dev/null 2>&1 ;;
    codex)  [ -z "$project" ] && command -v codex >/dev/null 2>&1 && marketplace_source >/dev/null 2>&1 ;;
    *) return 1 ;;
  esac
}

# Try a target's built-in CLI. Return 0 on success (installer done), 1 to fall back.
native_install() {
  local native="$1" project="$2" src scope
  case "$native" in
    claude)
      src="$(marketplace_source)" || return 1
      info "Using native Claude Code CLI (claude plugin …)"
      claude plugin marketplace add "$src" >/dev/null 2>&1 \
        || claude plugin marketplace update "$MARKETPLACE" >/dev/null 2>&1 || true
      if [ -n "$project" ]; then
        scope=project
        ( cd "$project" && claude plugin install "$PLUGIN_NAME@$MARKETPLACE" --scope project >/dev/null 2>&1 ) || true
        ( cd "$project" && claude plugin list 2>/dev/null | grep -qi "$PLUGIN_NAME" ) || return 1
      else
        scope=user
        claude plugin install "$PLUGIN_NAME@$MARKETPLACE" --scope user >/dev/null 2>&1 || true
        claude plugin list 2>/dev/null | grep -qi "$PLUGIN_NAME" || return 1
      fi
      ok "claude plugin install $PLUGIN_NAME@$MARKETPLACE --scope $scope"
      return 0 ;;
    codex)
      [ -z "$project" ] || return 1   # codex marketplace install is global-only
      src="$(marketplace_source)" || return 1
      info "Using native Codex CLI (codex plugin …)"
      codex plugin marketplace add "$src" >/dev/null 2>&1 \
        || codex plugin marketplace upgrade >/dev/null 2>&1 || true
      codex plugin add "$PLUGIN_NAME@$MARKETPLACE" >/dev/null 2>&1 || true
      codex plugin list 2>/dev/null | grep -qi "$PLUGIN_NAME" || return 1
      ok "codex plugin add $PLUGIN_NAME@$MARKETPLACE"
      return 0 ;;
  esac
  return 1
}

native_uninstall() {
  local native="$1" project="$2"
  case "$native" in
    claude)
      command -v claude >/dev/null 2>&1 || return 1
      if [ -n "$project" ]; then
        ( cd "$project" && claude plugin uninstall "$PLUGIN_NAME" >/dev/null 2>&1 ) || return 1
      else
        claude plugin uninstall "$PLUGIN_NAME" >/dev/null 2>&1 || return 1
      fi
      ok "claude plugin uninstall $PLUGIN_NAME"
      return 0 ;;
    codex)
      command -v codex >/dev/null 2>&1 || return 1
      codex plugin remove "$PLUGIN_NAME" >/dev/null 2>&1 || return 1
      ok "codex plugin remove $PLUGIN_NAME"
      return 0 ;;
  esac
  return 1
}

# --- linking (scripted fallback) --------------------------------------------
list_skills() { local d; for d in "$1"/skills/*/; do [ -d "$d" ] && basename "$d"; done; }

link_skills_global() {
  local plugin="$1" target="$2" style="$3" skill
  mkdir -p "$target"
  case "$style" in
    per-skill)
      while IFS= read -r skill; do
        ln -sfn "$plugin/skills/$skill" "$target/$skill"; ok "$target/$skill"
      done < <(list_skills "$plugin") ;;
    folder)
      ln -sfn "$plugin/skills" "$target/understand-anything"; ok "$target/understand-anything" ;;
  esac
}

link_plugin_root() {
  local plugin="$1"
  if [ -L "$PLUGIN_LINK" ] || [ -e "$PLUGIN_LINK" ]; then
    ok "$PLUGIN_LINK already exists, leaving as-is"
  else
    ln -s "$plugin" "$PLUGIN_LINK"; ok "$PLUGIN_LINK → $plugin"
  fi
}

write_kiro_agent() {
  local plugin="$1"
  mkdir -p "$HOME/.kiro/agents"
  local resources="" a
  while IFS= read -r a; do
    [ -n "$a" ] || continue
    [ -n "$resources" ] && resources+=$',\n'
    resources+="    \"file://$a\""
  done < <(find "$plugin/agents" -maxdepth 1 -type f -name '*.md' | LC_ALL=C sort)
  cat > "$HOME/.kiro/agents/understand.json" <<KIROEOF
{
  "name": "understand",
  "description": "Analyze codebase into interactive knowledge graph — Understand Anything",
  "prompt": "file://$plugin/skills/understand/SKILL.md",
  "tools": ["read", "write", "shell", "grep", "glob", "code", "subagent"],
  "resources": [
$resources
  ]
}
KIROEOF
  ok "$HOME/.kiro/agents/understand.json"
}

# Copy the assembled plugin payload into a project root (scripted local install).
copy_payload_to() {
  local project="$1"
  if find_assets; then
    local tmp; tmp="$(mktemp -d)"
    tar -xzf "$CORE_TGZ" -C "$tmp"
    cp -R "$tmp/understand-anything-plugin/." "$project/"
    [ -n "$WHEELHOUSE_TGZ" ] && tar -xzf "$WHEELHOUSE_TGZ" -C "$project/packages/arch_analysis"
    [ -n "$DASH_TGZ" ] && tar -xzf "$DASH_TGZ" -C "$project/packages/dashboard"
    rm -rf "$tmp"
  else
    local src; src="$(resolve_plugin_home)"
    ( cd "$src" && tar --exclude='./packages/*/.venv' --exclude='./packages/*/node_modules' \
        --exclude='*/__pycache__' --exclude='*/.pytest_cache' -cf - . ) | tar -xf - -C "$project"
  fi
}

scripted_local_install() {
  local id="$1" local_dir="$2" project="$3" dirs d skill
  info "Installing project-local plugin into $project"
  copy_payload_to "$project"
  # Wire the universal .agents/skills + this target's own project skills dir.
  dirs="$(printf '%s\n%s\n' ".agents/skills" "$local_dir" | sort -u)"
  while IFS= read -r d; do
    [ -n "$d" ] && [ "$d" != "skills" ] || continue
    mkdir -p "$project/$d"
    local depth back; depth="$(awk -F/ '{print NF}' <<<"$d")"; back="$(printf '../%.0s' $(seq 1 "$depth"))skills"
    while IFS= read -r skill; do
      ln -sfn "$back/$skill" "$project/$d/$skill"; ok "$d/$skill → $back/$skill"
    done < <(list_skills "$project")
  done <<<"$dirs"
  [ "$id" = "kiro" ] && write_kiro_agent "$project"
  warm_env "$project"
}

# --- commands ---------------------------------------------------------------
# cmd_install <id> [project-dir]
cmd_install() {
  local id="$1" project="${2:-}" row global style local_dir local_flag native
  row="$(row_for "$id")"
  [ -n "$row" ] || die "Unknown platform: $id (supported: $(platform_ids | tr '\n' ' '))"
  global="$(field "$row" 2)"; style="$(field "$row" 3)"
  local_dir="$(field "$row" 4)"; local_flag="$(field "$row" 5)"; native="$(field "$row" 6)"

  # Enforce the --local matrix for this target.
  if [ -n "$project" ]; then
    [ "$local_flag" != "none" ] || die "$id does not support --local"
    [ -d "$project" ] || die "project dir does not exist: $project"
    project="$(cd "$project" && pwd -P)"
  else
    [ "$local_flag" != "required" ] || die "$id is project-only — pass --local <PATH>"
  fi

  check_prereqs

  # 1) Prefer the target's native CLI.
  if native_available "$native" "$project"; then
    if native_install "$native" "$project"; then
      printf '\n✓ Installed Understand-Anything for %s (native CLI).\n' "$id"
      printf '  Restart your CLI/IDE to pick up the plugin.\n'
      return 0
    fi
    warn "native install did not complete; falling back to the scripted installer"
  fi

  # 2) Scripted fallback (symlinks).
  if [ -n "$project" ]; then
    scripted_local_install "$id" "$local_dir" "$project"
    printf '\n✓ Installed project-local Understand-Anything into %s\n' "$project"
  else
    local plugin; plugin="$(resolve_plugin_home)"
    info "Linking skills for $id ($style → $global)"
    link_skills_global "$plugin" "$global" "$style"
    info "Linking universal plugin root"
    link_plugin_root "$plugin"
    [ "$id" = "kiro" ] && { info "Writing Kiro agent config"; write_kiro_agent "$plugin"; }
    warm_env "$plugin"
    printf '\n✓ Installed Understand-Anything for %s\n' "$id"
    printf '  Restart your CLI/IDE to pick up the skills.\n'
    [ "$id" = "kiro" ] && printf '  Usage: kiro-cli chat --agent understand "Analyze this project"\n'
  fi
  return 0
}

cmd_assemble() { local dest="${1:-$UA_HOME}"; find_assets || die "No payload archives found."; assemble_into "$dest" >/dev/null; ok "assembled into $dest/understand-anything-plugin"; }

# cmd_uninstall <id> [project-dir]
cmd_uninstall() {
  local id="$1" project="${2:-}" row global style local_dir native skill
  row="$(row_for "$id")"
  [ -n "$row" ] || die "Unknown platform: $id"
  global="$(field "$row" 2)"; style="$(field "$row" 3)"
  local_dir="$(field "$row" 4)"; native="$(field "$row" 6)"
  [ -n "$project" ] && project="$(cd "$project" 2>/dev/null && pwd -P || echo "$project")"

  # Native uninstall first when applicable.
  if native_available "$native" "$project" && native_uninstall "$native" "$project"; then
    return 0
  fi

  info "Removing skill links for $id"
  local target
  if [ -n "$project" ]; then target="$project/$local_dir"; else target="$global"; fi
  [ -n "$target" ] || { warn "nothing to remove for $id"; return 0; }
  if [ "$style" = "folder" ]; then
    [ -L "$target/understand-anything" ] && rm -f "$target/understand-anything" && ok "removed $target/understand-anything"
  elif [ -d "$target" ]; then
    for skill in "$target"/*; do
      [ -L "$skill" ] || continue
      case "$(readlink "$skill" 2>/dev/null || true)" in */understand-anything-plugin/skills/*|../*skills/*) rm -f "$skill"; ok "removed $skill" ;; esac
    done
  fi
  [ "$id" = "kiro" ] && [ -f "$HOME/.kiro/agents/understand.json" ] && rm -f "$HOME/.kiro/agents/understand.json" && ok "removed kiro agent"
  [ -z "$project" ] && [ -L "$PLUGIN_LINK" ] && rm -f "$PLUGIN_LINK" && ok "removed $PLUGIN_LINK"
  return 0
}

cmd_update() {
  if [ -d "$UA_HOME/repo/.git" ]; then git -C "$UA_HOME/repo" pull --ff-only && printf '✓ Updated (git).\n';
  elif find_assets; then assemble_into "$UA_HOME" >/dev/null; printf '✓ Re-assembled from archives.\n';
  else die "Nothing to update (no git checkout or archives)."; fi
}

prompt_platform() {
  local ids=() id i=1 choice=""
  while IFS= read -r id; do ids+=("$id"); done < <(global_ids)
  printf 'Which platform are you installing for?\n' >&2
  for id in "${ids[@]}"; do printf '  %d) %s\n' "$i" "$id" >&2; i=$((i+1)); done
  printf '  (Cursor is project-only: ./install.sh cursor --local <project-dir>)\n' >&2
  printf 'Choose [1-%d]: ' "${#ids[@]}" >&2
  if { exec 3</dev/tty; } 2>/dev/null; then read -r choice <&3 || true; exec 3<&-; else read -r choice || true; fi
  [[ "$choice" =~ ^[0-9]+$ ]] && (( choice>=1 && choice<=${#ids[@]} )) || die "Invalid choice: ${choice:-<none>}"
  printf '%s\n' "${ids[$((choice-1))]}"
}

usage() {
  cat <<USAGE
Understand-Anything installer

  install.sh [<platform>]                     Install (prompts if <platform> omitted)
  install.sh <platform> --local <PATH>        Install into the project at <PATH>
  install.sh --uninstall <platform> [--local <PATH>]
  install.sh --assemble [<dir>]               Assemble the payload only
  install.sh --update                         Update / re-assemble
  install.sh --help

Platforms:  $(platform_ids | tr '\n' ' ')
  cursor is project-only (requires --local); every other platform installs
  globally by default and accepts an optional --local <PATH>.

Native CLIs are preferred when available (e.g. claude plugin install); set
UA_NO_NATIVE=1 to force the scripted installer.

Environment: UA_REPO_URL, UA_DIR (=$UA_HOME), UA_ASSET_DIR, UA_NO_NATIVE
USAGE
}

# Parse "[--local <PATH>]" out of the remaining args; sets LOCAL_PATH.
LOCAL_PATH=""
parse_local() {
  LOCAL_PATH=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --local) shift; [ -n "${1:-}" ] || die "--local requires <PATH>"; LOCAL_PATH="$1" ;;
      *) die "Unexpected argument: $1" ;;
    esac
    shift
  done
}

main() {
  case "${1:-}" in
    -h|--help) usage ;;
    --update) cmd_update ;;
    --assemble) shift; cmd_assemble "${1:-}" ;;
    --uninstall)
      shift; [ -n "${1:-}" ] || die "--uninstall requires a platform"
      local id="$1"; shift; parse_local "$@"; cmd_uninstall "$id" "$LOCAL_PATH" ;;
    "") cmd_install "$(prompt_platform)" ;;
    -*) die "Unknown option: $1" ;;
    *)
      local id="$1"; shift; parse_local "$@"; cmd_install "$id" "$LOCAL_PATH" ;;
  esac
}

main "$@"
