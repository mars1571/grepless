#!/bin/sh
# @map map.install: the tool and its hook copied into a repository's tools/ folder in the language chosen, then init: the areas detected and the section for AGENTS.md
# Usage, from the root of the repository that adopts the map:
#   curl -fsSL https://raw.githubusercontent.com/mars1571/grepless/main/install.sh | sh                 # Python (the default)
#   curl -fsSL https://raw.githubusercontent.com/mars1571/grepless/main/install.sh | sh -s -- --lang node
#   sh /path/to/grepless/install.sh [--lang python|node|go|rust] [target repository, the working folder by default]
# Python and Node copy single files into tools/. Go and Rust build the binaries into tools/ when their toolchain is
# installed (go, cargo); without it, the release page of the repository has prebuilt binaries to copy there.
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
repo=${MAP_REPO:-mars1571/grepless}
raw="https://raw.githubusercontent.com/$repo/main"
mkdir -p "$target/tools"
fetch() {  # fetch <path in the repository> <file in tools/>
  if [ -n "$here" ] && [ -f "$here/$1" ]; then cp "$here/$1" "$target/tools/$2"; else curl -fsSL "$raw/$1" -o "$target/tools/$2"; fi
}
case "$lang" in
  python)
    for f in map.py map-guard.py map-coach.py map-sessions.py; do fetch "python/$f" "$f"; done
    chmod +x "$target"/tools/map*.py
    cmd="python3 tools/map.py" ;;
  node)
    for f in map.mjs map-guard.mjs map-coach.mjs map-sessions.mjs; do fetch "node/$f" "$f"; done
    chmod +x "$target"/tools/map*.mjs
    cmd="node tools/map.mjs" ;;
  go)
    command -v go >/dev/null || { echo "go is not installed: copy the binaries of the release page into $target/tools instead"; exit 1; }
    src=${here:-$(mktemp -d)}
    [ -d "$src/go" ] || { git clone -q --depth 1 "https://github.com/$repo" "$src/map-src" && src="$src/map-src"; }
    (cd "$src/go" && for b in map map-guard map-coach map-sessions; do go build -o "$(cd "$target/tools" && pwd)/$b" "./cmd/$b"; done)
    cmd="tools/map" ;;
  rust)
    command -v cargo >/dev/null || { echo "cargo is not installed: copy the binaries of the release page into $target/tools instead"; exit 1; }
    src=${here:-$(mktemp -d)}
    [ -d "$src/rust" ] || { git clone -q --depth 1 "https://github.com/$repo" "$src/map-src" && src="$src/map-src"; }
    (cd "$src/rust" && cargo build --release -q && for b in map map-guard map-coach map-sessions; do cp "target/release/$b" "$(cd "$target/tools" && pwd)/$b"; done)
    cmd="tools/map" ;;
  *) echo "--lang python|node|go|rust"; exit 1 ;;
esac
echo "The map is in $target/tools ($lang). Its command: $cmd"
cd "$target"
if [ ! -f map.json ]; then printf '{\n  "command": "%s"\n}\n' "$cmd" > map.json; fi
$cmd init
