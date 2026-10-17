#!/bin/sh
# @map ci.release.pack: one build's four programs packed under the name install.sh downloads, grepless-<go|rust>-<os>-<arch>: a .tar.gz, or a .zip for Windows
# Usage: sh .github/pack.sh <go|rust> <darwin|linux|windows> <arm64|x86_64> <folder holding the four programs> <dist folder>
set -e
impl=$1 os=$2 arch=$3 bin=$4 dist=$5
exe=
[ "$os" = windows ] && exe=.exe
name=grepless-$impl-$os-$arch
mkdir -p "$dist/$name"
for b in map map-guard map-coach map-sessions; do cp "$bin/$b$exe" "$dist/$name/"; done
if [ "$os" != windows ]; then
  tar -czf "$dist/$name.tar.gz" -C "$dist/$name" map map-guard map-coach map-sessions
elif command -v 7z > /dev/null; then
  (cd "$dist/$name" && 7z a -tzip -bd "../$name.zip" ./*.exe > /dev/null)
else
  (cd "$dist/$name" && zip -q "../$name.zip" ./*.exe)
fi
rm -rf "${dist:?}/$name"
echo "$dist/$name: packed"
