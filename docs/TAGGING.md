# Tagging a codebase

## The tag

A tag sits alone on the line above its block, in the file's own comment form:

```python
# @map shop.prices.discounts: the discount rules: a percentage past a quantity, and a coupon on the whole cart
BULK = {'apple': (10, 15)}

def line_discount(code, quantity):
    ...
# @end shop.prices.discounts
```

```js
/* @map web.cart.render: the cart drawn on the page: one row per line, the total, and the coupon field */
// @map web.cart.events: what the page does on a click: the coupon applied, the cart drawn again   (// works too)
```

```html
<!-- @map web.cart.markup: the cart's table, its total line and the coupon field with its button -->
```

```sql
-- @map db.orders.schema: the orders table and its indexes, one row per line of a cart
```

- **The id** is `<area>.<topic>.<part>`, lowercase words and digits with hyphens, at least two words. The first word
  is the area: the folder under `src/` (or `lib/`, `app/`, `packages/` …), else the top folder, else what
  `map.json` says ([CONFIG.md](CONFIG.md)); a block that belongs to another area may take that area's id. The
  first two words name the **component** (`shop.cart`), the third its **part** (`shop.cart.totals`).
- **The purpose**, after the colon: three words or more, saying what the block is for in the words a task would
  use. Name the things it handles ("the coupon", "the total", "the page's events"), not the mechanism.
- **A block ends** at `@end <id>` when other code follows it in the same file, else where the next block outside it
  starts, or the file ends. Blocks nest by id: `shop.cart.totals.rounding` inside `shop.cart.totals`.
- **One id may tag a piece in several files**: `web.cart.styles` in the CSS, `web.cart.render` in the script,
  `web.cart.markup` in the HTML make one component, `web.cart`, that `brief` shows with its three files.
- **Sizes**: a block holds at most 16,000 characters of its own code (about 4,000 tokens: readable in one answer);
  split a larger one with blocks inside it. A tagged file may have at most 30 non-blank lines outside any block
  (imports, constants). `python3 tools/map.py gaps` lists what breaks these, and `check` fails on them.
- **A shebang** stays the first line; the tag goes below it.

Tags never reach a build: a build that strips tag lines (`map.py` has `strip(text, path)` for that) produces a
byte-identical output, which is how the first tagged codebase proved tagging changed nothing.

## Tagging an existing codebase with an agent

Tag a few files by hand first, so the agent has your own tags as the pattern. Then one folder at a time:

1. `python3 tools/map.py gaps src/<folder>` says which files carry no tag, how many lines each has and what it
   declares.
2. Give the agent the prompt below with the folder. One agent per folder; two agents on separate folders at once
   work fine (they share no file).
3. `python3 tools/map.py build`, then `python3 tools/map.py check`: a tag that cannot be read, an id with an
   unknown area, a purpose too short, a block too large or an id used twice in a file is a line of output with the
   file and the line.
4. Read `map/<area>.yaml`: one line per component. A component whose "what" says nothing ("helpers", "utils",
   "misc") is a tag to rewrite.

The prompt (paste it, with the folder):

> Tag every code file in `src/<folder>` for the code map (read `docs/TAGGING.md` first, and `python3 tools/map.py
> gaps src/<folder>` for what is left). Put a tag on the line above each block of code that a person would look
> for as one thing: a model, a class, a group of related functions, a screen, a command, its styles, its markup.
> The id is `<area>.<topic>.<part>`; the area is `<area>`. The purpose says what the block is for in the words a
> task would use, three words or more; name the things it handles, not the mechanism. Nest blocks inside a large
> one so that no block holds more than 16,000 characters of its own; at most 30 non-blank lines may stay outside
> any block. Close a block with `@end <id>` when other code follows it in the file. Change nothing but comment
> lines. When the folder is tagged, run `python3 tools/map.py build` and `python3 tools/map.py check` and fix what
> they report.

In the first codebase, 1,710 blocks in 170 files were tagged this way in a day: nine files by hand as the pilot, the rest by
twelve agents on separate files at once, then seventeen ids renamed so a piece's script, styles and markup
shared one id.

## Keeping it true

- **Tag what you add or move.** The instructions for agents say so; `check` in CI fails on an untagged file in
  strict mode (`"strict": true` in `map.json`, once everything is tagged) and on every broken tag always.
- **Keep purposes true.** A purpose that no longer says what the block does is worse than none: the agent trusts
  it. When a change alters what a block is for, change its purpose in the same change.
- **Recipes cannot rot.** A recipe in `map.json` names the blocks a kind of change touches; `check` fails when one
  of them is gone, so a recipe is corrected when the code moves ([CONFIG.md](CONFIG.md)).
- **Files without code are described, not tagged**: generated files, assets, data, vendored code, in `map.json`'s
  `describe` and `ignore`. The map lists them under `other:` so an agent knows they exist and what they are.

## What to tag, what not to

Tag what someone will look for: features, screens, models, commands, the parts of a protocol, a test file's
scenarios. Do not tag line by line; a block of forty lines with a purpose beats four blocks of ten. Do not tag
generated code (describe it), vendored code (ignore it) or a lock file (it is data, listed under `other:`).
Tests are tagged like the code (`tests.cart.discounts: the bulk discount past the quantity, and the coupon on
the whole cart`): `brief` then shows the tests that say what a component does.
