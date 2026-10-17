# AGENTS.md

This repository is **grepless**: a code map and a pre-tool hook for AI coding agents. To learn what it does, read
`README.md`, then `docs/METHOD.md` and `docs/EVIDENCE.md`. To work on it, read on: this repository is worked the way
it tells others to work, with its own map, its own guard and coach on five agents, and a git hook that keeps the map
current (README.md, "This repository uses its own method", lists where each piece is).

## Finding code

Every block of code carries a tag naming it (`@map <area>.<topic>.<part>: what it does`), and the map is read
from the tags and the code: `map.yaml` (the areas and what each needs from the others) and `map/<area>.yaml`
(each area's components). The map, not grep, is how this repository is read. Every call of an agent re-reads the
whole conversation, so questions go in rounds: every question of a round in one call, each answered whole.

1. **Start with `python3 python/map.py brief <the task's words>`**, as the code names things: the components
   the words name, their blocks and lines, what they declare, need and are needed by, their tests, docs and
   latest commits; then the first round of questions, as one call.
2. **Then one `ask` for each round of questions.** Write down every question the brief leaves open and ask them
   together; a later round asks only what the answers opened:
   `python3 python/map.py ask <question> [<question> …] [--in <paths>] [--all]` reads and locates everything:
   a block id (its code), an identifier (what it is, the code declaring it, every line naming it), a file (whole,
   or its outline), a folder, `src/x.js:120-180`, `docs/X.md#heading`, `data.json#key`, `'src/**/*.css'`, or any
   text (every line holding it, by block or section). `--in` narrows the questions before it.
   Beside `ask`: `find <words>`, `history <id>` (its commits), `deps` and `impact <id or file>` (imports, and
   the tests to run), `recipe [name]` (the steps of a change across layers).
3. **Do not read or search the code and the docs with `grep`, `rg`, `sed`, `cat`, `head`, `tail`, `ls`, `find`,
   with a script that only prints them, or with a file-reading tool on whole files**: `ask` answers the same
   question, by block, with the code. Counting, computing over data, editing and other files go ahead; so does a
   range of lines before an edit.
4. **Tag what you add or move** (`docs/TAGGING.md`): a tag on the line above each block, in the file's comment form,
   `@end <id>` when other code follows it; keep purposes true. **End each change with `python3 python/map.py check`**, which also
   checks that the map is current (`python3 python/map.py build` writes it again).

## How to work here

The four practices of [docs/METHOD.md](docs/METHOD.md), in this repository:

- **Start with `brief`, then read in rounds of `ask`.** A round is every question you can already name, in one
  call; a call per question is the old way through a new door.
- **One session per change.** A task of several changes is planned first, in a Markdown plan with `## Part <n>`
  sections that name their files, and each part goes in a session of its own. `python3 python/map.py plan <plan.md>`
  says which parts share no file and no import, so two agents can build them at once, each in its own git worktree.
- **Check each change, run the whole suite once.** A change ends with `python3 python/map.py build && python3
  python/map.py check` and the tests that reach it (`python3 python/map.py impact <id or file>` names them). The
  whole suite runs once per task, before the commit: `make check` (the unit tests, this map and the example's, and
  the four implementations against the golden answers).
- **The guard and the coach are on.** `.claude/settings.json`, `.codex/hooks.json`, `.cursor/hooks.json`,
  `.github/hooks/map-guard.json` and `.gemini/settings.json` run `python/map-guard.py` before a tool call and
  `python/map-coach.py` after it. A refusal names the `ask` that answers the same question: run it. When the guard
  refuses something that is not a read of the code or the docs, that is a bug of the guard: fix it in the four
  implementations, with its case in `tests/conformance.py`.

## Measuring a session

`python3 python/map-sessions.py` reads Claude Code's transcripts of this folder (the `.jsonl` files in the folder of
`~/.claude/projects/` named after this one's path) and prints one line per session: the model calls, the context re-read, the
calls that only searched or read and how many of them went through the map, the asks and the questions per ask,
the reads of the code that ran outside the map, the runs of eight or more reading calls in a row, and the model's
median response time under and over 300k tokens of context. `--since YYYY-MM-DD` keeps the recent sessions; a
session id prefix, or the path of a `.jsonl`, picks one. Run it when a session ends: the share of reads through the
map and the questions per ask are the two numbers to watch.

## Rules of this repository

- **Four implementations, one behaviour.** Python is the reference; Node, Go and Rust give the same answers. A
  change to what the tool prints is made in all four, with its golden answer in `tests/golden/`.
- **Checks.** `python3 -m unittest discover -s tests`, `python3 python/map.py check` (and in `example/`), and
  `python3 tests/conformance.py` for each implementation (`make conformance` runs all four; `make check` runs it
  all). CI runs the same.
- **The map stays current.** `make setup` once per clone: git then runs `.githooks/pre-commit` before each commit,
  which writes the map again and checks it.
- **The article's numbers come from `article/data/`.** Figures are drawn by `article/src/figures.py` and rendered
  by `article/src/render.mjs`; the transcript measurements by `article/analysis/`. A number in the text that is
  not in a data file is a bug.
- **Claims about other tools** cite the tool's own page, in `docs/COMPARISON.md`.
