# AGENTS.md — the section to paste

Paste the section below into your repository's `AGENTS.md` (Codex, Cursor, Copilot, Gemini CLI and the other
agents that read it) and, for Claude Code, import it from `CLAUDE.md` with a line `@AGENTS.md` (or let Claude
Code read `AGENTS.md` directly when there is no `CLAUDE.md`). `python3 tools/map.py init` prints the same
section with your own command. Keep it short: an instructions file is read at the start of every session.

---

## Finding code

Every block of code carries a tag naming it (`@map <area>.<topic>.<part>: what it does`), and the map is read
from the tags and the code: `map.yaml` (the areas and what each needs from the others) and `map/<area>.yaml`
(each area's components). The map, not grep, is how this repository is read. Every call of an agent re-reads the
whole conversation, so questions go in rounds: every question of a round in one call, each answered whole.

1. **Start with `python3 tools/map.py brief <the task's words>`**, as the code names things: the components
   the words name, their blocks and lines, what they declare, need and are needed by, their tests, docs and
   latest commits; then the first round of questions, as one call.
2. **Then one `ask` for each round of questions.** Write down every question the brief leaves open and ask them
   together; a later round asks only what the answers opened:
   `python3 tools/map.py ask <question> [<question> …] [--in <paths>] [--all]` reads and locates everything:
   a block id (its code), an identifier (what it is, the code declaring it, every line naming it), a file (whole,
   or its outline), a folder, `src/x.js:120-180`, `docs/X.md#heading`, `data.json#key`, `'src/**/*.css'`, or any
   text (every line holding it, by block or section). `--in` narrows the questions before it.
   Beside `ask`: `find <words>`, `history <id>` (its commits), `deps` and `impact <id or file>` (imports, and
   the tests to run), `recipe [name]` (the steps of a change across layers).
3. **Do not read or search the code and the docs with `grep`, `rg`, `sed`, `cat`, `head`, `tail`, `ls`, `find`,
   with a script that only prints them, or with a file-reading tool on whole files**: `ask` answers the same
   question, by block, with the code. Counting, computing over data, editing and other files go ahead; so does a
   range of lines before an edit.
4. **Tag what you add or move** (`https://github.com/mars1571/grepless/blob/main/docs/TAGGING.md`): a tag on the line above each block, in the file's comment form,
   `@end <id>` when other code follows it; keep purposes true. **End each change with `python3 tools/map.py check`**, which also
   checks that the map is current (`python3 tools/map.py build` writes it again).
