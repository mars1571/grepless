#!/usr/bin/env python3
# @map tests.conformance.cases: every implementation of the map run on the example project and compared with the golden answers of the reference
"""The conformance suite: the same commands, on the same example project, must print the same answers in every
language. The Python implementation is the reference; its answers are the golden files in tests/golden/.

    python3 tests/conformance.py --record                       write the golden files with the reference (python3 map.py)
    python3 tests/conformance.py                                check the reference against them
    python3 tests/conformance.py --impl 'node node/map.mjs' --guard 'node node/map-guard.mjs'
    python3 tests/conformance.py --impl go/bin/map --guard go/bin/map-guard
    python3 tests/conformance.py --impl rust/target/release/map --guard rust/target/release/map-guard

Lines that depend on the machine (a commit hash, a date, a path) are masked before comparing."""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
GOLDEN = HERE / 'golden'
QUESTIONS = ['shop.cart.totals', 'total', 'src/web/*.js', 'docs/CART.md#discounts', 'src/shop', 'src/shop/cart.py:5-8',
             'coupon', '--in', 'src/web', 'function render', 'nothing-here-xyz', 'map.json#holds.shop', 'web.cart',
             'src/shop/cart.py:30', '#cart-total', 'money', 'readCoupon(', 'ten apples', 'src/web/cart.css']
CASES = [
    ('build', ['build']), ('check', ['check']), ('ask', ['ask'] + QUESTIONS), ('ask-all', ['ask', 'coupon', '--all']),
    ('find', ['find', 'discount']), ('find-name', ['find', 'money']), ('find-none', ['find', 'zzz-nothing']),
    ('where', ['where', 'shop.cart']), ('deps', ['deps', 'src/shop/cart.py']), ('impact', ['impact', 'shop.prices']),
    ('impact-file', ['impact', 'src/web/format.js']), ('tests', ['tests', 'src/shop/prices.py', 'src/web/format.js']),
    ('recipe-list', ['recipe']), ('recipe', ['recipe', 'new-discount']), ('gaps', ['gaps']), ('brief', ['brief', 'cart', 'discount', 'coupon']),
    ('brief-web', ['brief', 'page', 'money', 'format']), ('history', ['history', 'shop.cart.totals']), ('plan', ['plan', 'plan.md']),
    ('help', ['help']), ('version', ['version']),
]
GUARD_CASES = [
    ('claude-grep', None, {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': 'grep -rn coupon src 2>/dev/null | head -3'}}),
    ('claude-sed', None, {'tool_name': 'Bash', 'tool_input': {'command': 'sed -n 20,40p src/shop/cart.py | cut -c1-80'}}),
    ('claude-find-xargs', None, {'tool_name': 'Bash', 'tool_input': {'command': 'find src -name "*.js" | xargs grep -n money'}}),
    ('claude-script', None, {'tool_name': 'Bash', 'tool_input': {'command': "python3 -c \"print(open('src/shop/cart.py').read())\""}}),
    ('claude-heredoc', None, {'tool_name': 'Bash', 'tool_input': {'command': "cat > /tmp/peek-conf.py <<'EOF'\nt = open('src/shop/prices.py').read()\nprint(t[:500])\nEOF"}}),
    ('claude-allowed', None, {'tool_name': 'Bash', 'tool_input': {'command': 'grep -c coupon src/shop/cart.py && python3 -m unittest'}}),
    ('claude-read', None, {'tool_name': 'Read', 'tool_input': {'file_path': '{root}/src/shop/cart.py'}}),
    ('claude-read-range', None, {'tool_name': 'Read', 'tool_input': {'file_path': '{root}/src/shop/cart.py', 'offset': 10, 'limit': 20}}),
    ('claude-grep-tool', None, {'tool_name': 'Grep', 'tool_input': {'pattern': 'coupon', 'path': 'src', '-i': True}}),
    ('claude-glob', None, {'tool_name': 'Glob', 'tool_input': {'pattern': '**/*.js', 'path': 'src'}}),
    ('codex', 'codex', {'hook_event_name': 'PreToolUse', 'turn_id': 't', 'tool_name': 'Bash', 'tool_input': {'command': 'cat src/shop/prices.py'}}),
    ('cursor-shell', None, {'command': 'rg coupon src', 'cwd': '{root}', 'sandbox': False, 'cursor_version': '1.0'}),
    ('cursor-read', None, {'file_path': '{root}/docs/CART.md', 'content': '…', 'attachments': [], 'cursor_version': '1.0'}),
    ('cursor-pretool', 'cursor', {'tool_name': 'Shell', 'tool_input': {'command': 'head -40 src/web/cart.js', 'working_directory': '{root}'}}),
    ('copilot-cli', None, {'sessionId': 's', 'toolName': 'bash', 'toolArgs': '{"command": "grep -rn money src/web"}'}),
    ('copilot-vscode', None, {'hook_event_name': 'PreToolUse', 'tool_name': 'bash', 'tool_input': {'command': 'cat src/web/format.js'}}),
    ('copilot-view', 'copilot', {'toolName': 'view', 'toolArgs': '{"path": "{root}/src/web/cart.js"}'}),
    ('gemini-shell', None, {'hook_event_name': 'BeforeTool', 'tool_name': 'run_shell_command', 'tool_input': {'command': 'grep -rn coupon src'}}),
    ('gemini-read', None, {'hook_event_name': 'BeforeTool', 'tool_name': 'read_file', 'tool_input': {'absolute_path': '{root}/src/shop/cart.py'}}),
    ('gemini-allowed', None, {'hook_event_name': 'BeforeTool', 'tool_name': 'run_shell_command', 'tool_input': {'command': 'python3 -m unittest'}}),
    ('garbage', None, 'not json'),
]
PLAN = """# A plan

## Part 1: the rule
- Files: src/shop/prices.py docs/CART.md

## Part 2: the page
- Files: src/web/cart.js src/web/cart.css

## Part 3: the totals
- Files: src/shop/cart.py
"""


def mask(text, root):
    text = text.replace(str(root), '<root>')
    text = re.sub(r'changed \d{4}-\d{2}-\d{2} [0-9a-f]{7} ', 'changed <date> <hash> ', text)
    text = re.sub(r'^  [0-9a-f]{7} \d{4}-\d{2}-\d{2} ', '  <hash> <date> ', text, flags=re.M)
    text = re.sub(r'python3 \S*map\.py', '<map>', text)
    return text


def setup(tmp):
    root = tmp / 'example'
    shutil.copytree(REPO / 'example', root, ignore=shutil.ignore_patterns('map.yaml', 'map', '.git'))
    cfg = json.loads((root / 'map.json').read_text())
    cfg['command'] = 'python3 tools/map.py'
    (root / 'map.json').write_text(json.dumps(cfg, indent=2) + '\n')
    (root / 'plan.md').write_text(PLAN)
    env = {**os.environ, 'GIT_AUTHOR_DATE': '2026-10-16T12:00:00Z', 'GIT_COMMITTER_DATE': '2026-10-16T12:00:00Z'}
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    subprocess.run(['git', 'add', '.'], cwd=root, check=True)
    subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'the example'], cwd=root, check=True, env=env)
    return root


def run(impl, root, args, stdin=None, extra=None):
    cmd = impl.split() + list(args)
    r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, input=stdin, env={**os.environ, **(extra or {})})
    return (r.stdout + ('' if not r.stderr.strip() else '\n[stderr]\n' + r.stderr), r.returncode)


def answers(impl, guard, root):
    out = {}
    for name, args in CASES:
        text, rc = run(impl, root, ['--root', str(root)] + args)
        text = mask(text, root)
        if name == 'build':
            text += '\n[map.yaml]\n' + (root / 'map.yaml').read_text() + ''.join(
                f'\n[{p.name}]\n' + p.read_text() for p in sorted((root / 'map').glob('*.yaml')))
        out[name] = f'rc={rc}\n{text}'
    extra = root / 'src' / 'shop' / 'orders.py'
    extra.write_text('import json\n\n\ndef place(cart):\n    return json.dumps(cart.lines)\n\n\nclass Order:\n    def __init__(self):\n        self.lines = []\n' * 20)
    for name, args in (('untagged-ask', ['ask', 'src/shop/orders.py', 'place']), ('untagged-gaps', ['gaps']), ('untagged-check', ['check'])):
        text, rc = run(impl, root, ['--root', str(root)] + args)
        out[name] = f'rc={rc}\n{mask(text, root)}'
    extra.unlink()
    run(impl, root, ['--root', str(root), 'build'])
    if guard:
        for name, agent, data in GUARD_CASES:
            payload = data if isinstance(data, str) else json.dumps(data).replace('{root}', str(root))
            text, rc = run(guard, root, (['--agent', agent] if agent else []), stdin=payload, extra={'MAP_ROOT': str(root)})
            try:
                parsed = json.loads(text)
                text = json.dumps(parsed, sort_keys=True, indent=1)
            except ValueError:
                pass
            out['guard-' + name] = f'rc={rc}\n{mask(text, root)}'
        text, rc = run(guard, root, ['try', 'ls src/web'], extra={'MAP_ROOT': str(root)})
        out['guard-try'] = f'rc={rc}\n{mask(text, root)}'
    return out


def main(argv):
    impl = argv[argv.index('--impl') + 1] if '--impl' in argv else f'python3 {REPO / "python" / "map.py"}'
    guard = argv[argv.index('--guard') + 1] if '--guard' in argv else (f'python3 {REPO / "python" / "map-guard.py"}' if '--impl' not in argv else None)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='map-conformance-'))
    try:
        root = setup(tmp)
        got = answers(impl, guard, root)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if '--record' in argv:
        GOLDEN.mkdir(exist_ok=True)
        for old in GOLDEN.glob('*.txt'):
            old.unlink()
        for name, text in got.items():
            (GOLDEN / f'{name}.txt').write_text(text)
        print(f'{len(got)} golden answers written to {GOLDEN.relative_to(REPO)}')
        return 0
    failed = 0
    for name, text in got.items():
        want = (GOLDEN / f'{name}.txt').read_text() if (GOLDEN / f'{name}.txt').exists() else None
        if want is None:
            print(f'{name}: no golden file (python3 tests/conformance.py --record)')
            failed += 1
        elif want != text:
            failed += 1
            print(f'{name}: differs')
            if '-v' in argv:
                import difflib
                sys.stdout.writelines(difflib.unified_diff(want.splitlines(True), text.splitlines(True), 'golden', impl, n=1))
        else:
            print(f'{name}: ok')
    print(f'{len(got) - failed} of {len(got)} answers match {impl}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
# @end tests.conformance.cases
