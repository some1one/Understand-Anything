#!/usr/bin/env bash
# Install a repository-local Valgrind from verified Debian/Ubuntu package indexes.
# No system package changes or sudo. The tool directory is already Git-ignored.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
launcher="$repo/.private/benchmark-tools/bin/valgrind"
if [ -x "$launcher" ]; then
  "$launcher" --version
  exit 0
fi
if command -v valgrind >/dev/null; then
  valgrind --version
  exit 0
fi
if ! command -v apt-get >/dev/null || ! command -v dpkg-deb >/dev/null; then
  echo 'Install Valgrind with your OS package manager; this local bootstrap supports Debian/Ubuntu.' >&2
  exit 2
fi
mkdir -p "$repo/.private/benchmark-tools/bin"
setup_dir=$(mktemp -d "$repo/.private/benchmark-tools/valgrind.XXXXXXXX")
cd "$setup_dir"
apt-get download valgrind
if ! dpkg-query -W -f='${Status}' libc6-dbg 2>/dev/null | grep -q 'install ok installed'; then
  libc_version=$(dpkg-query -W -f='${Version}' libc6)
  apt-get download "libc6-dbg=$libc_version"
fi
for package in ./*.deb; do
  dpkg-deb --extract "$package" "$setup_dir/root"
done
python3 - "$setup_dir" "$launcher" <<'PY'
from pathlib import Path
import shlex, sys
prefix, launcher = map(Path, sys.argv[1:])
libs = next((prefix / 'root/usr').glob('lib*/valgrind/memcheck-*'), None)
if libs is None:
    raise SystemExit('Cannot find the extracted Valgrind tool libraries')
text = '#!/usr/bin/env bash\nset -euo pipefail\n'
text += 'export VALGRIND_LIB=' + shlex.quote(str(libs.parent)) + '\n'
text += 'exec ' + shlex.quote(str(prefix / 'root/usr/bin/valgrind'))
text += ' --extra-debuginfo-path=' + shlex.quote(str(prefix / 'root')) + ' "$@"\n'
launcher.write_text(text)
launcher.chmod(0o755)
PY
"$launcher" --version
# Detect missing loader debug information or incompatible host libraries now.
"$launcher" --tool=memcheck --quiet --error-exitcode=97 /usr/bin/true
printf '%s\n' 'Repository-local Valgrind is ready; make benchmark-full discovers it automatically.'
