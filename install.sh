#!/bin/sh
# @map map.install: the tool and its hook copied into a repository's tools/ folder in the language chosen, built or downloaded with its checksum, then init: the areas detected and the section for AGENTS.md
# Usage, from the root of the repository that adopts the map:
#   curl -fsSL https://raw.githubusercontent.com/mars1571/grepless/main/install.sh | sh                 # Python (the default)
#   curl -fsSL https://raw.githubusercontent.com/mars1571/grepless/main/install.sh | sh -s -- --lang go
#   sh /path/to/grepless/install.sh [--lang python|node|go|rust] [target repository, the working folder by default]
# Python and Node copy single files into tools/. Go and Rust build the binaries into tools/ when their toolchain is
# installed (go, cargo); without it, they download this system's binaries from the repository's latest release, check
# them against its SHA256SUMS and unpack them into tools/ (MAP_RELEASES names another place to download them from).
# map.json's command is set to the one installed, and init ends: the areas detected, the section for AGENTS.md printed.
# On Windows, run it in Git Bash (https://gitforwindows.org): the programs are installed as tools/map.exe and so on, and
# the command stays `tools/map`, which Git Bash resolves, so map.json reads the same on every system.
set -e
lang=python
target=.
while [ $# -gt 0 ]; do
  case "$1" in
    --lang) lang=$2; shift 2 ;;
    *) target=$1; shift ;;
  esac
done
here=$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)
[ -f "$here/install.sh" ] && [ -f "$here/python/map.py" ] || here=""      # a grepless checkout, or nothing (curl | sh)
repo=${MAP_REPO:-mars1571/grepless}
raw="https://raw.githubusercontent.com/$repo/main"
releases=${MAP_RELEASES:-https://github.com/$repo/releases/latest/download}
exe=
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) exe=.exe ;; esac      # Git Bash on Windows: the compiled programs are name.exe
py=
for p in python3 python; do      # the Python 3 that runs: on Windows python3 may be missing, or the Store's stub that does not run
  if "$p" -c 'import sys; sys.exit(sys.version_info[0] < 3)' > /dev/null 2>&1; then py=$p; break; fi
done
mkdir -p "$target/tools"
tools=$(cd "$target/tools" && pwd)
fetch() {  # fetch <path in the repository> <file in tools/>
  if [ -n "$here" ]; then cp "$here/$1" "$tools/$2"; else curl -fsSL "$raw/$1" -o "$tools/$2"; fi
}
source_of() {  # source_of <go|rust>: a folder holding the repository's source of that implementation
  if [ -n "$here" ]; then echo "$here"; else src=$(mktemp -d) && git clone -q --depth 1 "https://github.com/$repo" "$src/grepless" && echo "$src/grepless"; fi
}
unzip_to() {  # unzip_to <zip> <folder>: Git Bash has no unzip, but Windows ships a tar (bsdtar) that reads zips
  if command -v unzip > /dev/null; then unzip -oq "$1" -d "$2"; return; fi
  win=tar
  if command -v cygpath > /dev/null && [ -n "$SYSTEMROOT" ]; then win="$(cygpath -u "$SYSTEMROOT")/System32/tar.exe"; fi
  "$win" -xf "$1" -C "$2"
}
prebuilt() {  # prebuilt <go|rust>: this system's binaries from the release, checked against SHA256SUMS, into tools/
  case "$(uname -s)" in
    Darwin) os=darwin ;; Linux) os=linux ;; MINGW*|MSYS*|CYGWIN*) os=windows ;;
    *) echo "No release binaries for $(uname -s): install $2 and run this again."; exit 1 ;;
  esac
  case "$(uname -m)" in
    arm64|aarch64) arch=arm64 ;; x86_64|amd64) arch=x86_64 ;;
    *) echo "No release binaries for $(uname -m): install $2 and run this again."; exit 1 ;;
  esac
  ext=tar.gz
  [ "$os" = windows ] && ext=zip
  name="grepless-$1-$os-$arch.$ext"
  down=$(mktemp -d)
  echo "$2 is not installed: $name from $releases instead."
  if ! { curl -fsSL "$releases/$name" -o "$down/$name" && curl -fsSL "$releases/SHA256SUMS" -o "$down/SHA256SUMS"; }; then
    echo "Could not download $name and SHA256SUMS from $releases."; exit 1
  fi
  want=$(awk -v n="$name" '$2 == n || $2 == "*" n { print $1 }' "$down/SHA256SUMS")
  got=$( (sha256sum "$down/$name" 2>/dev/null || shasum -a 256 "$down/$name") | awk '{ print $1 }')
  [ -n "$want" ] && [ "$want" = "$got" ] || { echo "$name: its SHA-256 is not the one SHA256SUMS gives; nothing installed."; exit 1; }
  if [ "$ext" = tar.gz ]; then tar -xzf "$down/$name" -C "$tools"
  else unzip_to "$down/$name" "$tools"; fi
  rm -rf "$down"
  echo "$name: SHA-256 checked, unpacked into $tools."
}
case "$lang" in
  python)
    for f in map.py map-guard.py map-coach.py map-sessions.py; do fetch "python/$f" "$f"; done
    chmod +x "$tools"/map*.py
    cmd="${py:-python3} tools/map.py" ;;
  node)
    for f in map.mjs map-guard.mjs map-coach.mjs map-sessions.mjs; do fetch "node/$f" "$f"; done
    chmod +x "$tools"/map*.mjs
    cmd="node tools/map.mjs" ;;
  go)
    if command -v go > /dev/null; then
      src=$(source_of go)
      (cd "$src/go" && for b in map map-guard map-coach map-sessions; do go build -o "$tools/$b$exe" "./cmd/$b"; done)
    else
      prebuilt go go
    fi
    cmd="tools/map" ;;
  rust)
    if command -v cargo > /dev/null; then
      src=$(source_of rust)
      (cd "$src/rust" && cargo build --release -q && for b in map map-guard map-coach map-sessions; do cp "target/release/$b$exe" "$tools/$b$exe"; done)
    else
      prebuilt rust cargo
    fi
    cmd="tools/map" ;;
  *) echo "--lang python|node|go|rust"; exit 1 ;;
esac
echo "The map is in $tools ($lang). Its command: $cmd"
cd "$target"
case "$lang" in    # the tool's copies in tools/ are vendored code, which map.json's ignore leaves out of the map
  python) own="tools/map.py tools/map-guard.py tools/map-coach.py tools/map-sessions.py" ;;
  node) own="tools/map.mjs tools/map-guard.mjs tools/map-coach.mjs tools/map-sessions.mjs" ;;
  *) own="" ;;     # binaries: no code the map reads
esac
if [ -n "$py" ]; then    # map.json: its command, and the copies left out
  "$py" - "$cmd" "$own" <<'PY'
import json, os, sys
cmd, own = sys.argv[1], sys.argv[2].split()
try:
    cfg = json.load(open('map.json', encoding='utf-8')) if os.path.exists('map.json') else {}
except ValueError:
    sys.exit(f'map.json is not JSON: set "command": "{cmd}" in it, and "ignore" {", ".join(own) or "nothing"}.')
old, ignore = cfg.get('command'), cfg.get('ignore', [])
cfg['command'] = cmd
if own:
    cfg['ignore'] = ignore + [f for f in own if f not in ignore]
with open('map.json', 'w', encoding='utf-8', newline='\n') as f:      # LF on every system: Windows would write CRLF
    f.write(json.dumps(cfg, indent=2, ensure_ascii=False) + '\n')
print(f'map.json: the command is {cmd}' + (f' (it was {old})' if old and old != cmd else '') + ('; the copies in tools/ are left out of the map (ignore)' if own else '') + '.')
PY
elif command -v node > /dev/null; then
  node - "$cmd" "$own" <<'JS'
const fs = require('fs');
const [cmd, list] = process.argv.slice(2), own = list.split(' ').filter(Boolean);
let cfg = {};
try { if (fs.existsSync('map.json')) cfg = JSON.parse(fs.readFileSync('map.json', 'utf8')); } catch { console.log(`map.json is not JSON: set "command": "${cmd}" in it, and "ignore" ${own.join(', ') || 'nothing'}.`); process.exit(1); }
const old = cfg.command, ignore = cfg.ignore || [];
cfg.command = cmd;
if (own.length) cfg.ignore = ignore.concat(own.filter(f => !ignore.includes(f)));
fs.writeFileSync('map.json', JSON.stringify(cfg, null, 2) + '\n');
console.log(`map.json: the command is ${cmd}` + (old && old !== cmd ? ` (it was ${old})` : '') + (own.length ? '; the copies in tools/ are left out of the map (ignore)' : '') + '.');
JS
elif [ ! -f map.json ]; then
  printf '{\n  "command": "%s"\n}\n' "$cmd" > map.json
else    # neither Python nor Node: the command's line edited in place
  sed "1,/\"command\"/s|\"command\": *\"[^\"]*\"|\"command\": \"$cmd\"|" map.json > map.json.new && mv map.json.new map.json
  grep -q "\"command\": \"$cmd\"" map.json || echo "map.json names no command: add \"command\": \"$cmd\" to it."
fi
$cmd init
