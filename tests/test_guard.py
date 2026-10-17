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


def bash(command):
    out = hook({'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': str(ROOT)})
    if not out:
        return None
    o = out['hookSpecificOutput']
    assert o['permissionDecision'] == 'deny'
    return o['permissionDecisionReason'].split('Run instead:\n  ')[1]


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
                self.assertEqual(bash(command), ASK + ask)

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


class Allowed(unittest.TestCase):
    def test_what_is_not_reading_goes_ahead(self):
        for command in ['python3 ../python/map.py ask total', 'python3 -m unittest discover -s tests', 'node tests/format.test.js',
                        "sed -i '' 's/a/b/' src/shop/cart.py", "cat > /tmp/x.txt <<'EOF'\ngrep -rn x src\nEOF",
                        'grep -c coupon src/shop/cart.py', 'grep -q coupon src/shop/cart.py && echo yes', 'rg -l coupon src',
                        'wc -l src/shop/cart.py', 'ls', 'cat map.yaml', 'head -5 map/shop.yaml', 'cat ../README.md',
                        'git diff src/shop/cart.py | head', 'find src -newer map.yaml -type f', 'tail -5 /tmp/run.log',
                        "python3 - <<'EOF'\np='src/shop/cart.py'\ns=open(p).read().replace('a','b')\nopen(p,'w').write(s)\nEOF",
                        "python3 -c \"import json;print(json.load(open('/tmp/out.json')))\""]:
            with self.subTest(command=command):
                self.assertIsNone(bash(command), command)

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
            subprocess.run(['python3', str(tmp / 'map-guard.py'), 'install', 'claude'], cwd=tmp, capture_output=True, text=True)
            self.assertEqual(len(json.loads((tmp / '.claude' / 'settings.json').read_text())['hooks']['PreToolUse']), 2)   # installed twice: once
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
# @end tests.guard.cases


if __name__ == '__main__':
    unittest.main()
