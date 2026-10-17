# AGENTS.md

This repository is **grepless**: a code map and a pre-tool hook for AI coding agents. To learn what it does, read
`README.md`, then `docs/METHOD.md` and `docs/EVIDENCE.md`. To work on it, read on.

## Finding code

Every block of code carries a tag naming it (`@map <area>.<topic>.<part>: what it does`), and the map is read
from the tags and the code: `map.yaml` (the areas and what each needs from the others) and `map/<area>.yaml`
(each area's components). Read this repository through its own map, not with grep: every call of an agent
re-reads the whole conversation, so questions go in rounds, every question of a round in one call.

1. Start with `python3 python/map.py brief <the task's words>`.
2. Then one `python3 python/map.py ask <question> [<question> …] [--in <paths>]` per round: a block id, a name, a
   file, `path:120-180`, `docs/X.md#heading` or any text, each answered whole.
3. Tag what you add or move (`docs/TAGGING.md`), and end each change with `python3 python/map.py check`.

## Rules of this repository

- **Four implementations, one behaviour.** Python is the reference; Node, Go and Rust give the same answers. A
  change to what the tool prints is made in all four, with its golden answer in `tests/golden/`.
- **Checks.** `python3 -m unittest discover -s tests`, `python3 python/map.py check` (and in `example/`), and
  `python3 tests/conformance.py` for each implementation (`make conformance` runs all four). CI runs the same.
- **The article's numbers come from `article/data/`.** Figures are drawn by `article/src/figures.py` and rendered
  by `article/src/render.mjs`; the transcript measurements by `article/analysis/`. A number in the text that is
  not in a data file is a bug.
- **Claims about other tools** cite the tool's own page, in `docs/COMPARISON.md`.
