# map.json

Optional, at the repository's root; `python3 tools/map.py init` writes one with the areas it detects. Every
setting has a default; an unknown setting is refused with the list of the known ones.

```json
{
  "command": "python3 tools/map.py",
  "name": "my project",
  "roots": ["src", "lib", "app", "packages"],
  "areas": {"tools": "build", ".github": "ci", ".": "root", "src/legacy/": "legacy"},
  "holds": {"shop": "the cart, the prices and the discounts", "web": "the page that shows the cart"},
  "describe": [["*.min.js", "generated", "a bundle, never read whole"], ["assets/*.png", "asset", "a picture"]],
  "ignore": ["dist/", "vendor/"],
  "forms": {".kt": "slash", ".nim": "hash"},
  "limits": {"untagged": 30, "block": 16000, "answer": 28000},
  "tests": ["tests/**", "**/*.spec.ts"],
  "recipes": {"new-discount": {"about": "…", "words": "discount rule coupon", "steps": [["shop.prices.discounts", "add the rule"], ["docs/CART.md", "describe it"]]}},
  "strict": false,
  "guard": {"skip": ["tests/fixtures/"]}
}
```

| Setting | Default | What it does |
|---|---|---|
| `command` | `python3 tools/map.py` | how agents run the tool, as the map's answers, `init` and the guard's refusals say it |
| `name` | the root folder's name | the project's name in `map.yaml`'s first line |
| `roots` | `src lib app apps packages pkg internal cmd services` | a file under one of these takes its next folder as its area (`src/shop/cart.py` → `shop`); a file directly under a root takes the root's name |
| `areas` | `{}` | a path prefix (a folder or a file) → its area, before the rule above; the longest prefix wins; `"."` is the files at the root (`root` by default). Area names are lowercase words and digits with hyphens |
| `holds` | `{}` | an area → one line saying what it holds, printed in `map.yaml` and `map/<area>.yaml`; `init` writes an empty one per area |
| `describe` | `[]` | files without code to read, each `[pattern, kind, about]`: a code file that matches is listed under `other:` in `map.yaml` with its kind and description instead of being expected to carry tags (generated code, bundles, fixtures kept as they were) |
| `ignore` | `[]` | paths left out of the map altogether, besides `.gitignore` and the usual folders (`node_modules`, `dist`, `build`, `target`, `vendor`, `.venv` …): folders (`dist/`), files or globs. `install.sh` puts the tool's own copies here (`tools/map.py` … or `tools/map.mjs` …): they are its code, not the repository's |
| `forms` | `{}` | the comment form of an extension the table in `map.py` lacks: `slash` (`/* */`, `//`), `hash` (`#`), `html` (`<!-- -->`), `dash` (`--`), `semicolon` (`;`), `percent` (`%`); `null` for an extension that must carry no tags |
| `limits` | `{"untagged": 30, "block": 16000, "answer": 28000}` | non-blank lines a tagged file may have outside any block; characters of its own code a block may hold; characters one `ask` of several questions prints before its longest answers leave their code out (Claude Code shows about 30,000 inline and files the rest away; `ask --budget N` sets it for one call, `0` for none) |
| `tests` | `[]` | globs of test files, besides the usual names (`tests/`, `test/`, `spec/`, `__tests__/`, `test_*.py`, `*_test.go`, `*.test.js`, `*.spec.ts`, `*Test.java`, `*_spec.rb` …) |
| `recipes` | `{}` | the steps of a kind of change across layers, by name: `about` (one line), `words` (the task words that match it, two or more match), `checked` (the change it was checked against, optional), `steps` (a list of `[block id or file, what to do there]`), `note` (optional). `check` fails when a step names a block or a file that is gone |
| `strict` | `false` | `check` also fails on code files that carry no tag yet: for CI, once everything is tagged |
| `guard.skip` | `[]` | paths the guard leaves alone besides `ignore`: fixtures an agent may `cat`, data folders |

## Areas, from folders

Without `areas`, a file's area is: the folder under a root (`src/shop/x.py` → `shop`), else the top folder
(`tools/x.py` → `tools`, `.github/…` → `github`), else `root` for a file at the root. Every area a tag names must
be one of these, or one named in `areas` or `holds`; a block that belongs to another area may take that area's
id (a repository can keep `.claude/hooks/*.py` under the area `ci` with `"areas": {".claude": "ci", ".github": "ci"}`).

## The comment forms

| Form | Extensions (the built-in table) |
|---|---|
| `slash` | .js .mjs .cjs .jsx .ts .tsx .mts .cts .java .kt .kts .scala .groovy .go .rs .swift .c .h .cc .cpp .cxx .hpp .hh .cs .m .mm .php .dart .css .scss .less .proto .zig .d .v |
| `hash` | .py .pyi .rb .rake .sh .bash .zsh .fish .pl .pm .r .R .yml .yaml .toml .ps1 .ex .exs .nim .jl .cmake .tf .nix .cr .coffee .mk; Makefile, Dockerfile, Rakefile, Gemfile, Justfile, Vagrantfile, CMakeLists.txt; a file without extension whose first line is `#!` |
| `html` | .html .htm .xml .vue .svelte .astro .xhtml (also accepts `/* */` and `//` inside scripts and styles) |
| `dash` | .sql .lua .hs .elm .ada .vhd |
| `semicolon` | .clj .cljs .cljc .edn .el .lisp .scm .rkt |
| `percent` | .erl .hrl .tex |

Files `ask` reads but that carry no tags: `.md .markdown .rst .txt .adoc .json .ini .cfg .csv`. Declarations
(for `ask <name>`, the outlines and `brief`) are read from Python with its own parser and from JavaScript,
TypeScript, Go, Rust, Java, Kotlin, Scala, C#, Swift, Ruby, PHP, C, C++, shell, Elixir, Lua, SQL and Perl by
their shape; imports (for `deps`, `impact`, `tests` and the areas' `needs`) from Python, JavaScript and
TypeScript, Go, Rust, Java and C#, Ruby, PHP, C, shell, CSS and HTML. Another language still gets tags, blocks,
`ask` by block and by text, `brief` and `find`; it only lacks declared names and imports.
