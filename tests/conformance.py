#!/usr/bin/env python3
# @map tests.conformance.cases: every implementation of the map run on the example project and compared with the golden answers of the reference
"""The conformance suite: the same commands, on the same example project, must print the same answers in every
language. The Python implementation is the reference; its answers are the golden files in tests/golden/.

    python3 tests/conformance.py --record                       write the golden files with the reference (python3 map.py)
    python3 tests/conformance.py                                check the reference against them
    python3 tests/conformance.py --impl 'node node/map.mjs' --guard 'node node/map-guard.mjs'
    python3 tests/conformance.py --impl go/bin/map --guard go/bin/map-guard
    python3 tests/conformance.py --impl rust/target/release/map --guard rust/target/release/map-guard

With --guard, the hook runs on each agent's events, and the coach and the sessions beside it (map-coach and
map-sessions in the guard's folder, or --coach and --sessions) run on fixed events and on two synthetic transcripts.
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
    ('ask-budget', ['ask', 'shop.cart.totals', 'src/web/cart.js', 'total', '--budget', '1500']),
    ('pack', ['pack', 'new-discount', 'coupon', '--budget', '6000']), ('pack-words', ['pack', 'cart', 'total']),
    ('pack-none', ['pack', 'zzz-nothing']),
    ('find', ['find', 'discount']), ('find-name', ['find', 'money']), ('find-none', ['find', 'zzz-nothing']),
    ('where', ['where', 'shop.cart']), ('deps', ['deps', 'src/shop/cart.py']), ('impact', ['impact', 'shop.prices']),
    ('impact-file', ['impact', 'src/web/format.js']), ('tests', ['tests', 'src/shop/prices.py', 'src/web/format.js']),
    ('recipe-list', ['recipe']), ('recipe', ['recipe', 'new-discount']), ('gaps', ['gaps']), ('brief', ['brief', 'cart', 'discount', 'coupon']),
    ('brief-web', ['brief', 'page', 'money', 'format']), ('history', ['history', 'shop.cart.totals']), ('plan', ['plan', 'plan.md']),
    ('ask-json', ['ask', '--json', 'shop.cart.totals', 'total', 'src/web/*.js', 'src/shop/cart.py:5-8', 'coupon', '--in', 'src/web']),
    ('ask-literal', ['ask', '--literal', 'total(', 'function render', 'a|b', 'cart.lines']), ('ask-literal-flag', ['ask', '-F', 'shop.cart.totals']),
    ('ask-literal-json', ['ask', '--json', '-F', 'def total(']), ('brief-json', ['brief', '--json', 'cart', 'discount', 'coupon']),
    ('find-json', ['find', '--json', 'discount']), ('find-name-json', ['find', '--json', 'money']),
    ('help', ['help']), ('version', ['version']),
]
GUARD_CASES = [
    ('claude-grep', None, {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': 'grep -rn coupon src 2>/dev/null | head -3'}}),
    ('claude-sed', None, {'tool_name': 'Bash', 'tool_input': {'command': 'sed -n 20,40p src/shop/cart.py | cut -c1-80'}}),
    ('claude-find-xargs', None, {'tool_name': 'Bash', 'tool_input': {'command': 'find src -name "*.js" | xargs grep -n money'}}),
    ('claude-script', None, {'tool_name': 'Bash', 'tool_input': {'command': "python3 -c \"print(open('src/shop/cart.py').read())\""}}),
    ('claude-heredoc', None, {'tool_name': 'Bash', 'tool_input': {'command': "cat > /tmp/peek-conf.py <<'EOF'\nt = open('src/shop/prices.py').read()\nprint(t[:500])\nEOF"}}),
    ('claude-allowed', None, {'tool_name': 'Bash', 'tool_input': {'command': 'grep -c coupon src/shop/cart.py && python3 -m unittest'}}),
    ('claude-mixed', None, {'tool_name': 'Bash', 'tool_input': {'command': 'sed -n 1,5p src/shop/cart.py; python3 -m unittest'}}),
    ('claude-mixed-line', None, {'tool_name': 'Bash', 'tool_input': {'command': 'grep -rn coupon src 2>&1 | head -3; cargo test -p shop && sed -n 1,5p src/shop/cart.py'}}),
    ('claude-outside', None, {'tool_name': 'Bash', 'tool_input': {'command': 'cat docs/CART.md; ls /tmp'}}),
    ('claude-readonly', None, {'tool_name': 'Bash', 'tool_input': {'command': 'git status --short | head -3; which python3; sed -n 1,5p src/shop/cart.py; pwd'}}),
    ('claude-forms', None, {'tool_name': 'Bash', 'tool_input': {'command': 'cut -c1-20 src/shop/cart.py 2>&1; grep -rn coupon src | sed -n 1,3p'}}),
    ('claude-count-grep', None, {'tool_name': 'Bash', 'tool_input': {'command': 'grep -rn coupon src | grep -ic money'}}),
    ('codex-mixed-line', 'codex', {'hook_event_name': 'PreToolUse', 'turn_id': 't', 'tool_name': 'Bash', 'tool_input': {'command': 'cd src && cat shop/cart.py; npm test'}}),
    ('claude-edit-check', None, {'tool_name': 'Bash', 'tool_input': {'command': "sed -i 's/TEN/10/' src/shop/prices.py && grep -n TEN src/shop/prices.py"}}),
    ('claude-count', None, {'tool_name': 'Bash', 'tool_input': {'command': 'grep -rn coupon src | wc -l'}}),
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
# @end tests.conformance.cases


# @map tests.conformance.hooks: each agent's events, as its hook settings send them: the reads the guard refuses and the work it lets through, the coach's reminder, the sessions measured
SHELL_DEMO = [   # what the guard refuses on the code, then what it lets through
    ('grep', 'grep -rn coupon src'), ('cat', 'cat src/shop/prices.py'), ('sed', 'sed -n 1,20p src/web/cart.js'),
    ('count', 'grep -c coupon src/shop/cart.py && wc -l src/web/*.js'), ('edit', "sed -i 's/TEN/10/' src/shop/prices.py"),
    ('tests', 'python3 -m unittest discover -s tests'), ('not code', 'cat LICENSE /tmp/map-demo.log'),
    ('reads', 'ls src/web; tail -3 src/shop/prices.py | cut -c1-20'), ('mixed', 'grep -rn coupon src; python3 -m unittest'),
    ('check an edit', "sed -i 's/TEN/10/' src/shop/prices.py && tail -3 src/shop/prices.py"), ('count lines', 'grep -rn coupon src | wc -l'),
    ('mixed line', 'git status -s; grep -rn coupon src 2>/dev/null | head -3; cargo test'), ('read-only steps', 'which python3; sed -n 1,5p src/shop/cart.py; pwd'),
    ('count with grep', 'grep -rn coupon src | grep -ic money'), ('cut a file', 'cut -c1-20 src/shop/cart.py'),
]
SHELL = {   # each agent's shell event, with the flag its settings give the guard (agents/README.md)
    'claude': (None, lambda c: {'hook_event_name': 'PreToolUse', 'session_id': 's', 'cwd': '{root}', 'tool_name': 'Bash', 'tool_input': {'command': c}}),
    'codex': ('codex', lambda c: {'hook_event_name': 'PreToolUse', 'session_id': 's', 'turn_id': 't', 'cwd': '{root}', 'tool_name': 'Bash', 'tool_input': {'command': c}}),
    'cursor': ('cursor', lambda c: {'hook_event_name': 'beforeShellExecution', 'conversation_id': 'c', 'cursor_version': '1.7', 'workspace_roots': ['{root}'], 'command': c, 'cwd': '{root}', 'sandbox': False}),
    'copilot': ('copilot', lambda c: {'sessionId': 's', 'timestamp': 1792141200000, 'cwd': '{root}', 'toolName': 'bash', 'toolArgs': json.dumps({'command': c})}),
    'gemini': ('gemini', lambda c: {'hook_event_name': 'BeforeTool', 'session_id': 's', 'cwd': '{root}', 'timestamp': '2026-10-17T10:00:00Z', 'tool_name': 'run_shell_command', 'tool_input': {'command': c}}),
}
TOOL_DEMO = {   # each agent's own tools: a whole file of code, a file that is not code, a range before an edit, a search
    'claude': [('read code', {'tool_name': 'Read', 'tool_input': {'file_path': '{root}/src/shop/cart.py'}}),
               ('read not code', {'tool_name': 'Read', 'tool_input': {'file_path': '{root}/LICENSE'}}),
               ('edit', {'tool_name': 'Edit', 'tool_input': {'file_path': '{root}/src/shop/cart.py', 'old_string': 'a', 'new_string': 'b'}})],
    'codex': [],
    'cursor': [('read code', {'hook_event_name': 'beforeReadFile', 'conversation_id': 'c', 'cursor_version': '1.7', 'file_path': '{root}/src/web/cart.js', 'content': '…', 'attachments': []}),
               ('read not code', {'hook_event_name': 'beforeReadFile', 'conversation_id': 'c', 'cursor_version': '1.7', 'file_path': '{root}/LICENSE', 'content': '…', 'attachments': []})],
    'copilot': [('view code', {'sessionId': 's', 'toolName': 'view', 'toolArgs': '{"path": "{root}/src/shop/prices.py"}'}),
                ('view not code', {'sessionId': 's', 'toolName': 'view', 'toolArgs': '{"path": "{root}/LICENSE"}'}),
                ('edit', {'sessionId': 's', 'toolName': 'edit', 'toolArgs': {'path': '{root}/src/shop/prices.py', 'old_str': 'a', 'new_str': 'b'}})],
    'gemini': [('read code', {'hook_event_name': 'BeforeTool', 'tool_name': 'read_file', 'tool_input': {'file_path': '{root}/src/shop/cart.py'}}),
               ('read a range', {'hook_event_name': 'BeforeTool', 'tool_name': 'read_file', 'tool_input': {'file_path': '{root}/src/shop/cart.py', 'start_line': 5, 'end_line': 30}}),
               ('read not code', {'hook_event_name': 'BeforeTool', 'tool_name': 'read_file', 'tool_input': {'file_path': '{root}/LICENSE'}}),
               ('search a folder', {'hook_event_name': 'BeforeTool', 'tool_name': 'grep_search', 'tool_input': {'pattern': 'coupon', 'dir_path': 'src/shop'}})],
}
MAP_READS = ['python3 tools/map.py brief cart discount', 'python3 tools/map.py ask shop.cart.totals | head -40',
             'tools/map ask total --in src/shop', 'node tools/map.mjs ask coupon']
COACH_CASES = [   # (name, --agent, the event of a call); the same session throughout, the reminder at the third read
    ('claude', None, lambda c, tool='Bash': {'session_id': 'coach-claude', 'hook_event_name': 'PostToolUse', 'tool_name': tool,
                                             'tool_input': {'command': c} if tool == 'Bash' else {'file_path': c}, 'tool_response': {'stdout': '…'}}),
    ('codex', 'codex', lambda c, tool='Bash': {'session_id': 'coach-codex', 'turn_id': 't', 'hook_event_name': 'PostToolUse', 'tool_name': tool,
                                               'tool_input': {'command': c}, 'tool_response': '…'}),     # Bash and apply_patch: command
    ('cursor', None, lambda c, tool='Shell': {'conversation_id': 'coach-cursor', 'generation_id': 'g', 'cursor_version': '1.7', 'hook_event_name': 'postToolUse',
                                              'tool_name': tool, 'tool_input': {'command': c} if tool == 'Shell' else {'file_path': c}, 'tool_output': '{}'}),
    ('copilot', 'copilot', lambda c, tool='bash': {'sessionId': 'coach-copilot', 'timestamp': 1792141200000, 'toolName': tool,
                                                   'toolArgs': json.dumps({'command': c} if tool == 'bash' else {'path': c}),
                                                   'toolResult': {'resultType': 'success', 'textResultForLlm': '…'}}),
    ('gemini', None, lambda c, tool='run_shell_command': {'session_id': 'coach-gemini', 'hook_event_name': 'AfterTool', 'tool_name': tool,
                                                          'tool_input': {'command': c} if tool == 'run_shell_command' else {'file_path': c}, 'tool_response': {'llmContent': '…'}}),
]
EDITS = {'claude': ('Edit', 'src/shop/cart.py'), 'cursor': ('Write', 'src/shop/cart.py'), 'copilot': ('edit', 'src/shop/cart.py'),
         'gemini': ('replace', 'src/shop/cart.py'), 'codex': ('apply_patch', '*** Begin Patch\n*** Update File: src/shop/cart.py\n*** End Patch')}
SESSIONS = sorted((HERE / 'sessions').glob('*.jsonl'))   # two synthetic Claude Code transcripts: no real session's data


def hook_answers(guard, coach, sessions, root):
    """The guard on each agent's events, the coach on each agent's calls, the sessions on the two transcripts."""
    out = {}
    write(root / 'LICENSE', 'MIT License\n')                           # a file that is not code
    for agent, (flag, event) in SHELL.items():
        steps = [(f'{label}: {c}', event(c)) for label, c in SHELL_DEMO] + TOOL_DEMO[agent]
        text = ''
        for label, data in steps:
            answer, rc = run(guard, root, ['--agent', flag] if flag else [], stdin=json.dumps(with_root(data, root)), extra={'MAP_ROOT': str(root)})
            text += f'== {label} (rc={rc})\n{shown(answer, root)}\n'
        out['guard-demo-' + agent] = text
    if coach:
        state = root.parent / 'coach'
        for agent, flag, event in COACH_CASES:
            steps = [(MAP_READS[0], event(MAP_READS[0])), ('the same call again (a second source)', event(MAP_READS[0]))]
            steps += [(c, event(c)) for c in MAP_READS[1:]]
            tool, edit = EDITS[agent]
            steps += [(f'an edit ({tool})', event(edit, tool)), (MAP_READS[1], event(MAP_READS[1]))]
            if agent == 'claude':                                     # a subagent counts its own reads, apart from its session's
                steps += [(f'a subagent: {c}', {**event(c), 'agent_id': 'sub-1'}) for c in MAP_READS[1:]]
                steps += [('not json', 'not json'), ('no session', {'tool_name': 'Bash'})]
            text = ''
            for label, data in steps:
                payload = data if isinstance(data, str) else json.dumps(data)
                answer, rc = run(coach, root, ['--agent', flag] if flag else [], stdin=payload, extra={'MAP_ROOT': str(root), 'MAP_COACH_DIR': str(state)})
                text += f'== {label} (rc={rc})\n{shown(answer, root)}\n'
            out['coach-' + agent] = text
    if sessions:
        home = root.parent / 'home'                                    # no transcript of the machine's own
        home.mkdir(exist_ok=True)
        for name, args in (('sessions', [str(p) for p in SESSIONS]), ('sessions-since', ['--since', '2026-10-17'] + [str(p) for p in SESSIONS])):
            text, rc = run(sessions, root, args, extra={'MAP_ROOT': str(root), 'HOME': str(home)})
            out[name] = f'rc={rc}\n{mask(text, root)}'
    return out


def shown(text, root):
    """A hook's answer as the golden file keeps it: its JSON sorted and indented, or what it printed, or that it printed nothing."""
    try:
        return mask(json.dumps(json.loads(text), sort_keys=True, indent=1), root)
    except ValueError:
        return mask(text, root).rstrip('\n') or '(nothing printed: the call goes ahead)'
# @end tests.conformance.hooks


# @map tests.conformance.run: each implementation run on a fresh copy of the example, its answers masked and compared with the golden files, or recorded
def read(path):
    return pathlib.Path(path).read_text(encoding='utf-8')


def write(path, text):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:      # LF on every system: Windows would write CRLF
        f.write(text)


def in_json(root):
    """The root as it goes inside a JSON string: a Windows path carries backslashes."""
    return json.dumps(str(root))[1:-1]


def with_root(data, root):
    """The event with {root} filled in at every level; Copilot's toolArgs is JSON inside a string, so there the root is
    escaped once more (on macOS and Linux the result is the same as replacing it in the serialized event)."""
    if isinstance(data, dict):
        return {k: with_root(v, root) for k, v in data.items()}
    if isinstance(data, list):
        return [with_root(v, root) for v in data]
    if isinstance(data, str):
        return data.replace('{root}', in_json(root) if data.startswith('{"') else str(root))
    return data


def mask(text, root):
    forms = {os.path.realpath(root), str(root)}                         # /var is /private/var on macOS
    if os.name == 'nt':     # the root as Windows answers write it: with \ or /, escaped in JSON, quoted for the shell
        forms |= {f.replace('\\', '/') for f in forms}
        forms |= {json.dumps(f)[1:-1] for f in forms}
        forms |= {"'" + f + "'" for f in forms}
    for form in sorted(forms, key=len, reverse=True):
        text = text.replace(form, '<root>')
    text = re.sub(r'changed \d{4}-\d{2}-\d{2} [0-9a-f]{7} ', 'changed <date> <hash> ', text)
    text = re.sub(r'^  [0-9a-f]{7} \d{4}-\d{2}-\d{2} ', '  <hash> <date> ', text, flags=re.M)
    text = re.sub(r'"\d{4}-\d{2}-\d{2} [0-9a-f]{7} ', '"<date> <hash> ', text)      # a commit in --json
    text = re.sub(r'python3 \S*map\.py', '<map>', text)
    return text


def setup(tmp):
    root = tmp / 'example'
    shutil.copytree(REPO / 'example', root, ignore=shutil.ignore_patterns('map.yaml', 'map', '.git'))
    cfg = json.loads(read(root / 'map.json'))
    cfg['command'] = 'python3 tools/map.py'
    write(root / 'map.json', json.dumps(cfg, indent=2) + '\n')
    write(root / 'plan.md', PLAN)
    env = {**os.environ, 'GIT_AUTHOR_DATE': '2026-10-16T12:00:00Z', 'GIT_COMMITTER_DATE': '2026-10-16T12:00:00Z'}
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    subprocess.run(['git', 'add', '.'], cwd=root, check=True)
    subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'the example'], cwd=root, check=True, env=env)
    return root


def run(impl, root, args, stdin=None, extra=None):
    cmd = impl.split() + list(args)
    r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace', input=stdin,
                       env={**os.environ, **(extra or {})})
    return (r.stdout + ('' if not r.stderr.strip() else '\n[stderr]\n' + r.stderr), r.returncode)


def answers(impl, guard, coach, sessions, root):
    out = {}
    for name, args in CASES:
        text, rc = run(impl, root, ['--root', str(root)] + args)
        text = mask(text, root)
        if name == 'build':
            text += '\n[map.yaml]\n' + read(root / 'map.yaml') + ''.join(
                f'\n[{p.name}]\n' + read(p) for p in sorted((root / 'map').glob('*.yaml')))
        out[name] = f'rc={rc}\n{text}'
    extra = root / 'src' / 'shop' / 'orders.py'
    write(extra, 'import json\n\n\ndef place(cart):\n    return json.dumps(cart.lines)\n\n\nclass Order:\n    def __init__(self):\n        self.lines = []\n' * 20)
    for name, args in (('untagged-ask', ['ask', 'src/shop/orders.py', 'place']), ('untagged-gaps', ['gaps']), ('untagged-check', ['check'])):
        text, rc = run(impl, root, ['--root', str(root)] + args)
        out[name] = f'rc={rc}\n{mask(text, root)}'
    extra.unlink()
    run(impl, root, ['--root', str(root), 'build'])
    if guard:
        for name, agent, data in GUARD_CASES:
            payload = data if isinstance(data, str) else json.dumps(with_root(data, root))
            text, rc = run(guard, root, (['--agent', agent] if agent else []), stdin=payload, extra={'MAP_ROOT': str(root)})
            try:
                parsed = json.loads(text)
                text = json.dumps(parsed, sort_keys=True, indent=1)
            except ValueError:
                pass
            out['guard-' + name] = f'rc={rc}\n{mask(text, root)}'
        text, rc = run(guard, root, ['try', 'ls src/web'], extra={'MAP_ROOT': str(root)})
        out['guard-try'] = f'rc={rc}\n{mask(text, root)}'
        out.update(hook_answers(guard, coach, sessions, root))
    return out


def beside(guard, name):
    """The program next to the guard: map-guard → map-coach, map-guard.mjs → map-sessions.mjs."""
    head, found, tail = guard.rpartition('map-guard')
    return head + name + tail if found else None


def main(argv):
    opt = lambda k: argv[argv.index(k) + 1] if k in argv and argv.index(k) + 1 < len(argv) else None  # noqa: E731
    impl = opt('--impl') or f'python3 {REPO / "python" / "map.py"}'
    guard = opt('--guard') or (f'python3 {REPO / "python" / "map-guard.py"}' if '--impl' not in argv else None)
    coach = opt('--coach') or (beside(guard, 'map-coach') if guard else None)
    sessions = opt('--sessions') or (beside(guard, 'map-sessions') if guard else None)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='map-conformance-'))
    try:
        root = setup(tmp)
        got = answers(impl, guard, coach, sessions, root)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if '--record' in argv:
        GOLDEN.mkdir(exist_ok=True)
        for old in GOLDEN.glob('*.txt'):
            old.unlink()
        for name, text in got.items():
            write(GOLDEN / f'{name}.txt', text)
        print(f'{len(got)} golden answers written to {GOLDEN.relative_to(REPO)}')
        return 0
    failed = 0
    for name, text in got.items():
        want = read(GOLDEN / f'{name}.txt') if (GOLDEN / f'{name}.txt').exists() else None
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
# @end tests.conformance.run
