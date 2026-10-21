# @map tests.guard.cases: the guard on shell lines and on the five agents' hook formats: what is refused, with which ask, and what goes ahead
"""The map guard: a refused call names the ask that answers the same question, and that ask runs; anything that is
not reading the code or the docs goes ahead; each agent's format is read and answered in its own shape."""
import json
import os
import pathlib
import subprocess
import unittest

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
GUARD = REPO / 'python' / 'map-guard.py'
ROOT = REPO / 'example'
ASK = 'python3 ../python/map.py ask '


def hook(data, agent=None):
    args = ['python3', str(GUARD)] + (['--agent', agent] if agent else [])
    r = subprocess.run(args, input=data if isinstance(data, str) else json.dumps(data), capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def bash(command, agent=None):
    """The ask a refusal names, the line Claude Code runs in its place, or None when the line goes ahead."""
    out = hook({'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': command, 'description': 'd'}, 'cwd': str(ROOT)}, agent)
    if not out:
        return None
    o = out['hookSpecificOutput']
    if o['permissionDecision'] == 'allow':
        assert o['updatedInput']['description'] == 'd' and o['additionalContext'].endswith(o['updatedInput']['command'])
        return o['updatedInput']['command']
    assert o['permissionDecision'] == 'deny'
    return o['permissionDecisionReason'].split('Run instead:\n  ')[1]


def refusal_line(command, agent=None):
    """What follows 'Run instead:' in an agent's refusal of a shell line, in that agent's own format."""
    cwd = str(ROOT)
    event = {None: {'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': cwd},
             'codex': {'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': cwd},
             'gemini': {'hook_event_name': 'BeforeTool', 'tool_name': 'run_shell_command', 'tool_input': {'command': command}, 'cwd': cwd},
             'copilot': {'toolName': 'bash', 'toolArgs': json.dumps({'command': command}), 'cwd': cwd},
             'cursor': {'command': command, 'cwd': cwd, 'cursor_version': '1.0'}}[agent]
    out = hook(event, agent)
    text = (out.get('hookSpecificOutput', {}).get('permissionDecisionReason') or out.get('permissionDecisionReason')
            or out.get('reason') or out.get('agent_message'))
    return text.split('Run instead:\n  ')[1]


def in_place(ask):
    return f'(cd {ROOT} && {ASK}{ask})'


class Refused(unittest.TestCase):
    cases = [
        ('grep -rn coupon src', 'coupon --in src'),
        ('grep -n "def total" src/shop/cart.py', 'total --in src/shop/cart.py'),
        ('grep -n "total\\|money" src', 'total money --in src'),
        ('grep -rn "ten apples" src docs', "'ten apples' --in src,docs"),
        ('grep -rn coupon src 2>/dev/null | head -3', 'coupon --in src | head -3'),
        ('cd src && grep -rn coupon .', 'coupon --in src'),
        ('git grep -n coupon', 'coupon'),
        ('find src -name "*.js" | xargs grep -n money', "money --in 'src/*.js'"),
        ('grep -n "@map shop.cart.totals" src/shop/cart.py', 'shop.cart.totals'),
        ('sed -n 20,40p src/shop/cart.py', 'src/shop/cart.py:20-40'),
        ('sed -n 20,40p src/shop/cart.py | cut -c1-80', 'src/shop/cart.py:20-40 | cut -c1-80'),
        ('cat docs/CART.md', 'docs/CART.md'),
        ('head -5 docs/CART.md', 'docs/CART.md:1-5'),
        ('tail -3 src/shop/prices.py', 'src/shop/prices.py:28-30'),
        ('ls src/web/', 'src/web'),
        ('rg coupon src', 'coupon --in src'),
    ]

    def test_shell_lines(self):
        for command, ask in self.cases:
            with self.subTest(command=command):
                self.assertEqual(bash(command, 'codex'), ASK + ask)
                self.assertEqual(bash(command), ASK + ask if 'xargs' in command else in_place(ask))   # xargs could run anything

    def test_claude_code_runs_a_line_of_reads_in_its_place(self):
        self.assertEqual(bash('sed -n 1,5p src/shop/cart.py; echo ---; sed -n 20,40p src/shop/cart.py | head -3'),
                         f'(cd {ROOT} && {ASK}src/shop/cart.py:1-5; echo ---; {ASK}src/shop/cart.py:20-40 | head -3)')
        self.assertEqual(bash('ls src/web; wc -l src/web/cart.js; tail -3 src/shop/prices.py | cut -c1-20'),
                         f'(cd {ROOT} && {ASK}src/web; wc -l src/web/cart.js; {ASK}src/shop/prices.py:28-30 | cut -c1-20)')
        for command in ['grep -rn coupon src; python3 -m unittest discover -s tests', 'sed -n 1,5p src/shop/cart.py | awk "{print}"',
                        'cat src/shop/cart.py LICENSE-none', 'cat $(ls src/shop/*.py)']:
            with self.subTest(command=command):                       # another step, a filter that runs commands: refused
                self.assertTrue(bash(command).startswith(ASK), command)
        line = bash('cd src/shop && sed -n 1,3p cart.py')
        r = subprocess.run(line, shell=True, cwd=ROOT / 'src', capture_output=True, text=True)    # from any folder
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('src/shop/cart.py:1-3', r.stdout)

    def test_read_only_steps_stay_in_the_rewritten_line(self):
        """git's read-only forms, which, command -v, --version, pwd, date, printf, true: as written, inside the line Claude Code runs."""
        for command, ask, line in [
            ('git status --short | head -3; sed -n 1,5p src/shop/cart.py', 'src/shop/cart.py:1-5', 'git status --short | head -3; {}'),
            ('git log --oneline -3; git diff --stat | tail -2; git show HEAD --stat; git rev-parse HEAD; git branch -a; cat docs/CART.md', 'docs/CART.md',
             'git log --oneline -3; git diff --stat | tail -2; git show HEAD --stat; git rev-parse HEAD; git branch -a; {}'),
            ("git branch --list 'x*' && cat docs/CART.md", 'docs/CART.md', "git branch --list 'x*' && {}"),
            ('which python3; command -v git; python3 --version; pwd; date +%F; printf "a\\n"; true; cat docs/CART.md', 'docs/CART.md',
             'which python3; command -v git; python3 --version; pwd; date +%F; printf "a\\n"; true; {}'),
            ('git status 2>&1 | head -2\ncat docs/CART.md', 'docs/CART.md', 'git status 2>&1 | head -2\n{}'),
        ]:
            with self.subTest(command=command):
                self.assertEqual(bash(command), in_place(ask).replace(f'{ASK}{ask}', line.format(ASK + ask)))
        for command in ['git commit -m x; cat docs/CART.md', 'git branch newone; cat docs/CART.md', 'git branch -D x; cat docs/CART.md',
                        'git diff --output=/tmp/x; cat docs/CART.md', 'git -C .. status; cat docs/CART.md', 'git -c core.pager=x log; cat docs/CART.md',
                        'git push; cat docs/CART.md', 'date -s 2020-01-01; cat docs/CART.md', './tools/x --version; cat docs/CART.md',
                        'ls /tmp; cat docs/CART.md', 'cat /tmp/x.log; cat docs/CART.md', 'wc -l /etc/hosts; cat docs/CART.md']:
            with self.subTest(command=command):                         # not read-only, or outside the repository: refused, never an allow
                out = hook({'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': str(ROOT)})['hookSpecificOutput']
                self.assertEqual(out['permissionDecision'], 'deny')
                self.assertNotIn('updatedInput', out)
        self.assertIsNone(bash('cd .. && git status; cat docs/CART.md'))           # nothing of the repository is read: goes ahead

    def test_shell_forms_of_a_line_of_reads(self):
        for command, line in [
            ('cat docs/CART.md 2>&1 | head -3', f'(cd {ROOT} && {ASK}docs/CART.md | head -3)'),
            ('cat docs/CART.md 2>/dev/null; cat docs/CART.md &>/dev/null', f'(cd {ROOT} && {ASK}docs/CART.md; {ASK}docs/CART.md)'),
            ('cut -c1-20 src/shop/cart.py', f'(cd {ROOT} && {ASK}src/shop/cart.py | cut -c1-20)'),
            ('cut -d, -f2 src/shop/cart.py | sort | uniq -c', f'(cd {ROOT} && {ASK}src/shop/cart.py | cut -d, -f2 | sort | uniq -c)'),
            ('sort -u docs/CART.md', f'(cd {ROOT} && {ASK}docs/CART.md | sort -u)'),
            ('grep -rn coupon src | sed -n 1,5p', f'(cd {ROOT} && {ASK}coupon --in src | sed -n 1,5p)'),
            ('sed -n 1,5p src/shop/cart.py | sed -n 2,3p; cat docs/CART.md | wc -l', f'(cd {ROOT} && {ASK}src/shop/cart.py:1-5 | sed -n 2,3p; cat docs/CART.md | wc -l)'),
            ('for f in a b; do echo $f; done; sed -n 1,5p src/shop/cart.py', f'(cd {ROOT} && for f in a b; do echo $f; done; {ASK}src/shop/cart.py:1-5)'),
        ]:
            with self.subTest(command=command):
                self.assertEqual(bash(command), line)
        for command in ['grep -rn coupon src | grep -c money', 'grep -rn coupon src | grep -ic money', 'cat docs/CART.md | grep -ci x',
                        'sort docs/CART.md -o /tmp/x', 'sed -n 1,5p src/shop/cart.py | sed -n "s/a/b/w /tmp/x"']:
            with self.subTest(command=command):
                if 'grep' in command or 'sort' in command:
                    self.assertIsNone(bash(command), command)               # a count goes ahead; sort -o writes
        self.assertFalse(bash('sed -n 1,5p src/shop/cart.py | sed "s/a/b/w /tmp/x"').startswith('(cd'))   # a sed that writes: refused
        self.assertFalse(bash('sed -n 1,5p src/shop/cart.py | sed -n "1e id"; echo x').startswith('(cd'))

    def test_a_refused_line_comes_back_whole(self):
        """Reads beside steps that are not reads: the refusal gives the line to send again, every read as its ask, every
        other step as written, the same separators; for each agent."""
        cases = [
            ('grep -rn coupon src; python3 -m unittest discover -s tests', ASK + 'coupon --in src; python3 -m unittest discover -s tests'),
            ('python3 -m unittest && sed -n 1,5p src/shop/cart.py | head -3 || echo "no"', f'python3 -m unittest && {ASK}src/shop/cart.py:1-5 | head -3 || echo "no"'),
            ("sed -n 1,5p src/shop/cart.py\nnpm  test  2>&1 | tail -3\ncat docs/CART.md", f"{ASK}src/shop/cart.py:1-5\nnpm  test  2>&1 | tail -3\n{ASK}docs/CART.md"),
            ('git commit -m "a b" ; cat docs/CART.md', f'git commit -m "a b" ; {ASK}docs/CART.md'),
            ('cat docs/CART.md; ls /tmp', ASK + 'docs/CART.md; ls /tmp'),                                    # a read outside the repository stays as it is
            ('git -C .. status; cat docs/CART.md', f'git -C .. status; {ASK}docs/CART.md'),             # git of another folder is no read of this repository
            ('cd src && cat shop/cart.py && npm test', f'cd src && (cd {ROOT} && {ASK}src/shop/cart.py) && npm test'),   # the ask runs from the root
            ('cat docs/CART.md | wc -l; grep -rn coupon src; cargo test', f'cat docs/CART.md | wc -l; {ASK}coupon --in src; cargo test'),
        ]
        for command, line in cases:
            for agent in (None, 'codex', 'gemini', 'copilot', 'cursor'):
                with self.subTest(command=command, agent=agent):
                    self.assertEqual(refusal_line(command, agent), line)
        out = hook({'tool_name': 'Bash', 'tool_input': {'command': 'cat docs/CART.md; npm test'}, 'cwd': str(ROOT)})['hookSpecificOutput']
        self.assertEqual(out['permissionDecision'], 'deny')                       # never an allow: the line has a step that is not a read
        self.assertIn('None of this command ran: send this line instead, its reads already through the map. Run instead:\n  ' + ASK + 'docs/CART.md; npm test', out['permissionDecisionReason'])
        # a line of reads only keeps the refusal that names the asks
        self.assertIn('send its other steps again. Run instead:\n  ' + ASK + 'src/shop/cart.py:1-5', hook({'tool_name': 'Bash', 'tool_input': {'command': 'sed -n 1,5p src/shop/cart.py | awk "{print}"'}, 'cwd': str(ROOT)})['hookSpecificOutput']['permissionDecisionReason'])

    def test_the_line_sent_again_goes_ahead(self):
        """The map's own commands beside other steps are no read: the line the refusal gave runs, in every agent."""
        import shutil
        import tempfile
        tmp = pathlib.Path(os.path.realpath(tempfile.mkdtemp(prefix='map-resend-')))
        try:
            (tmp / 'src').mkdir()
            (tmp / 'src' / 'a.py').write_text('x = 1\n' * 30)
            (tmp / 'map.json').write_text('{"command": "tools/map"}')        # no map.py in the command: nothing in it marks the line as the map's
            env = {**os.environ, 'MAP_ROOT': str(tmp)}

            def ask(command, agent=None):
                data = {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': str(tmp)}
                r = subprocess.run(['python3', str(GUARD)] + (['--agent', agent] if agent else []), input=json.dumps(data), capture_output=True, text=True, cwd=tmp, env=env)
                return json.loads(r.stdout) if r.stdout.strip() else None
            out = ask('tools/map ask a 2>&1 | head -5; git status -s; sed -n 1,5p src/a.py 2>&1')['hookSpecificOutput']        # the map's own step as written
            self.assertEqual(out['updatedInput']['command'], f'(cd {tmp} && tools/map ask a 2>&1 | head -5; git status -s; tools/map ask src/a.py:1-5)')
            for command in ['grep -rn x src; cargo test', 'sed -n 1,5p src/a.py && npm test | tail -3', 'cat src/a.py; ls /tmp; git commit -m x',
                            'cd src && head -3 a.py; make']:
                for agent in (None, 'codex'):
                    with self.subTest(command=command, agent=agent):
                        out = ask(command, agent)['hookSpecificOutput']
                        self.assertEqual(out['permissionDecision'], 'deny')
                        again = out['permissionDecisionReason'].split('Run instead:\n  ')[1]
                        self.assertIn('tools/map ask', again)
                        self.assertIsNone(ask(again, agent), again)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_scripts_that_only_print_the_code(self):
        self.assertEqual(bash("python3 -c \"print(open('src/shop/cart.py').read())\""), ASK + 'src/shop/cart.py')
        self.assertEqual(bash("node -e \"console.log(require('fs').readFileSync('src/web/cart.js','utf8'))\""), ASK + 'src/web/cart.js')
        self.assertEqual(bash("cat > /tmp/peek-map-test.py <<'EOF'\nt = open('src/shop/prices.py').read()\nprint(t[:500])\nEOF"), ASK + 'src/shop/prices.py')

    def test_each_named_ask_runs(self):
        for _, ask in self.cases:
            with self.subTest(ask=ask):
                r = subprocess.run('sh -c ' + json.dumps(ASK + ask), shell=True, cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertGreater(len(r.stdout), 20, ask)


# @map tests.guard.cases.allowed: what is not a read of the code goes ahead: edits and the reads that check them, other tools, files outside the repository
class Allowed(unittest.TestCase):
    def test_what_is_not_reading_goes_ahead(self):
        for command in ['python3 ../python/map.py ask total', 'python3 -m unittest discover -s tests', 'node tests/format.test.js',
                        "sed -i '' 's/a/b/' src/shop/cart.py", "cat > /tmp/x.txt <<'EOF'\ngrep -rn x src\nEOF",
                        'grep -c coupon src/shop/cart.py', 'grep -q coupon src/shop/cart.py && echo yes', 'rg -l coupon src',
                        'wc -l src/shop/cart.py', 'ls', 'cat map.yaml', 'head -5 map/shop.yaml', 'cat ../README.md',
                        'git diff src/shop/cart.py | head', 'find src -newer map.yaml -type f', 'tail -5 /tmp/run.log',
                        "python3 - <<'EOF'\np='src/shop/cart.py'\ns=open(p).read().replace('a','b')\nopen(p,'w').write(s)\nEOF",
                        "python3 -c \"import json;print(json.load(open('/tmp/out.json')))\"",
                        'grep -rn coupon src | wc -l', "awk 'NR>=5 && NR<=8' src/shop/cart.py | wc -c"]:
            with self.subTest(command=command):
                self.assertIsNone(bash(command), command)

    def test_the_reads_that_check_an_edit_go_ahead(self):
        for command in ["sed -i '' 's/a/b/' src/shop/cart.py && grep -n b src/shop/cart.py",
                        "python3 - <<'EOF'\np='src/shop/cart.py'\ns=open(p).read().replace('a','b')\nopen(p,'w').write(s)\nEOF\ntail -5 src/shop/cart.py",
                        "cat >> src/shop/cart.py <<'EOF'\n# more\nEOF\nsed -n 1,5p src/shop/cart.py", 'echo x | tee -a docs/CART.md; cat docs/CART.md']:
            with self.subTest(command=command):
                self.assertIsNone(bash(command), command)
                self.assertIsNone(bash(command, 'codex'), command)
        self.assertEqual(bash('sed -n 1,5p src/shop/cart.py; echo x > /tmp/map-guard-test.txt', 'codex'),
                         ASK + 'src/shop/cart.py:1-5; echo x > /tmp/map-guard-test.txt')            # not an edit of the code: the whole line

    def test_tools_of_claude_code(self):
        self.assertEqual(hook({'tool_name': 'Read', 'tool_input': {'file_path': str(ROOT / 'src/shop/cart.py')}, 'cwd': str(ROOT)})['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertIsNone(hook({'tool_name': 'Read', 'tool_input': {'file_path': str(ROOT / 'src/shop/cart.py'), 'offset': 10, 'limit': 20}, 'cwd': str(ROOT)}))
        self.assertIsNone(hook({'tool_name': 'Read', 'tool_input': {'file_path': '/tmp/shot.png'}, 'cwd': str(ROOT)}))
        grep = hook({'tool_name': 'Grep', 'tool_input': {'pattern': 'coupon', 'path': 'src'}, 'cwd': str(ROOT)})
        self.assertIn(ASK + 'coupon --in src', grep['hookSpecificOutput']['permissionDecisionReason'])
        self.assertIsNone(hook({'tool_name': 'Grep', 'tool_input': {'pattern': 'coupon', 'path': 'src', 'output_mode': 'count'}, 'cwd': str(ROOT)}))
        glob_ = hook({'tool_name': 'Glob', 'tool_input': {'pattern': '**/*.js', 'path': 'src'}, 'cwd': str(ROOT)})
        self.assertIn(ASK + "'src/**/*.js'", glob_['hookSpecificOutput']['permissionDecisionReason'])
        self.assertIsNone(hook({'tool_name': 'Edit', 'tool_input': {'file_path': str(ROOT / 'src/shop/cart.py')}, 'cwd': str(ROOT)}))


# @end tests.guard.cases.allowed


# @map tests.guard.cases.agents: each agent's hook format read and answered in its own shape, bad input, and the settings install writes
class Agents(unittest.TestCase):
    def test_codex(self):
        out = hook({'hook_event_name': 'PreToolUse', 'turn_id': 't', 'tool_name': 'Bash', 'tool_input': {'command': 'cat src/shop/prices.py'}, 'cwd': str(ROOT)}, 'codex')
        self.assertEqual(out['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertTrue(out['hookSpecificOutput']['permissionDecisionReason'].endswith(ASK + 'src/shop/prices.py'))

    def test_cursor(self):
        out = hook({'command': 'rg coupon src', 'cwd': str(ROOT), 'sandbox': False, 'cursor_version': '1.0'})
        self.assertEqual(out['permission'], 'deny')
        self.assertTrue(out['agent_message'].endswith(ASK + 'coupon --in src'))
        out = hook({'file_path': str(ROOT / 'docs/CART.md'), 'content': '…', 'attachments': [], 'cursor_version': '1.0'})
        self.assertEqual(out['permission'], 'deny')
        out = hook({'tool_name': 'Shell', 'tool_input': {'command': 'head -40 src/web/cart.js', 'working_directory': str(ROOT)}, 'cwd': str(ROOT)}, 'cursor')
        self.assertTrue(out['agent_message'].endswith(ASK + 'src/web/cart.js:1-20'))
        self.assertIsNone(hook({'command': 'node tests/format.test.js', 'cwd': str(ROOT), 'sandbox': False, 'cursor_version': '1.0'}))

    def test_copilot(self):
        out = hook({'sessionId': 's', 'cwd': str(ROOT), 'toolName': 'bash', 'toolArgs': json.dumps({'command': 'grep -rn money src/web'})})
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertTrue(out['permissionDecisionReason'].endswith(ASK + 'money --in src/web'))
        out = hook({'hook_event_name': 'PreToolUse', 'cwd': str(ROOT), 'tool_name': 'bash', 'tool_input': {'command': 'cat src/web/format.js'}})
        self.assertTrue(out['permissionDecisionReason'].endswith(ASK + 'src/web/format.js'))
        out = hook({'cwd': str(ROOT), 'toolName': 'view', 'toolArgs': json.dumps({'path': str(ROOT / 'src/web/cart.js')})}, 'copilot')
        self.assertTrue(out['permissionDecisionReason'].endswith(ASK + 'src/web/cart.js'))

    def test_gemini(self):
        out = hook({'hook_event_name': 'BeforeTool', 'tool_name': 'run_shell_command', 'tool_input': {'command': 'grep -rn coupon src'}, 'cwd': str(ROOT)})
        self.assertEqual(out['decision'], 'deny')
        self.assertTrue(out['reason'].endswith(ASK + 'coupon --in src'))
        out = hook({'hook_event_name': 'BeforeTool', 'tool_name': 'read_file', 'tool_input': {'absolute_path': str(ROOT / 'src/shop/cart.py')}, 'cwd': str(ROOT)})
        self.assertTrue(out['reason'].endswith(ASK + 'src/shop/cart.py'))
        self.assertIsNone(hook({'hook_event_name': 'BeforeTool', 'tool_name': 'run_shell_command', 'tool_input': {'command': 'python3 -m unittest'}, 'cwd': str(ROOT)}))
        ranged = {'file_path': str(ROOT / 'src/shop/cart.py'), 'start_line': 5, 'end_line': 30}            # read_file's range: before an edit
        self.assertIsNone(hook({'hook_event_name': 'BeforeTool', 'tool_name': 'read_file', 'tool_input': ranged, 'cwd': str(ROOT)}))
        out = hook({'hook_event_name': 'BeforeTool', 'tool_name': 'grep_search', 'tool_input': {'pattern': 'coupon', 'dir_path': 'src/shop'}, 'cwd': str(ROOT)})
        self.assertTrue(out['reason'].endswith(ASK + 'coupon --in src/shop'))

    def test_bad_input_goes_ahead(self):
        self.assertIsNone(hook('not json'))
        self.assertIsNone(hook({'tool_name': 'Bash'}))

    def test_install_writes_each_agents_settings(self):
        import shutil
        import tempfile
        tmp = pathlib.Path(tempfile.mkdtemp(prefix='map-install-'))
        try:
            shutil.copy(GUARD, tmp / 'map-guard.py')
            (tmp / 'map.json').write_text('{}')
            (tmp / '.claude').mkdir()
            (tmp / '.claude' / 'settings.json').write_text(json.dumps({'permissions': {'deny': ['Bash(git push *)']}, 'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'echo hi'}]}]}}))
            for agent, path in [('claude', '.claude/settings.json'), ('codex', '.codex/hooks.json'), ('cursor', '.cursor/hooks.json'),
                                ('copilot', '.github/hooks/map-guard.json'), ('gemini', '.gemini/settings.json')]:
                r = subprocess.run(['python3', str(tmp / 'map-guard.py'), 'install', agent], cwd=tmp, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue((tmp / path).is_file(), path)
                self.assertIn('map-guard.py', (tmp / path).read_text())
            claude = json.loads((tmp / '.claude' / 'settings.json').read_text())
            self.assertEqual(claude['permissions'], {'deny': ['Bash(git push *)']})                    # what was there is kept
            self.assertEqual(len(claude['hooks']['PreToolUse']), 2)
            self.assertEqual(claude['hooks']['PreToolUse'][1]['hooks'][0]['command'], 'python3 "$CLAUDE_PROJECT_DIR/map-guard.py"')
            codex = json.loads((tmp / '.codex' / 'hooks.json').read_text())['hooks']['PreToolUse'][0]['hooks'][0]
            self.assertEqual(codex['command'], 'python3 "$(git rev-parse --show-toplevel)/map-guard.py" --agent codex')
            gemini = json.loads((tmp / '.gemini' / 'settings.json').read_text())['hooks']['BeforeTool'][0]['hooks'][0]
            self.assertEqual(gemini['command'], 'python3 "$GEMINI_PROJECT_DIR/map-guard.py" --agent gemini')
            copilot = json.loads((tmp / '.github' / 'hooks' / 'map-guard.json').read_text())['hooks']['preToolUse'][0]
            self.assertEqual(copilot['cwd'], '.')                       # the repository's root, wherever the CLI was started
            subprocess.run(['python3', str(tmp / 'map-guard.py'), 'install', 'claude'], cwd=tmp, capture_output=True, text=True)
            self.assertEqual(len(json.loads((tmp / '.claude' / 'settings.json').read_text())['hooks']['PreToolUse']), 2)   # installed twice: once
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
# @end tests.guard.cases.agents
# @end tests.guard.cases


if __name__ == '__main__':
    unittest.main()
