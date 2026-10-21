# The commands

All of them: `python3 tools/map.py <command> …` (or whatever `command` in `map.json` says: the map's own
messages use it). Everything runs from the repository's root; `--root <path>` or `MAP_ROOT` names another
repository. The examples are from [example/](../example/), a tagged shop.

## For the agent

### `brief <words>`

Where a task starts. The words are the task's, as the code names things; rarer words weigh more, a word in an
id counts three, in a purpose two, in a file name or a declared name one. The best three components in full, the
next ones a line each, then the tests that say it, the recipes the words match, and the first round of
questions as one `ask`.

```
$ python3 ../map.py brief cart discount coupon
brief cart discount coupon: 3 of 3 components that match, best first. ask <id or name> reads a block.

shop.cart  the cart: its lines, adding and removing articles, and what it holds  [src/shop/cart.py]
  parts: shop.cart.totals src/shop/cart.py:24-38 — the totals: each line's amount and discount, the coupon on the rest,…
         shop.cart.model src/shop/cart.py:1-21 — the cart: its lines, adding and removing articles, and what it holds
  declares (8): Cart, __init__, add, remove, is_empty, line_total, total, summary
  needs (imports): shop.prices; needed by: tests.cart
  tests (1): tests/test_cart.py
  docs: README.md, docs/CART.md
  changed 2026-10-16 3f2a1c0 the example
…
recipe new-discount: a new kind of discount, from the rule to the page and the tests (python3 ../map.py recipe new-discount)
Next, one call for the whole first round (add every other question to it): python3 ../map.py ask shop.prices.discounts shop.cart.totals web.cart.styles web.cart.render
End each change with: python3 ../map.py check
```

### `pack [recipe] <words>`

The start of a task in one call, for an agent handed a task: the recipe's steps when the first word names a recipe,
the brief of the other words, and then their first round already answered (the recipe's blocks and files, the
brief's first blocks), as `ask` answers it. The whole call keeps within the budget of `ask` (`limits.answer`, or
`--budget N`): what the round leaves out says to ask it in the next. `pack new-discount coupon` is the recipe, the
brief of `coupon` and the code of both; without a recipe, `pack cart total` is `brief cart total` with its round.

### `ask <question> [<question> …] [--in <paths>] [--all]`

The one way to read and locate. Every question of a round in one call, each under a `== question` heading:

| Question | Answered with |
|---|---|
| a block id: `shop.cart.totals` | its code; a long block with blocks inside it, their outline; a prefix (`shop.cart`), the blocks under it |
| an identifier: `total`, `render`, `#cart-total`, `.amount`, `data-price`, `--color-warn`, `MAX_ITEMS` | what declares it (its code when short, its start when long, the places when many) and every other line naming it, grouped by the block or section holding them |
| a name as grep would write it: `function render`, `total(`, `const SIZE=`, `a\|b` | the same as the identifier |
| a file: `src/shop/cart.py`, `docs/CART.md`, `map.json` | a short file whole; else its blocks with the names declared in each, a document's headings, a JSON file's keys, an untagged file's declarations |
| a folder: `src/shop` | its files with what each is, and its folders |
| lines: `src/shop/cart.py:5-8`; one line: `src/shop/cart.py:30` | those lines; the block or section holding that line, whole |
| a part: `docs/CART.md#discounts`, `data.json#key.subkey`, `src/x.js#legend` | the section, the key's value, the blocks whose id or purpose has the words |
| a glob: `'src/web/*.js'` | the files it names, with what each is |
| any text or regular expression: `'ten apples'`, `'coupon\|total'` | every line holding it, by block or section; past 120 lines, the places and how many lines each (`--all` prints them all) |

`--in src/web,docs` narrows the questions before it to those files, folders or globs (and only those: a second
`--in` starts over). Files over a megabyte are listed, never printed.

A call of several questions keeps within a budget of characters (`limits.answer` in `map.json`, 28,000 by default,
under the 30,000 Claude Code shows inline): while the answers run over it, the longest one keeps its places and leaves
its lines of code out, and says to ask it in a call of its own. `--budget N` sets it for one call (`0`: no budget). One
question is always answered whole.

`--literal` (or `-F`) asks for text exactly as written: no regular expression, and no reading of `fn x`, `x(` or
`a|b` as names; every question of the call is searched as plain text in the code and the docs (no file, block id or
glob lookup). Without it, text questions are regular expressions, as before.

`--json` (also on `brief` and `find`) prints one JSON document on stdout instead of the text. `ask --json`:
`{"questions": [{"question", "blocks": [{id, file, first, last, purpose}], "declarations": [{what, file, first, last}],
"files": [{file, lines, what}], "hits": [{file, line, text, block}], "found", "text"}]}`, where `text` is the question's
human answer (with the code). `brief --json`: `{words, matching, total, components: [{name, what, files, parts,
declares, needs, needed_by, tests, docs, changed}], also, tests_that_say_it, recipes, untagged_files, first_round,
check}`. `find --json`: `{declarations, blocks, more}`. Without the flag the text is unchanged. The four
implementations have both flags and give the same documents (`tests/conformance.py`).

### `find <words>`

The blocks whose id, purpose or file has every word (word starts count: `discount` finds `discounts`), best
first; an identifier among the words first says what declares it.

### `history <id or file>`

The commits that touched a block's lines (`git log -L`), latest first; for a file, its commits.

### `deps <id or file>`, `impact <id or file>`

What a file imports from the repository; what imports it, one step and one more, and the test files that reach
it (those that import it, import what imports it, or name it).

### `tests [paths | --changed]`

The test files that reach these files, or the files `git status` shows, each with why.

### `recipe [name]`

The recipes of `map.json`, or one of them: the steps of a change across layers, each at a block with its lines
now. `check` fails when a step names a block or a file that is gone.

### `plan <plan.md>`

A plan with `## Part <n>: …` sections, each with a `- Files:` line: which pairs of parts share no file and no
import, so two agents can build them at once.

## For the repository

### `build`

Writes `map.yaml` (the areas, with what each needs from the others read from imports; the files without code,
by folder; the files still untagged) and `map/<area>.yaml` (one line per component: what it is, its parts,
files, declarations, needs, needed by, tests by folder, docs). Never edit them: the next build overwrites them.

### `check`

What CI runs. The rules on every tagged file (a tag that cannot be read, an unknown area, a purpose under three
words, an id twice in a file, an `@end` closing nothing, too many lines outside blocks, a block too large), the
recipes' blocks, and that `map.yaml` and `map/` match the code. Exit 1 when anything is wrong. Untagged files are
counted, and fail only with `"strict": true` in `map.json`.

### `gaps [paths]`

The files without tags (with what each declares, to tag them), the files with too many lines outside blocks, the
blocks to split, and every problem, by file and line.

### `init`

The areas detected from the folders, `map.json` written with a `holds` to fill in for each, the next steps (with
the guard of the same implementation: `tools/map-guard install <agent>` beside `tools/map`), and the "Finding
code" section printed, to paste into `AGENTS.md`.

## The guard, the coach and the measurement

```
python3 tools/map-guard.py install <claude|codex|cursor|copilot|gemini>   the hook settings written for that agent
python3 tools/map-guard.py try 'grep -rn coupon src'                      what the guard would answer (or "goes ahead"), and the line Claude Code runs in its place
python3 tools/map-coach.py [--agent <agent>]                              the coach, a post-tool hook (agents/README.md)
python3 tools/map-sessions.py [--since 2026-10-01] [session prefix or .jsonl …]   how the sessions went (Claude Code's transcripts, their subagents' counted in them), with the `$` each cost (`+`: a model's price was unknown)
```

In Claude Code a shell line whose every step only reads is not refused: the guard runs it through the map in its place
(`permissionDecision: "allow"` with `updatedInput`), each read as its ask, every other step as it was written, from the
repository's root, and tells the agent so. The steps that may stay are the map's own commands, `echo`, `printf`, `true`,
`pwd`, `date` (a format, `-u`, `-I`), `wc`, `which`, `command -v`, `<command> --version`, git's read-only forms (`status`,
`log`, `diff`, `show`, `rev-parse`, `branch` listing; never `-c`, `--output`, `-C` outside the repository), counts
(`grep -c`, a read piped into `wc` or `grep -c`, kept as written), and filters that run no command (`head`, `tail`,
`cut`, `grep`, `sort`, `uniq`, `tr`, `column`, `sed -n 5,20p`), with `2>&1`, `2>/dev/null` and `&>/dev/null` on any of
them. A step that reads or writes outside the repository, or does more than read (`cargo`, `npm`, `git commit`, a
script), makes the line mixed.

A mixed line is refused whole, never allowed (an allow would skip Claude Code's own permission prompt for its other
steps), and the refusal gives the line to send again: "None of this command ran: send this line instead, its reads
already through the map. Run instead:" and the line, each read as its ask, every other step exactly as written, with the
same separators (`;`, `&&`, `||`, newlines, pipes); an ask after a `cd` runs from the root as `(cd <root> && …)`. The
other agents get the same line. That line goes ahead: the map's own commands beside other steps are no read. A line of
reads only that cannot run in place (a filter that could run a command) is refused with the asks, as before.

What the guard refuses, and what it lets through, in one table:

| Refused, with the ask that answers it | Goes ahead |
|---|---|
| `grep`, `rg`, `ag`, `ack`, `git grep` over the code or the docs | `grep -c`, `grep -q`, `grep -l`, a read piped into `wc` or `grep -c` (a count, a yes, file names) |
| `cat`, `sed -n`, `head`, `tail`, `awk`, `less`, `cut`, `sort`, `uniq`, `perl -ne` … on a mapped file (`cut -c1-9 file` is asked as `ask file \| cut -c1-9`) | `sed -i`, `perl -pi`, a redirection or `tee` into the repository, a script that writes the file back, and the reads in the same line that check that edit |
| `ls`, `find`, `tree` on the code's folders | `ls` of the root, `find -newer`, anything on ignored or generated files |
| `python3 -c`, `node -e`, a heredoc or a scratch script that opens a file only to print it | a script that computes over data (`.json`, `.yaml`) |
| the agent's own file-reading tool on a whole file; its grep and glob tools | a range of lines (before an edit); images; files outside the repository |
| | the map's own commands, tests, builds, pipes into `head`/`cut` (kept on the ask); `git status`, `which`, `--version` and the other read-only steps beside a read (the line runs in place) |
