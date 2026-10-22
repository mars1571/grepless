# @map tests.guard.cases: the guard on shell lines and on the five agents' hook formats: what is refused, with which ask, and what goes ahead
"""The map guard: a refused call names the ask that answers the same question, and that ask runs; anything that is
not reading the code or the docs goes ahead; each agent's format is read and answered in its own shape."""
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

HERE =pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
GUARD = REPO / 'python' / 'map-guard.py'
ROOT = REPO / 'example'
ASK = 'python3 ../python/map.py ask '


# @map tests.guard.cases.shell: the root as the guard writes it in a line, and the lines it writes run in the agent's shell (Git Bash on Windows)
def root_word(path):
    """A folder as the guard writes it in a `(cd … && …)`: on Windows with `/` (bash takes a backslash for an escape),
    quoted when it needs it."""
    p = str(path).replace('\\', '/') if os.name == 'nt' else str(path)
    return p if re.fullmatch(r'[A-Za-z0-9@%+=:,./_-]+', p) else "'" + p.replace("'", "'\"'\"'") + "'"


WORD = root_word(ROOT)


def git_bash():
    """Git for Windows' bash, found from git (the `bash` on the PATH may be WSL's)."""
    here = shutil.which('git')
    for _ in range(3):
        here = os.path.dirname(here or '')
        for sub in ('bin', os.path.join('usr', 'bin')):
            if os.path.isfile(os.path.join(here, sub, 'bash.exe')):
                return os.path.join(here, sub, 'bash.exe')
    return shutil.which('bash') or 'bash'


def sh(line, cwd):
    """A shell line run as the agent's shell runs it: sh, or Git Bash on Windows (cmd.exe cannot run what the guard writes)."""
    if os.name != 'nt':
        return subprocess.run(line, shell=True, cwd=cwd, capture_output=True, text=True)
    return subprocess.run([git_bash(), '-c', line], cwd=cwd, capture_output=True, text=True, encoding='utf-8')
# @end tests.guard.cases.shell


def hook(data, agent=None, root=None):
    """The guard's answer to an event; root: another folder (a copy of the example) for the guard to take as the repository.
    MAP_GUARD names another implementation's guard to answer it (`node node/map-guard.mjs`, a built map-guard)."""
    args = (shlex.split(os.environ['MAP_GUARD']) if os.environ.get('MAP_GUARD') else ['python3', str(GUARD)]) + (['--agent', agent] if agent else [])
    env = {**os.environ, 'MAP_ROOT': str(root)} if root else None
    r = subprocess.run(args, input=data if isinstance(data, str) else json.dumps(data), capture_output=True, text=True, encoding='utf-8', cwd=root or ROOT, env=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def bash(command, agent=None, root=None):
    """The ask a refusal names, the line Claude Code runs in its place, or None when the line goes ahead."""
    out = hook({'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': command, 'description': 'd'}, 'cwd': str(root or ROOT)}, agent, root)
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
    return f'(cd {WORD} && {ASK}{ask})'


class Refused(unittest.TestCase):
    cases = [
        ('grep -rn coupon src', 'coupon --in src'),
        ('grep -n "def total" src/shop/cart.py', 'total --in src/shop/cart.py'),
        ('grep -n "total\\|money" src', 'total money --in src'),
        ('grep -rn "ten apples" src docs', "'ten apples' --in src,docs"),
        ('grep -rn coupon src 2>/dev/null | head -3', 'coupon --in src'),
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
                         f'(cd {WORD} && {ASK}src/shop/cart.py:1-5; echo ---; {ASK}src/shop/cart.py:20-40)')
        self.assertEqual(bash('ls src/web; wc -l src/web/cart.js; tail -3 src/shop/prices.py | cut -c1-20'),
                         f'(cd {WORD} && {ASK}src/web; wc -l src/web/cart.js; {ASK}src/shop/prices.py:28-30 | cut -c1-20)')
        for command in ['grep -rn coupon src; python3 -m unittest discover -s tests', 'sed -n 1,5p src/shop/cart.py | awk "{print}"',
                        'cat src/shop/cart.py LICENSE-none', 'cat $(ls src/shop/*.py)']:
            with self.subTest(command=command):                       # another step, a filter that runs commands: refused
                self.assertTrue(bash(command).startswith(ASK), command)
        line = bash('cd src/shop && sed -n 1,3p cart.py')
        r = sh(line, ROOT / 'src')                                  # from any folder
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
            ('cat docs/CART.md 2>&1 | head -3', f'(cd {WORD} && {ASK}docs/CART.md:1-3)'),
            ('cat docs/CART.md 2>/dev/null; cat docs/CART.md &>/dev/null', f'(cd {WORD} && {ASK}docs/CART.md; {ASK}docs/CART.md)'),
            ('cut -c1-20 src/shop/cart.py', f'(cd {WORD} && {ASK}src/shop/cart.py | cut -c1-20)'),
            ('cut -d, -f2 src/shop/cart.py | sort | uniq -c', f'(cd {WORD} && {ASK}src/shop/cart.py | cut -d, -f2 | sort | uniq -c)'),
            ('sort -u docs/CART.md', f'(cd {WORD} && {ASK}docs/CART.md | sort -u)'),
            ('grep -rn coupon src | sed -n 1,5p', f'(cd {WORD} && {ASK}coupon --in src | sed -n 1,5p)'),
            ('sed -n 1,5p src/shop/cart.py | sed -n 2,3p; cat docs/CART.md | wc -l', f'(cd {WORD} && {ASK}src/shop/cart.py:1-5 | sed -n 2,3p; cat docs/CART.md | wc -l)'),
            ('for f in a b; do echo $f; done; sed -n 1,5p src/shop/cart.py', f'(cd {WORD} && for f in a b; do echo $f; done; {ASK}src/shop/cart.py:1-5)'),
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
            ('python3 -m unittest && sed -n 1,5p src/shop/cart.py | head -3 || echo "no"', f'python3 -m unittest && {ASK}src/shop/cart.py:1-5 || echo "no"'),
            ("sed -n 1,5p src/shop/cart.py\nnpm  test  2>&1 | tail -3\ncat docs/CART.md", f"{ASK}src/shop/cart.py:1-5\nnpm  test  2>&1 | tail -3\n{ASK}docs/CART.md"),
            ('git commit -m "a b" ; cat docs/CART.md', f'git commit -m "a b" ; {ASK}docs/CART.md'),
            ('cat docs/CART.md; ls /tmp', ASK + 'docs/CART.md; ls /tmp'),                                    # a read outside the repository stays as it is
            ('git -C .. status; cat docs/CART.md', f'git -C .. status; {ASK}docs/CART.md'),             # git of another folder is no read of this repository
            ('cd src && cat shop/cart.py && npm test', f'cd src && (cd {WORD} && {ASK}src/shop/cart.py) && npm test'),   # the ask runs from the root
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
                r = subprocess.run(['python3', str(GUARD)] + (['--agent', agent] if agent else []), input=json.dumps(data), capture_output=True, text=True, encoding='utf-8', cwd=tmp, env=env)
                return json.loads(r.stdout) if r.stdout.strip() else None
            out = ask('tools/map ask a 2>&1 | head -5; git status -s; sed -n 1,5p src/a.py 2>&1')['hookSpecificOutput']        # the map's own step as written
            self.assertEqual(out['updatedInput']['command'], f'(cd {root_word(tmp)} && tools/map ask a 2>&1 | head -5; git status -s; tools/map ask src/a.py:1-5)')
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


# @map tests.guard.cases.places: one rule for every tool, on a copy of the example: a place the map does not index (left out, or holding no file it reads) goes ahead for Glob, Grep, Read and Bash alike, and a Windows path names the same place in any of its forms
class Places(unittest.TestCase):
    LEFT_OUT = [('.claude/redesign/design', 'review.html'),      # map.json ignore
                ('fixtures', 'cases.md'),                         # map.json guard.skip
                ('scratch', 'notes.md'),                          # .gitignore
                ('vendor/lib', 'lib.js')]                         # one of the usual folders

    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(os.path.realpath(tempfile.mkdtemp(prefix='map-places-')))
        cls.root = cls.tmp / 'example'
        shutil.copytree(ROOT, cls.root, ignore=shutil.ignore_patterns('__pycache__'))
        cfg = json.loads((cls.root / 'map.json').read_text(encoding='utf-8'))
        cfg['ignore'], cfg['guard'] = ['.claude/redesign/'], {'skip': ['fixtures/']}
        (cls.root / 'map.json').write_text(json.dumps(cfg), encoding='utf-8')
        (cls.root / '.gitignore').write_text('scratch/\n', encoding='utf-8')
        for folder, name in cls.LEFT_OUT + [('assets', 'logo.png'), ('deep/a', 'logo.png'), ('deep/a/b', 'notes.md')]:  # assets: holds no file the map reads; deep: one, two folders down
            (cls.root / folder).mkdir(parents=True, exist_ok=True)
            (cls.root / folder / name).write_text('<p>Roche limit</p>\n', encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def ask(self, tool, given):
        """The ask the guard's refusal of this tool call names (the line Claude Code runs in place of a shell line), or None when it goes ahead."""
        out = hook({'tool_name': tool, 'tool_input': given, 'cwd': str(self.root)}, root=self.root)
        o = out and out['hookSpecificOutput']
        return o and (o['updatedInput']['command'] if o['permissionDecision'] == 'allow' else o['permissionDecisionReason'].split('Run instead:\n  ')[1])

    def test_a_place_the_map_leaves_out_goes_ahead_for_every_tool(self):
        for k, (folder, name) in enumerate(self.LEFT_OUT):
            file = str(self.root / folder / name)
            calls = [('Glob', {'pattern': f'{folder}/*'}), ('Grep', {'pattern': 'Roche', 'path': folder}), ('Read', {'file_path': file}),
                     ('Bash', {'command': f'grep -n Roche {folder}/{name}'}), ('Bash', {'command': f'ls {folder}'})]
            if k == 0:                                                   # the folder of the report, in more forms
                calls += [('Glob', {'pattern': '*', 'path': folder}), ('Glob', {'pattern': f'{folder}/**/{name}'}), ('Glob', {'pattern': file.replace('\\', '/')}),
                          ('Glob', {'pattern': '**/*', 'path': str(self.root / folder)}), ('Bash', {'command': f'cat {folder}/{name}'})]
            for tool, given in calls:
                with self.subTest(folder=folder, tool=tool, given=given):
                    self.assertIsNone(self.ask(tool, given))
        for tool, given in [('Glob', {'pattern': 'assets/*'}), ('Grep', {'pattern': 'Roche', 'path': 'assets'}), ('Bash', {'command': 'grep -rn Roche assets'}),
                            ('Bash', {'command': 'ls assets'}), ('Read', {'file_path': str(self.root / 'assets/logo.png')})]:
            with self.subTest(folder='assets', tool=tool, given=given):     # a folder holding no file the map reads: its ask would answer nothing
                self.assertIsNone(self.ask(tool, given))
        for tool, given, ask in [('Glob', {'pattern': 'src/web/*'}, "'src/web/*'"), ('Grep', {'pattern': 'coupon', 'path': 'src'}, 'coupon --in src'),
                                 ('Read', {'file_path': str(self.root / 'src/shop/cart.py')}, 'src/shop/cart.py'),
                                 ('Bash', {'command': 'grep -n coupon src/shop/cart.py'}, 'coupon --in src/shop/cart.py'),
                                 ('Grep', {'pattern': 'Roche', 'path': 'deep'}, 'Roche --in deep'), ('Bash', {'command': 'grep -rn Roche deep'}, 'Roche --in deep')]:
            with self.subTest(tool=tool):                                # the places the map reads, in the same copy, are still refused
                self.assertIn(ASK + ask, self.ask(tool, given))
        for agent, event in [('gemini', {'hook_event_name': 'BeforeTool', 'tool_name': 'glob', 'tool_input': {'pattern': '.claude/redesign/design/*'}}),
                             ('copilot', {'toolName': 'glob', 'toolArgs': json.dumps({'pattern': 'fixtures/*'})})]:
            with self.subTest(agent=agent):
                self.assertIsNone(hook({**event, 'cwd': str(self.root)}, agent, self.root))
        out = hook({'hook_event_name': 'BeforeTool', 'tool_name': 'glob', 'tool_input': {'pattern': '**/*.js', 'dir_path': 'src'}, 'cwd': str(self.root)}, 'gemini', self.root)
        self.assertTrue(out['reason'].endswith(ASK + "'src/**/*.js'"))

    def test_a_glob_is_refused_only_for_files_the_map_reads_under_its_pattern(self):
        """The ask answers a pattern as fnmatch on the path: a pattern it would answer with 0 files is not sent to it."""
        here = str(self.root).replace('\\', '/')
        for given, ask in [({'pattern': '**/*.js', 'path': 'src'}, "'src/**/*.js'"), ({'pattern': 'src/web/*'}, "'src/web/*'"),
                           ({'pattern': 'src/shop/cart.py'}, 'src/shop/cart.py'), ({'pattern': 'src'}, 'src'),
                           ({'pattern': f'{here}/src/web/*'}, "'src/web/*'"), ({'pattern': '**/*.md', 'path': here}, "'**/*.md'")]:
            with self.subTest(given=given):
                self.assertEqual(self.ask('Glob', given), ASK + ask)
        for given in [{'pattern': 'assets/*'}, {'pattern': '**/*.png'}, {'pattern': 'docs/*.md', 'path': 'src'}, {'pattern': 'src/**/*.rs'},
                      {'pattern': '*.js'}, {'pattern': 'src/nothing.py'}, {'pattern': '../*/x'}, {'pattern': '/tmp/*/x'}, {'pattern': 'map/*.yaml'}]:
            with self.subTest(given=given):                              # no file the map reads, or no glob the ask takes: goes ahead
                self.assertIsNone(self.ask('Glob', given))

    def test_after_the_end_of_options_the_first_word_is_the_pattern(self):
        """`--` ends the options: the word after it is the pattern even when it starts with `-`, as with -e, and the rest are places."""
        for line, same in [('grep -rn -- --coupon src', 'grep -rn -e --coupon src'),
                           ('grep -rnoE -- "--(a|b)" src --include=*.py', 'grep -rnoE -e "--(a|b)" src --include=*.py'),
                           ('rg -n -- --coupon src', 'rg -n -e --coupon src'), ('grep -rn -- coupon src/shop', 'grep -rn coupon src/shop')]:
            with self.subTest(line=line):
                self.assertEqual(bash(line, None, self.root), bash(same, None, self.root))
        self.assertIn(ASK + '--coupon --in src', bash('grep -rn -- --coupon src', None, self.root))
        for line in ['grep -rnoE -- "--(a|b)" .claude/redesign/design --include=*.html', 'rg -n -- --limit fixtures', 'grep -rn -- -x assets']:
            with self.subTest(line=line):                                # the place after the pattern is one the map leaves out
                self.assertIsNone(bash(line, None, self.root))

    @unittest.skipUnless(os.name == 'nt', 'the path forms of Windows and Git Bash')
    def test_a_windows_path_names_the_same_place_in_every_form(self):
        real = os.path.realpath(self.root)                                  # C:\Users\…\example
        drive, rest = os.path.splitdrive(real)
        win, rest = real.replace('\\', '/'), rest.replace('\\', '/')       # C:/Users/…/example and /Users/…/example
        low, cap = drive[0].lower(), drive[0].upper()
        forms = {'an MSYS path': f'grep -rn coupon /{low}{rest}/src', 'cd to an MSYS path': f'cd /{low}{rest} && grep -rn coupon src',
                 'cd to a path with /': f'cd {win} && grep -rn coupon src', 'a quoted backslash path': f"grep -rn coupon '{real}\\src'",
                 'an MSYS path, capital drive': f'grep -rn coupon /{cap}{rest}/src', 'cd to an MSYS path, capital drive': f'cd /{cap}{rest} && grep -rn coupon src',
                 'a path with a lower-case drive': f'grep -rn coupon {low}:{rest}/src', 'cd to a lower-case drive': f'cd {low}:{rest} && grep -rn coupon src',
                 'a cygdrive path': f'grep -rn coupon /cygdrive/{low}{rest}/src', 'cd to a cygdrive path': f'cd /cygdrive/{low}{rest} && grep -rn coupon src'}
        for agent in ('codex', None):
            plain = bash('grep -rn coupon src', agent, self.root)
            self.assertIn(ASK + 'coupon --in src', plain)
            for name, line in forms.items():
                with self.subTest(form=name, agent=agent):
                    self.assertEqual(bash(line, agent, self.root), plain)
# @end tests.guard.cases.places


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
            self.assertEqual(claude['hooks']['PreToolUse'][1]['matcher'], 'Bash|PowerShell|Read|Grep|Glob')
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


# @map tests.guard.cases.folding: a filter that cuts the ask's output is dropped, a cat that feeds a search is that search, and git grep in all its forms
class Folding(unittest.TestCase):
    def test_head_and_tail_are_not_applied_to_the_ask(self):
        """`| head -3` on the ask left its header and none of the code: the filters that cut by lines are dropped."""
        for command, ask in [('grep -n coupon src/shop/cart.py | head -3', 'coupon --in src/shop/cart.py'),
                             ('grep -rn coupon src | tail -2', 'coupon --in src'),
                             ('rg coupon src | head -20', 'coupon --in src'),
                             ('sed -n 20,40p src/shop/cart.py | head -3', 'src/shop/cart.py:20-40'),
                             ('ls src/web | head -3', 'src/web'),
                             ('grep -rn coupon src | head -5 | cut -c1-20', 'coupon --in src | cut -c1-20'),
                             ('grep -rn coupon src | sort | head -2', 'coupon --in src | sort')]:
            with self.subTest(command=command):
                self.assertEqual(bash(command, 'codex'), ASK + ask)
                self.assertEqual(bash(command), in_place(ask))

    def test_a_cat_that_feeds_a_search_is_that_search(self):
        for command, ask in [('cat src/shop/cart.py | grep coupon', 'coupon --in src/shop/cart.py'),
                             ('cat src/shop/cart.py | grep -n coupon | head -3', 'coupon --in src/shop/cart.py'),
                             ('cat src/shop/cart.py src/shop/prices.py | grep -i money', 'money --in src/shop/cart.py,src/shop/prices.py'),
                             ('cat docs/CART.md | head -3', 'docs/CART.md:1-3'),
                             ('cat src/shop/prices.py | tail -3', 'src/shop/prices.py:28-30'),
                             ('cat src/shop/cart.py | head -5 | grep coupon', 'src/shop/cart.py:1-5 | grep coupon')]:
            with self.subTest(command=command):
                self.assertEqual(bash(command, 'codex'), ASK + ask)
        for command in ['cat src/shop/cart.py | grep -c coupon', 'cat src/shop/cart.py | grep coupon | wc -l', 'cat src/shop/cart.py | wc -l',
                        'cat /tmp/x.log | grep error']:
            with self.subTest(command=command):
                self.assertIsNone(bash(command), command)                       # a count, or not the code

    def test_git_grep_in_all_its_forms(self):
        for command, ask in [('git grep -n coupon', 'coupon'), ('git grep -n coupon src', 'coupon --in src'),
                             ("git grep -n coupon -- '*.py'", "coupon --in '*.py'"), ("git grep -n coupon -- 'src/shop/*.py'", "coupon --in 'src/shop/*.py'"),
                             ('git grep -n -e coupon -- src/shop src/web', 'coupon --in src/shop,src/web'),
                             ('git grep -n coupon -- src ":!src/web"', 'coupon --in src'), ("git grep -n coupon -- 'src/**/*.js'", "coupon --in 'src/**/*.js'"),
                             ('git -C . grep -n coupon src', 'coupon --in src'), ('git --no-pager grep -n coupon src', 'coupon --in src'),
                             ('git -c color.ui=never grep -n coupon src | head -3', 'coupon --in src')]:
            with self.subTest(command=command):
                self.assertEqual(bash(command, 'codex'), ASK + ask)
        for command in ['git grep -c coupon', 'git grep -l coupon src', 'git grep -q coupon', 'git grep -n coupon | wc -l', 'git grep -n zzz /tmp']:
            with self.subTest(command=command):
                self.assertIsNone(bash(command), command)
# @end tests.guard.cases.folding


# @map tests.guard.cases.subagents: a subagent's read line is denied with its ask where the main session has it run in its place; guard.subagents in map.json chooses
SUB = {'agent_id': 'a1', 'agent_type': 'explorer'}


def tool(name, command, extra=None, root=None, cwd=None):
    """('allow', the line run in its place) or ('deny', what follows 'Run instead:') for a shell tool call; None when it goes ahead."""
    out = hook({'hook_event_name': 'PreToolUse', 'tool_name': name, 'tool_input': {'command': command}, 'cwd': str(cwd or root or ROOT), **(extra or {})}, None, root)
    o = out and out['hookSpecificOutput']
    if not o:
        return None
    return ('allow', o['updatedInput']['command']) if o['permissionDecision'] == 'allow' else ('deny', o['permissionDecisionReason'].split('Run instead:\n  ')[1])


class Subagents(unittest.TestCase):
    LINES = [('Bash', 'grep -rn coupon src', 'coupon --in src'), ('Bash', 'cat docs/CART.md', 'docs/CART.md'),
             ('Bash', 'sed -n 20,40p src/shop/cart.py | cut -c1-80', 'src/shop/cart.py:20-40 | cut -c1-80'),
             ('Bash', 'git grep -n coupon src', 'coupon --in src'), ('Bash', 'ls src/web; head -5 docs/CART.md', 'src/web docs/CART.md:1-5'),
             ('PowerShell', 'Select-String -Path src/shop/cart.py -Pattern coupon', 'coupon --in src/shop/cart.py'),
             ('PowerShell', 'Get-Content docs/CART.md', 'docs/CART.md')]

    def test_the_main_session_runs_the_line_and_a_subagent_is_denied_with_the_ask(self):
        for name, command, ask in self.LINES:
            with self.subTest(command=command):
                self.assertEqual(tool(name, command)[0], 'allow')
                self.assertEqual(tool(name, command, SUB), ('deny', ASK + ask))
                self.assertEqual(tool(name, command, {'agent_id': 'a1'}), ('deny', ASK + ask))           # the type is not needed
                self.assertEqual(tool(name, command, {'agent_type': 'main-agent'})[0], 'allow')          # --agent names the main session's type: no id, no subagent
                self.assertEqual(tool(name, command, {'agent_id': ''})[0], 'allow')

    def test_what_is_not_a_read_goes_ahead_for_a_subagent(self):
        for name, command in [('Bash', 'python3 -m unittest'), ('Bash', 'grep -c coupon src/shop/cart.py'), ('Bash', 'grep -rn coupon src | wc -l'),
                              ('Bash', "sed -i 's/TEN/10/' src/shop/prices.py"), ('Bash', 'cat /tmp/x.log'), ('PowerShell', 'cargo test'),
                              ('PowerShell', '(Get-Content docs/CART.md).Count')]:
            with self.subTest(command=command):
                self.assertIsNone(tool(name, command, SUB), command)

    def test_a_mixed_line_is_denied_whole_for_the_main_session_and_the_subagent(self):
        for extra in (None, SUB):
            out = tool('Bash', 'grep -rn coupon src; cargo test', extra)
            self.assertEqual(out, ('deny', ASK + 'coupon --in src; cargo test'))
            self.assertEqual(tool('PowerShell', 'Get-Content docs/CART.md; cargo test', extra), ('deny', ASK + 'docs/CART.md'))

    def test_map_json_chooses(self):
        tmp = pathlib.Path(os.path.realpath(tempfile.mkdtemp(prefix='map-subagents-')))
        try:
            root = tmp / 'example'
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns('__pycache__'))
            cfg = json.loads((root / 'map.json').read_text(encoding='utf-8'))
            for mode, want in [('translate', 'allow'), ('deny', 'deny'), (None, 'deny'), ('anything', 'deny')]:
                cfg['guard'] = {'skip': ['fixtures/']} | ({'subagents': mode} if mode else {})
                (root / 'map.json').write_text(json.dumps(cfg), encoding='utf-8')
                for name, command in [('Bash', 'grep -rn coupon src'), ('PowerShell', 'Get-Content docs/CART.md')]:
                    with self.subTest(mode=mode, command=command):
                        self.assertEqual(tool(name, command, SUB, root)[0], want)
                        self.assertEqual(tool(name, command, None, root)[0], 'allow')                 # the main session translates in every mode
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
# @end tests.guard.cases.subagents


# @map tests.guard.cases.powershell: the PowerShell tool: Select-String, Get-Content, Get-ChildItem and their aliases read through the map, in Windows paths too; the rest goes ahead
class PowerShell(unittest.TestCase):
    CASES = [
        ('Select-String -Path src/shop/cart.py -Pattern coupon', 'coupon --in src/shop/cart.py'),
        ('sls coupon src/shop/cart.py', 'coupon --in src/shop/cart.py'),
        ('Select-String coupon src/shop/cart.py,src/shop/prices.py', "coupon --in 'src/shop/cart.py,src/shop/prices.py'"),
        ('Select-String -Pattern coupon -LiteralPath src/shop/cart.py -CaseSensitive', 'coupon --in src/shop/cart.py'),
        ("sls 'cou.on' src/shop/cart.py", "'(?i)cou.on' --in src/shop/cart.py"), ("sls -CaseSensitive 'cou.on' src/shop/cart.py", "cou.on --in src/shop/cart.py"),
        ("Select-String -SimpleMatch 'a|b' docs/CART.md", "'(?i)a\|b' --in docs/CART.md"),
        ('Get-Content docs/CART.md', 'docs/CART.md'), ('gc docs/CART.md', 'docs/CART.md'), ('cat docs/CART.md', 'docs/CART.md'), ('type docs/CART.md', 'docs/CART.md'),
        ('Get-Content -Path docs/CART.md -Raw', 'docs/CART.md'), ('Get-Content -LiteralPath docs/CART.md', 'docs/CART.md'),
        ('Get-Content docs/CART.md -TotalCount 5', 'docs/CART.md:1-5'), ('gc docs/CART.md -Head 5', 'docs/CART.md:1-5'),
        ('Get-Content src/shop/prices.py -Tail 3', 'src/shop/prices.py:28-30'), ('gc src/shop/prices.py -Last 3', 'src/shop/prices.py:28-30'),
        ('Get-Content docs/CART.md | Select-Object -First 5', 'docs/CART.md:1-5'), ('cat docs/CART.md | select -First 5', 'docs/CART.md:1-5'),
        ('Get-Content src/shop/prices.py | Select-Object -Last 3', 'src/shop/prices.py:28-30'),
        ('Get-Content src/shop/cart.py | Select-String coupon', 'coupon --in src/shop/cart.py'),
        ('Get-Content src/shop/cart.py | Select-String coupon | Select-Object -First 3', 'coupon --in src/shop/cart.py'),
        ('Get-ChildItem src/web', 'src/web'), ('ls src/web', 'src/web'), ('dir src/web', 'src/web'), ('gci -Path src/web -Name', 'src/web'),
        ('Get-ChildItem -Recurse src', 'src'), ('gci -r src', 'src'),
        ('Get-ChildItem -Recurse src -Filter *.js', "'src/*.js'"), ('Get-ChildItem src -Recurse -Include *.js', "'src/*.js'"),
        ('Get-ChildItem -Recurse src/web -Filter *.js | Select-String money', "money --in 'src/web/*.js'"),
        ('Get-ChildItem -Recurse src/web | Select-Object -First 5', 'src/web'),
        ('Set-Location src; Get-Content shop/cart.py', 'src/shop/cart.py'), ('cd src; gc shop/cart.py', 'src/shop/cart.py'),
        ('grep -rn coupon src', 'coupon --in src'), ('git grep -n coupon src', 'coupon --in src'),               # the posix reads, when they are on the PATH
    ]

    def test_reads(self):
        for command, ask in self.CASES:
            with self.subTest(command=command):
                self.assertEqual(tool('PowerShell', command), ('allow', ASK + ask))
                self.assertEqual(tool('PowerShell', command, SUB), ('deny', ASK + ask))

    def test_each_read_of_a_line_is_an_ask_run_in_its_place(self):
        command = 'Get-Content docs/CART.md; Get-Content src/shop/cart.py -TotalCount 3'
        self.assertEqual(tool('PowerShell', command), ('allow', f'{ASK}docs/CART.md; {ASK}src/shop/cart.py:1-3'))
        self.assertEqual(tool('PowerShell', command, SUB), ('deny', f'{ASK}docs/CART.md src/shop/cart.py:1-3'))

    def test_windows_paths(self):
        here = str(ROOT / 'src' / 'shop' / 'cart.py')                       # as the OS writes it: backslashes on Windows
        for command in [f'Get-Content {here}', f"Get-Content '{here}'", f'Get-Content -Path "{here}"', f'gc {here.replace(chr(92), "/")}']:
            with self.subTest(command=command):
                self.assertEqual(tool('PowerShell', command), ('allow', ASK + 'src/shop/cart.py'))
        self.assertEqual(tool('PowerShell', f'Select-String -Path {here} -Pattern coupon'), ('allow', ASK + 'coupon --in src/shop/cart.py'))

    @unittest.skipUnless(os.name == 'nt', 'backslashes are Windows separators')
    def test_relative_paths_with_backslashes(self):
        for command, ask in [('Get-Content src\\shop\\cart.py', 'src/shop/cart.py'), ('Get-Content .\\src\\shop\\cart.py -TotalCount 3', 'src/shop/cart.py:1-3'),
                             ('Select-String -Path src\\shop\\*.py -Pattern coupon', "coupon --in 'src/shop/*.py'"), ('Get-ChildItem -Recurse .\\src\\web', 'src/web'),
                             ('Set-Location src\\shop; gc cart.py', 'src/shop/cart.py')]:
            with self.subTest(command=command):
                self.assertEqual(tool('PowerShell', command), ('allow', ASK + ask))

    def test_from_another_folder_the_line_runs_from_the_root(self):
        out = tool('PowerShell', 'Get-Content shop/cart.py', cwd=ROOT / 'src')
        self.assertEqual(out[0], 'allow')
        self.assertTrue(out[1].startswith('Push-Location -LiteralPath ') and out[1].endswith(f'try {{ {ASK}src/shop/cart.py }} finally {{ Pop-Location }}'), out)

    def test_what_is_not_a_read_goes_ahead(self):
        for command in ['(Get-Content src/shop/cart.py | Measure-Object -Line).Lines', '(Get-Content docs/CART.md).Count', 'Get-Content docs/CART.md | Measure-Object',
                        'Select-String -Quiet coupon src/shop/cart.py', 'Select-String -Path src/shop/cart.py -Pattern coupon -Quiet', 'Get-Content /tmp/x.log',
                        'Get-Content map.yaml', 'Get-Content ../README.md', 'Get-ChildItem', 'ls', 'Get-ChildItem -Recurse', 'Get-ChildItem /tmp',
                        'Get-ChildItem -Recurse src | Where-Object { $_.Length -gt 100 }', 'Get-ChildItem -Recurse src | Measure-Object',
                        'cargo test', 'git status --short', 'python3 -m unittest', 'Write-Output hi', 'Get-Date',
                        "(Get-Content src/shop/cart.py) -replace 'a','b' | Set-Content src/shop/cart.py", "Set-Content src/shop/cart.py 'x'; Get-Content src/shop/cart.py",
                        'Get-Content docs/CART.md | Out-File docs/COPY.md', "Add-Content docs/CART.md 'x'; Get-Content docs/CART.md", 'Remove-Item -Recurse src/shop',
                        '$x = 1', 'foreach ($f in 1..3) { $f }']:
            with self.subTest(command=command):
                self.assertIsNone(tool('PowerShell', command), command)

    def test_a_line_with_other_steps_is_denied_whole(self):
        for command, ask in [('Get-Content docs/CART.md; cargo test', 'docs/CART.md'), ('cargo test && Get-Content docs/CART.md', 'docs/CART.md'),
                             ('Get-Content docs/CART.md | ForEach-Object { $_.ToUpper() }', 'docs/CART.md'),
                             ("[System.IO.File]::ReadAllText('src/shop/cart.py')", 'src/shop/cart.py'),
                             ('Select-String coupon src/shop/cart.py | ForEach-Object { $_.Line }', 'coupon --in src/shop/cart.py')]:
            with self.subTest(command=command):
                self.assertEqual(tool('PowerShell', command), ('deny', ASK + ask))

    def test_bash_tool_lines_are_not_read_as_powershell(self):
        self.assertEqual(tool('Bash', 'cat docs/CART.md | head -3')[0], 'allow')
        self.assertIsNone(tool('Bash', 'Get-Content docs/CART.md'))
        self.assertIsNone(tool('Other', 'Get-Content docs/CART.md'))
# @end tests.guard.cases.powershell


if __name__ == '__main__':
    unittest.main()
