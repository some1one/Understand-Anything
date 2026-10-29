#!/bin/sh
# Registered only for SessionStart. Never wait for the host to close stdin.
exec </dev/null 2>/dev/null
[ "${UA_SKIP_UPDATE_CHECK:-}" = 1 ] && exit 0

plugin_root=$(CDPATH='' cd -P "$(dirname "$0")/.." && pwd) || exit 0

version_from_json() {
    sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([0-9][0-9.]*\)".*/\1/p' | head -n 1
}

valid_version() {
    # Bound component size so awk can compare every accepted value exactly.
    awk -v version="$1" 'BEGIN {
        if (version !~ /^[0-9]+\.[0-9]+\.[0-9]+$/) exit 1
        split(version, parts, ".")
        for (i = 1; i <= 3; i++) if (length(parts[i]) > 9) exit 1
    }'
}

installed=$(version_from_json < "$plugin_root/.claude-plugin/plugin.json")
valid_version "$installed" || exit 0
cache_root=${XDG_CACHE_HOME:-${LOCALAPPDATA:-${HOME:+$HOME/.cache}}}
[ -n "$cache_root" ] || exit 0
cache_dir=$cache_root/understand-anything
cache_file=$cache_dir/published-version.json
now=$(date +%s) || exit 0
latest=
checked_at=
if [ -f "$cache_file" ]; then
    latest=$(version_from_json < "$cache_file")
    checked_at=$(sed -n 's/.*"checkedAt"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$cache_file" | head -n 1)
fi
valid_version "$latest" || latest=

if ! awk -v now="$now" -v checked="$checked_at" 'BEGIN {
    age = now - checked / 1000
    exit !(checked ~ /^[0-9]+$/ && age >= 0 && age < 86400)
}'; then
    # -q ignores user curl configuration, including retries and proxy overrides.
    # No language runtime, Git, setup, or subprocess retaining host stdin.
    if command -v curl >/dev/null 2>&1; then
        if manifest=$(curl -q --fail --silent --show-error --connect-timeout 1 \
            --max-time 1 --max-filesize 16384 \
            'https://raw.githubusercontent.com/some1one/Understand-Anything/main/understand-anything-plugin/.claude-plugin/plugin.json'); then
            published=$(printf '%s\n' "$manifest" | version_from_json)
            if valid_version "$published"; then latest=$published; fi
        fi
    fi
    # Cache failed attempts as well; an unwritable cache must never fail startup.
    if mkdir -p "$cache_dir"; then
        (printf '{"checkedAt":%s000,"version":"%s"}\n' "$now" "$latest" > "$cache_file") || :
    fi
fi

valid_version "$latest" || exit 0
awk -v latest="$latest" -v installed="$installed" 'BEGIN {
    split(latest, a, "."); split(installed, b, ".")
    for (i = 1; i <= 3; i++) {
        if (a[i] + 0 > b[i] + 0) exit 0
        if (a[i] + 0 < b[i] + 0) exit 1
    }
    exit 1
}' || exit 0

# Only validated numeric versions enter the JSON string, so no escaping is needed.
message="[understand-anything] Version $latest is available (installed: $installed). Update/reinstall the plugin through your installation method, then reload it. Do not update or run setup automatically."
printf '{"systemMessage":"%s","hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' "$message" "$message"
exit 0
