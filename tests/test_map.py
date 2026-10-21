# @map tests.map.setup: the example copied to a scratch folder, the tool run there, and the checks of each command's answer
"""The map on the example project: build, check, ask, brief, find, recipe, deps, impact, tests, gaps, init.
Run: python3 -m unittest discover -s tests  (from the repository's root)."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
TOOL = REPO / 'python' / 'map.py'


def run(root, *args, env=None):
    t = time.perf_counter()
    r = subprocess.run(['python3', str(TOOL), '--root', str(root), *args], cwd=root, capture_output=True, text=True, env=env)
    return r.stdout + r.stderr, r.returncode, time.perf_counter() - t


class Example(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix='map-example-'))
        cls.root = cls.tmp / 'example'
        shutil.copytree(REPO / 'example', cls.root, ignore=shutil.ignore_patterns('map.yaml', 'map'))
        cfg = json.loads((cls.root / 'map.json').read_text())
        cfg['command'] = 'python3 ' + str(TOOL)
        (cls.root / 'map.json').write_text(json.dumps(cfg))
        subprocess.run(['git', 'init', '-q'], cwd=cls.root, check=True)
        subprocess.run(['git', 'add', '.'], cwd=cls.root, check=True)
        subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'the example'], cwd=cls.root, check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
# @end tests.map.setup

# @map tests.map.build: build writes the map, check passes, and the map says the areas, the components and what each needs
    def test_build_and_check(self):
        out, rc, _ = run(self.root, 'build')
        self.assertEqual(rc, 0, out)
        self.assertIn('12 blocks in 8 files, 6 components, 3 areas; 0 files without tags; 0 problems', out)
        central = (self.root / 'map.yaml').read_text()
        self.assertIn('shop: {holds: "the cart, the prices and the discounts", components: 2, files: 2, blocks: 4, map: map/shop.yaml, needs: {}, needed_by: {tests: 1}}', central)
        self.assertIn('tests: {holds: "the tests of the shop and of the page", components: 2, files: 2, blocks: 3, map: map/tests.yaml, needs: {shop: 1, web: 1}, needed_by: {}}', central)
        shop = (self.root / 'map' / 'shop.yaml').read_text()
        self.assertIn('shop.cart: {what: "the cart: its lines, adding and removing articles, and what it holds", parts: [model, totals], files: ["src/shop/cart.py"], declares: [Cart, __init__, add, remove, is_empty, line_total, total, summary], needs: [shop.prices], needed_by: [tests.cart], tests: {tests: 1}, docs: [README.md, docs/CART.md]}', shop)
        web = (self.root / 'map' / 'web.yaml').read_text()
        self.assertIn('files: ["src/web/cart.css", "src/web/cart.js", "src/web/index.html"]', web)     # one id, three files
        out, rc, _ = run(self.root, 'check')
        self.assertEqual(rc, 0, out)
        self.assertIn('12 blocks, 0 problems', out)
        self.assertEqual((self.root / 'map.yaml').read_text(), central)                               # check writes nothing

    def test_check_fails_on_a_stale_map_and_a_broken_tag(self):
        run(self.root, 'build')
        path = self.root / 'src' / 'shop' / 'prices.py'
        text = path.read_text()
        path.write_text(text.replace('# @map shop.prices.list: the price of each article, by its code, in cents',
                                     '# @map nowhere.prices.list: the price of each article, by its code, in cents'))
        try:
            out, rc, _ = run(self.root, 'check')
            self.assertEqual(rc, 1)
            self.assertIn('nowhere.prices.list: its first word is not an area', out)
            self.assertIn('out of date', out)
        finally:
            path.write_text(text)
        out, rc, _ = run(self.root, 'check')
        self.assertEqual(rc, 0, out)

    def test_a_rust_inner_attribute_is_not_a_shebang(self):
        rust = self.root / 'src' / 'shop' / 'lints.rs'
        script = self.root / 'src' / 'shop' / 'tool.py'
        rust.write_text('// @map shop.lints.allow: the lints the example allows, an inner attribute below the tag\n'
                        '#![allow(dead_code)]\nfn unused() {}\n')
        try:
            run(self.root, 'build')
            out, rc, _ = run(self.root, 'check')
            self.assertEqual(rc, 0, out)                                                              # #![ is no shebang
            script.write_text('# @map shop.tool.run: a script whose shebang line was pushed below its tag\n'
                              '#!/usr/bin/env python3\nprint(1)\n')
            run(self.root, 'build')
            out, rc, _ = run(self.root, 'check')
            self.assertEqual(rc, 1, out)
            self.assertIn('tool.py:2: the #! line must stay the first line', out)
            self.assertIn(', 1 problems', out)
        finally:
            rust.unlink(missing_ok=True)
            script.unlink(missing_ok=True)
            run(self.root, 'build')
        out, rc, _ = run(self.root, 'check')
        self.assertEqual(rc, 0, out)
# @end tests.map.build

# @map tests.map.ask: ask answers a round of questions in one call: a block, a name with its code, a file, a glob, a section, a folder, lines, text
    def test_ask_answers_each_kind_of_question_whole(self):
        out, rc, seconds = run(self.root, 'ask', 'shop.cart.totals', 'total', 'src/web/*.js', 'docs/CART.md#discounts', 'src/shop',
                               'src/shop/cart.py:5-8', 'coupon', '--in', 'src/web', 'function render', 'nothing-here-xyz')
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.count('\n== '), 8)
        self.assertLess(seconds, 2)
        self.assertRegex(out, r'== shop\.cart\.totals\n  src/shop/cart\.py:24-38  shop\.cart\.totals: the totals.*\n24\t# @map shop\.cart\.totals')
        self.assertRegex(out, r'== total\n  function total: src/shop/cart\.py:29-32  in shop\.cart\.totals\n29\tdef total\(cart\):')
        self.assertIn('named on 7 other lines', out)
        self.assertRegex(out, r'== src/web/\*\.js\n  src/web/\*\.js: 2 files\n    src/web/cart\.js  \(20 lines\)')
        self.assertRegex(out, r'== docs/CART\.md#discounts\n  docs/CART\.md:6-12  ## Discounts\n6\t## Discounts')
        self.assertRegex(out, r'== src/shop\n  src/shop: 2 files')
        self.assertRegex(out, r'== src/shop/cart\.py:5-8\n  src/shop/cart\.py:5-8  shop\.cart\.model\n5\t')
        self.assertRegex(out, r'== coupon\n  on \d+ lines\n  web\.cart\.styles  src/web/cart\.css:1-5')
        self.assertNotIn('src/shop/prices.py', out.split('== coupon')[1].split('== function')[0])      # --in narrows it
        self.assertRegex(out, r'== function render\n  the name render\n  function render: src/web/cart\.js:4-9')
        self.assertIn('== nothing-here-xyz\n  nothing in the code or the docs holds it', out)

    def test_a_file_without_tags_is_answered_with_its_declarations(self):
        extra = self.root / 'src' / 'shop' / 'orders.py'
        extra.write_text('import json\n\n\ndef place(cart):\n    return json.dumps(cart.lines)\n\n\nclass Order:\n    def __init__(self):\n        self.lines = []\n' * 20)
        try:
            run(self.root, 'build')
            out, rc, _ = run(self.root, 'ask', 'src/shop/orders.py')
            self.assertEqual(rc, 0, out)
            self.assertIn('no tags yet; what it declares', out)
            self.assertRegex(out, r'\n\s+4-5\s+function place')
            out, _, _ = run(self.root, 'gaps')
            self.assertIn('src/shop/orders.py: no tags', out)
            self.assertIn('1 of 9 files carry no tag', out)
            out, rc, _ = run(self.root, 'check')
            self.assertEqual(rc, 0, out)                                                            # not strict: the file is listed, not failed
            self.assertIn('1 files without tags', out)
            self.assertIn('untagged:\n  # code files that carry no tag yet, by folder (python3 ', (self.root / 'map.yaml').read_text())
        finally:
            extra.unlink()
            run(self.root, 'build')

    def test_ask_literal_searches_the_text_as_it_is(self):
        out, rc, _ = run(self.root, 'ask', '--literal', 'total(', 'a|b', 'function render', 'cart.lines')
        self.assertEqual(rc, 0, out)
        self.assertNotIn('the name', out)                                                           # `total(` and `function render` are not names
        self.assertRegex(out, r'== total\(\n  shop\.cart\.totals  src/shop/cart\.py:24-38')
        self.assertIn('== a|b\n  nothing in the code or the docs holds it', out)                    # not the alternation a or b
        self.assertIn('== function render\n  web.cart.render  src/web/cart.js:1-14', out)
        self.assertRegex(out, r'== cart\.lines\n  shop\.cart\.totals')
        self.assertNotIn('cartXlines', out)                                                         # the dot is a dot, not any character
        out, _, _ = run(self.root, 'ask', '-F', 'shop.cart.totals')
        self.assertIn('  docs/CART.md:1-16  # The cart', out)                                       # a block id is text too: the lines naming it
        self.assertNotIn('29\tdef total(cart):', out)                                                # not the block's code
        plain, _, _ = run(self.root, 'ask', 'shop.cart.totals')
        self.assertIn('29\tdef total(cart):', plain)                                                # without the flag, as before

    def test_ask_json_has_the_blocks_declarations_files_and_hits(self):
        out, rc, _ = run(self.root, 'ask', '--json', 'shop.cart.totals', 'total', 'src/web/*.js', 'coupon', '--in', 'src/web')
        self.assertEqual(rc, 0, out)
        doc = json.loads(out)
        first, name, glob, text = doc['questions']
        self.assertEqual(first['question'], 'shop.cart.totals')
        self.assertEqual(first['blocks'][0]['id'], 'shop.cart.totals')
        self.assertEqual((first['blocks'][0]['file'], first['blocks'][0]['first'], first['blocks'][0]['last']), ('src/shop/cart.py', 24, 38))
        self.assertIn('24\t# @map shop.cart.totals', first['text'])                                 # the human answer rides along
        self.assertEqual((name['declarations'][0]['file'], name['declarations'][0]['first']), ('src/shop/cart.py', 29))
        self.assertTrue(name['hits'] and all({'file', 'line', 'text', 'block'} <= set(h) for h in name['hits']))
        self.assertEqual([f['file'] for f in glob['files']], ['src/web/cart.js', 'src/web/format.js'])
        self.assertTrue(text['found'] and all(h['file'].startswith('src/web/') for h in text['hits']))     # --in narrows it
        self.assertEqual(json.loads(run(self.root, 'ask', '--json', 'nothing-here-xyz')[0])['questions'][0]['found'], False)

    def test_without_the_flags_the_text_is_the_same(self):
        for args in (('ask', 'shop.cart.totals', 'total', 'coupon'), ('brief', 'cart', 'coupon'), ('find', 'discount')):
            out, rc, _ = run(self.root, *args)
            self.assertEqual(rc, 0, out)
            self.assertFalse(out.lstrip().startswith('{"'), out)
# @end tests.map.ask

# @map tests.map.brief: brief ranks the components a task's words name and ends with the first round of questions; find, recipe, deps, impact, tests
    def test_brief(self):
        out, rc, seconds = run(self.root, 'brief', 'cart', 'discount', 'coupon')
        self.assertEqual(rc, 0, out)
        self.assertLess(seconds, 2)
        self.assertTrue(out.startswith('brief cart discount coupon: 3 of 3 components that match, best first.'))
        self.assertRegex(out, r'\nshop\.cart  the cart: its lines.*\n  parts: shop\.cart\.totals src/shop/cart\.py:24-38')
        self.assertIn('declares (8): Cart, __init__, add, remove, is_empty, line_total, total, summary', out)
        self.assertIn('needs (imports): shop.prices; needed by: tests.cart', out)
        self.assertIn('tests (1): tests/test_cart.py', out)
        self.assertIn('docs: README.md, docs/CART.md', out)
        self.assertIn('changed 20', out)                                                             # the commit of the scratch repository
        self.assertIn('recipe new-discount: a new kind of discount', out)
        self.assertRegex(out, r'Next, one call for the whole first round \(add every other question to it\): python3 \S+map\.py ask shop\.prices\.discounts')

    def test_brief_and_find_json(self):
        out, rc, _ = run(self.root, 'brief', '--json', 'cart', 'discount', 'coupon')
        self.assertEqual(rc, 0, out)
        doc = json.loads(out)
        self.assertEqual((doc['words'], doc['matching'], doc['total']), (['cart', 'discount', 'coupon'], 3, 3))
        cart = doc['components'][0]
        self.assertEqual(cart['name'], 'shop.cart')
        self.assertEqual(cart['parts'][0]['id'], 'shop.cart.totals')
        self.assertEqual((cart['parts'][0]['file'], cart['parts'][0]['first'], cart['parts'][0]['last']), ('src/shop/cart.py', 24, 38))
        self.assertEqual(cart['declares'][:3], ['Cart', '__init__', 'add'])
        self.assertEqual((cart['needs'], cart['needed_by'], cart['tests']), (['shop.prices'], ['tests.cart'], ['tests/test_cart.py']))
        self.assertIn('new-discount', [r['name'] for r in doc['recipes']])
        self.assertTrue(doc['first_round'][0].startswith('shop.'))
        out, rc, _ = run(self.root, 'find', '--json', 'discount')
        found = json.loads(out)
        self.assertEqual(found['blocks'][0]['id'], 'shop.prices.discounts')
        self.assertEqual((found['declarations'], found['more']), ([], 0))

    def test_find_recipe_deps_impact_tests(self):
        out, _, _ = run(self.root, 'find', 'discount')
        self.assertTrue(out.startswith('shop.prices.discounts                        src/shop/prices.py:16-30 (15 lines)'))
        out, _, _ = run(self.root, 'find', 'money')
        self.assertIn('money: function money, declared in web.format.money  src/web/format.js:2-4', out)
        out, _, _ = run(self.root, 'recipe', 'new-discount')
        self.assertIn('1. shop.prices.discounts  src/shop/prices.py:16-30\n   add the rule where the others are, with its name', out)
        out, _, _ = run(self.root, 'deps', 'src/shop/cart.py')
        self.assertIn('src/shop/cart.py imports 1 files of the repository:\n  src/shop/prices.py  shop.prices', out)
        out, _, _ = run(self.root, 'impact', 'shop.prices')
        self.assertIn('1 files import shop.prices directly:\n  src/shop/cart.py  shop.cart\n1 more import those: tests/test_cart.py', out)
        self.assertIn('Tests that reach it (1): tests/test_cart.py', out)
        out, _, _ = run(self.root, 'tests', 'src/shop/prices.py')
        self.assertIn('Run: tests/test_cart.py', out)
        out, _, _ = run(self.root, 'history', 'shop.cart.totals')
        self.assertIn('shop.cart.totals  src/shop/cart.py:24-38: 1 commits, latest first', out)
        out, _, _ = run(self.root, 'gaps')
        self.assertEqual(out.strip(), 'All 8 code files are tagged, no block to split, no problem.')

    def test_init_detects_the_areas_and_prints_the_section(self):
        root = self.tmp / 'fresh'
        shutil.copytree(self.root, root, ignore=shutil.ignore_patterns('map.json', 'map.yaml', 'map', '.git'))
        out, rc, _ = run(root, 'init')
        self.assertEqual(rc, 0, out)
        self.assertIn('map.json written: 3 areas detected', out)
        self.assertIn('Areas (code files each): web 4, shop 2, tests 2', out)
        self.assertIn('## Finding code', out)
        cfg = json.loads((root / 'map.json').read_text())
        self.assertEqual(sorted(cfg['holds']), ['shop', 'tests', 'web'])
        out, rc, _ = run(root, 'build')
        self.assertEqual(rc, 0, out)
        self.assertIn('12 blocks in 8 files', out)
# @end tests.map.brief


# @map tests.map.agents: the section agents/AGENTS.md carries, and this repository's own AGENTS.md, is the one init prints
class AgentsSection(unittest.TestCase):
    def section(self, cmd):
        text = (REPO / 'python' / 'map.py').read_text()
        start = text.index('AGENTS_SECTION = """') + len('AGENTS_SECTION = """')
        return text[start:text.index('"""', start)].format(cmd=cmd)

    def test_the_pasted_section_is_the_one_init_prints(self):
        self.assertIn(self.section('python3 tools/map.py'), (REPO / 'agents' / 'AGENTS.md').read_text())

    def test_this_repository_reads_itself_with_the_same_section(self):
        self.assertIn(self.section('python3 python/map.py'), (REPO / 'AGENTS.md').read_text())
# @end tests.map.agents


if __name__ == '__main__':
    unittest.main()
