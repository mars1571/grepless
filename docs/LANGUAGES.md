# One tool, four languages

The map is written four times, in Python, Node, Go and Rust, and the four give the same answers: the same
`map.yaml` byte for byte, the same `ask`, `brief`, `find`, `gaps`, `check`, and the same guard for the five
agents. `tests/conformance.py` runs every implementation against 46 golden answers recorded from the Python
version, the reference; `bench/run.py` times them on a synthetic codebase and compares the maps they write.

| | Python | Node | Go | Rust |
|---|---|---|---|---|
| Files | `python/map.py`, `map-guard.py`, `map-coach.py`, `map-sessions.py` | `node/map.mjs`, `map-guard.mjs`, `map-coach.mjs`, `map-sessions.mjs` | `go/cmd/*` on `go/internal/mapcore`, `go/internal/guard` | `rust/src/*`, four binaries |
| Needs | Python 3.9+ | Node 18+ | Go 1.22+ to build; nothing to run | cargo to build; nothing to run |
| Dependencies | none | none | none | `regex`, `serde_json`, `indexmap` |
| Lines | 1,800 + 560 + 80 + 180 | 1,000 + 450 + 60 + 150 | 3,700 | 3,300 |
| Install | `install.sh` (the default) | `install.sh --lang node` | `install.sh --lang go`, or the release binaries | `install.sh --lang rust`, or the release binaries |
| Command (`map.json`) | `python3 tools/map.py` | `node tools/map.mjs` | `tools/map` | `tools/map` |

## Which to pick

- **Python** when your repository already needs Python, or when you want to read the tool: it is the reference,
  the shortest, and the one the article was measured with.
- **Node** when the repository is JavaScript or TypeScript and Python is not around.
- **Go or Rust** when the guard's latency matters: a hook runs on every tool call of the agent, and a compiled
  binary answers in 3 ms against 23 ms for Python and 31 ms for Node. On a codebase of 400 files the whole map
  builds in 60 to 70 ms, `brief` answers in 90 to 105 ms. The binaries have no runtime to install.

The output of every command is identical, so switching language later is a matter of changing `command` in
`map.json` and the hook's command in the agent's settings (`map-guard install <agent>` writes it).

## Measured

`bench/run.py` on a synthetic codebase of 400 files and 2,940 tagged blocks (`bench/corpus.py`), the median of
three runs on a laptop, October 2026 ([the data](../article/data/languages.json),
[Figure 12](../article/images/12-four-implementations.png)):

| Command | Python | Node | Go | Rust |
|---|---|---|---|---|
| build, cold cache | 0.50 s | 0.38 s | 0.23 s | 0.13 s |
| build, warm cache | 0.22 s | 0.26 s | 0.07 s | 0.06 s |
| check | 0.22 s | 0.26 s | 0.07 s | 0.06 s |
| brief | 0.30 s | 0.31 s | 0.11 s | 0.09 s |
| ask, one question | 0.07 s | 0.06 s | 0.03 s | 0.03 s |
| ask, eight questions | 0.13 s | 0.08 s | 0.09 s | 0.04 s |
| find | 0.13 s | 0.07 s | 0.09 s | 0.04 s |
| impact | 0.08 s | 0.08 s | 0.02 s | 0.02 s |
| guard, per tool call | 23 ms | 31 ms | 3 ms | 3 ms |

The four maps were byte-identical. The cache (the parse of each file, in the system's temporary folder, one per
implementation) is what separates a cold build from a warm one; an agent's session is warm after its first call.

## How the four stay the same

The Python version avoids what the other languages' regular expression engines lack (no lookarounds, no
backreferences: the shell line is tokenised and the heredocs are cut by code), writes JSON and YAML strings
with one escaping rule, sorts with explicit keys, rounds the ranking scores to nine decimals, and counts
characters, not bytes. Each port follows it function by function, with the same names. A change to the tool is
made in Python first, recorded in the golden answers (`python3 tests/conformance.py --record`), and then made in
the other three until `make conformance` passes.

## Building

```sh
make go            # go/bin/map, map-guard, map-coach, map-sessions
make rust          # rust/target/release/…
make conformance   # every built implementation against the golden answers
make bench         # the four timed; writes article/data/languages.json
```
