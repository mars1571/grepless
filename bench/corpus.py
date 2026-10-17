#!/usr/bin/env python3
# @map bench.corpus: a synthetic tagged codebase of a chosen size, the same every time, to measure and compare the implementations on
"""A synthetic codebase to benchmark the map on: python3 bench/corpus.py <folder> [--files 400] [--seed 1].

Deterministic for a seed: areas under src/, files in Python, JavaScript, TypeScript, Go, Rust, CSS and HTML, each
with tagged blocks of realistic size, functions with names from a word list, imports between files of the same
language, test files that import and name the code, and docs that name components. About 400 files and 3,000
blocks by default, the scale of the codebase the map was measured on."""
import json
import os
import pathlib
import random
import sys

WORDS = ('cart price order invoice stock shelf basket coupon ledger payment refund receipt shipment route depot '
         'customer account session token policy quota limit window panel toolbar legend ruler layer page sheet row '
         'column cell formula chart axis series marker label style theme font glyph image thumbnail export import '
         'parser lexer writer reader cache index search query filter sort merge diff patch history version snapshot').split()
AREAS = ['shop', 'billing', 'catalog', 'ledger', 'editor', 'render', 'storage', 'sync']
LANGS = ['py', 'js', 'ts', 'go', 'rs', 'css', 'html']


def main():
    args = sys.argv[1:]
    root = pathlib.Path(args[0]).resolve()
    n_files = int(args[args.index('--files') + 1]) if '--files' in args else 400
    seed = int(args[args.index('--seed') + 1]) if '--seed' in args else 1
    rnd = random.Random(seed)
    root.mkdir(parents=True, exist_ok=True)
    files, blocks_total, by_lang = [], 0, {}
    per_area = max(1, round(n_files * 0.9 / len(AREAS)))
    for area in AREAS:
        for k in range(per_area):
            lang = rnd.choices(LANGS, weights=[30, 30, 12, 10, 8, 6, 4])[0]
            name = f'{rnd.choice(WORDS)}-{k}' if lang in ('js', 'ts', 'css', 'html') else f'{rnd.choice(WORDS)}_{k}'
            path = root / 'src' / area / f'{name}.{lang}'
            by_lang.setdefault(lang, []).append((area, path))
            files.append((area, path, lang))
    # imports: each file names one to three earlier files of its language and area
    texts = {}
    for area, path, lang in files:
        same = [p for a, p in by_lang[lang] if a == area and p != path and p in texts]
        targets = rnd.sample(same, min(len(same), rnd.randint(1, 3))) if same else []
        text, n = source(area, path, lang, targets, rnd, root)
        texts[path] = text
        blocks_total += n
    for path, text in texts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    # tests: one per ten files, importing or naming code
    tests = root / 'tests'
    tests.mkdir(exist_ok=True)
    code = [(a, p, lg) for a, p, lg in files if lg in ('py', 'js')]
    for i in range(max(1, n_files // 10)):
        area, target, lang = rnd.choice(code)
        rel = os.path.relpath(target, tests).replace(os.sep, '/')
        tid = target.stem.replace('_', '-')
        if lang == 'py':
            mod = str(target.relative_to(root / 'src')).replace('/', '.')[:-3]
            body = (f'# @map tests.{area}.{tid}: the {target.stem.replace("_", " ")} of {area} checked on real values\n'
                    f'import unittest\nfrom {mod} import run_{target.stem.split("_")[0]}\n\n\nclass T{i}(unittest.TestCase):\n'
                    f'    def test_runs(self):\n        self.assertIsNotNone(run_{target.stem.split("_")[0]}(1))\n# @end tests.{area}.{tid}\n')
            (tests / f'test_{area}_{i}.py').write_text(body, encoding='utf-8')
        else:
            body = (f'// @map tests.{area}.{tid}: the {target.stem.replace("-", " ")} of {area} checked on real values\n'
                    f"import assert from 'node:assert';\nimport {{ run }} from '{rel}';\nassert.ok(run(1));\n// @end tests.{area}.{tid}\n")
            (tests / f'{area}-{i}.test.js').write_text(body, encoding='utf-8')
    docs = root / 'docs'
    docs.mkdir(exist_ok=True)
    for area in AREAS:
        mine = [p for a, p, _ in files if a == area][:6]
        (docs / f'{area.upper()}.md').write_text(f'# {area}\n\nThe {area} area holds ' + ', '.join(f'`{area}.{p.stem.split("_")[0].split("-")[0]}`' for p in mine)
                                                 + f'.\n\n## Rules\n\nEvery {area} record is checked before it is written (`{area}.{mine[0].stem.split("_")[0].split("-")[0]}.validate`).\n', encoding='utf-8')
    (root / 'README.md').write_text(f'# corpus\n\nA synthetic codebase of {len(files)} files for benchmarking the map.\n', encoding='utf-8')
    (root / 'map.json').write_text(json.dumps({'command': 'python3 tools/map.py', 'name': 'corpus',
                                               'holds': {a: f'the {a} area of the synthetic codebase' for a in AREAS} | {'tests': 'the tests'}}, indent=2) + '\n', encoding='utf-8')
    print(f'{len(files)} code files, {blocks_total} blocks, {sum(len(t) for t in texts.values()) / 1e6:.1f} MB in {root}')


def source(area, path, lang, targets, rnd, root):
    """One file: its imports, then 3 to 12 tagged blocks of functions with bodies of a plausible size."""
    stem = path.stem
    topic = stem.split('_')[0].split('-')[0]
    n_blocks = rnd.randint(3, 12)
    out, total = [], 0
    if lang == 'py':
        imports = [f'from {str(t.relative_to(root / "src")).replace("/", ".")[:-3]} import run_{t.stem.split("_")[0]}' for t in targets]
        out.append(f'# @map {area}.{topic}.setup: the imports and the constants of {stem.replace("_", " ")}\n' + '\n'.join(['import json', 'import re'] + imports)
                   + f'\n\nLIMIT_{topic.upper()} = {rnd.randint(2, 99)}\n# @end {area}.{topic}.setup\n')
        for b in range(n_blocks):
            part = rnd.choice(WORDS)
            fn = f'run_{topic}' if b == 0 else f'{part}_{b}'
            body = '\n'.join(f'    x{i} = (x + {i}) * {rnd.randint(2, 9)}  # {rnd.choice(WORDS)} {rnd.choice(WORDS)}' for i in range(rnd.randint(4, 30)))
            out.append(f'\n\n# @map {area}.{topic}.{part}-{b}: the {part} of {topic}: {rnd.choice(WORDS)}, {rnd.choice(WORDS)} and {rnd.choice(WORDS)}\n'
                       f'def {fn}(x):\n    """{part} {rnd.choice(WORDS)}."""\n{body}\n    return x{rnd.randint(0, 3)} if x else None\n\n\nclass {part.capitalize()}{b}:\n'
                       f'    def read(self):\n        return LIMIT_{topic.upper()}\n# @end {area}.{topic}.{part}-{b}\n')
    elif lang in ('js', 'ts'):
        imports = [f"import {{ run }} from './{t.stem}.{t.suffix[1:]}';" if t.suffix == path.suffix else f"import {{ run }} from './{t.stem}.js';" for t in targets]
        out.append(f'// @map {area}.{topic}.setup: the imports and the constants of {stem.replace("-", " ")}\n' + '\n'.join(imports)
                   + f'\nconst LIMIT = {rnd.randint(2, 99)};\n// @end {area}.{topic}.setup\n')
        for b in range(n_blocks):
            part = rnd.choice(WORDS)
            fn = 'run' if b == 0 else f'{part}{b}'
            body = '\n'.join(f'  const x{i} = (x + {i}) * {rnd.randint(2, 9)}; // {rnd.choice(WORDS)} {rnd.choice(WORDS)}' for i in range(rnd.randint(4, 30)))
            typed = ': number' if lang == 'ts' else ''
            out.append(f'\n/* @map {area}.{topic}.{part}-{b}: the {part} of {topic}: {rnd.choice(WORDS)}, {rnd.choice(WORDS)} and {rnd.choice(WORDS)} */\n'
                       f'export function {fn}(x{typed}) {{\n{body}\n  return x{rnd.randint(0, 3)} > LIMIT;\n}}\n\nexport class {part.capitalize()}{b} {{\n  read() {{ return LIMIT; }}\n}}\n/* @end {area}.{topic}.{part}-{b} */\n')
    elif lang == 'go':
        out.append(f'// @map {area}.{topic}.setup: the package, its imports and the constants of {stem.replace("_", " ")}\npackage {area}\n\nimport (\n\t"fmt"\n\t"strings"\n)\n\nconst Limit{topic.capitalize()} = {rnd.randint(2, 99)}\n// @end {area}.{topic}.setup\n')
        for b in range(n_blocks):
            part = rnd.choice(WORDS)
            body = '\n'.join(f'\tx{i} := (x + {i}) * {rnd.randint(2, 9)} // {rnd.choice(WORDS)} {rnd.choice(WORDS)}' for i in range(rnd.randint(4, 30)))
            out.append(f'\n// @map {area}.{topic}.{part}-{b}: the {part} of {topic}: {rnd.choice(WORDS)}, {rnd.choice(WORDS)} and {rnd.choice(WORDS)}\n'
                       f'func {part.capitalize()}{b}(x int) int {{\n{body}\n\t_ = fmt.Sprint(strings.ToUpper("{part}"))\n\treturn x{rnd.randint(0, 3)}\n}}\n\ntype {part.capitalize()}{b}Type struct {{ Limit int }}\n// @end {area}.{topic}.{part}-{b}\n')
    elif lang == 'rs':
        out.append(f'// @map {area}.{topic}.setup: the uses and the constants of {stem.replace("_", " ")}\nuse std::collections::HashMap;\n\npub const LIMIT_{topic.upper()}: i64 = {rnd.randint(2, 99)};\n// @end {area}.{topic}.setup\n')
        for b in range(n_blocks):
            part = rnd.choice(WORDS)
            body = '\n'.join(f'    let x{i} = (x + {i}) * {rnd.randint(2, 9)}; // {rnd.choice(WORDS)} {rnd.choice(WORDS)}' for i in range(rnd.randint(4, 30)))
            out.append(f'\n// @map {area}.{topic}.{part}-{b}: the {part} of {topic}: {rnd.choice(WORDS)}, {rnd.choice(WORDS)} and {rnd.choice(WORDS)}\n'
                       f'pub fn {part}_{b}(x: i64) -> i64 {{\n{body}\n    let _m: HashMap<i64, i64> = HashMap::new();\n    x{rnd.randint(0, 3)}\n}}\n\npub struct {part.capitalize()}{b} {{ pub limit: i64 }}\n// @end {area}.{topic}.{part}-{b}\n')
    elif lang == 'css':
        for b in range(n_blocks):
            part = rnd.choice(WORDS)
            rules = '\n'.join(f'.{topic}-{part}-{i} {{ margin: {i}px; color: #{rnd.randint(0, 0xffffff):06x}; }}' for i in range(rnd.randint(3, 20)))
            out.append(f'/* @map {area}.{topic}.{part}-{b}: the styles of the {part} of {topic}: {rnd.choice(WORDS)} and {rnd.choice(WORDS)} */\n{rules}\n/* @end {area}.{topic}.{part}-{b} */\n\n')
    else:
        out.append(f'<!doctype html>\n<html><head><link rel="stylesheet" href="{topic}.css"></head><body>\n')
        for b in range(n_blocks):
            part = rnd.choice(WORDS)
            items = '\n'.join(f'  <li id="{topic}-{part}-{i}">{rnd.choice(WORDS)}</li>' for i in range(rnd.randint(3, 20)))
            out.append(f'<!-- @map {area}.{topic}.{part}-{b}: the markup of the {part} of {topic}: {rnd.choice(WORDS)} and {rnd.choice(WORDS)} -->\n<ul>\n{items}\n</ul>\n<!-- @end {area}.{topic}.{part}-{b} -->\n')
        out.append('</body></html>\n')
    text = ''.join(out)
    return text, n_blocks + (1 if lang in ('py', 'js', 'ts', 'go', 'rs') else 0)


if __name__ == '__main__':
    main()
# @end bench.corpus
