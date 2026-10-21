#!/usr/bin/env python3
# @map map.core.rules: the configuration, the comment forms of each language, the repository's files, their areas and the limits
"""map: a code map that coding agents read instead of grepping and reading whole files.

Every block of code carries a tag on the line above it, in the file's own comment form:

    JavaScript, CSS, Go, Rust, Java …   /* @map <area>.<topic>.<part>: what the block does */
    Python, shell, YAML, Ruby …         # @map <area>.<topic>.<part>: what the block does
    HTML, Vue, Svelte                   <!-- @map <area>.<topic>.<part>: what the block does -->

A block ends at `@end <id>` when other code follows it in the same file, else where the next block
outside it starts; blocks nest by id; one id may tag a piece in several files (its script, its styles,
its markup). The map is read from the tags and the code, never written by hand:

    python3 tools/map.py build            write map.yaml (the areas) and map/<area>.yaml (each area's components)
    python3 tools/map.py check            the rules, and that the map matches the code (for CI); exit 1 when not
    python3 tools/map.py brief <words>    where a task starts: the components the words name, their blocks and
                                          lines, what they declare, need and are needed by, their tests, docs and
                                          latest commits, then the first round of questions to ask, in one call
    python3 tools/map.py pack [recipe] <words>   brief (and the recipe's steps) with that first round already answered
    python3 tools/map.py ask <question> [<question> …] [--in <paths>] [--all] [--budget N]
                                          the one way to read and locate: every question of a round in one call, each
                                          answered whole: a block id (its code), an identifier (what it is, the code
                                          declaring it, every line naming it), a file (whole, or its outline), a folder,
                                          src/x.js:120-180, docs/X.md#heading, data.json#key, 'src/**/*.css',
                                          or any text (every line holding it, by block or section)
    python3 tools/map.py find <words>     blocks whose id, purpose or file has every word; an identifier first
    python3 tools/map.py history <id|file>   the commits that touched a block's lines (git log -L)
    python3 tools/map.py deps|impact <id|file>   what it imports; what imports it, and the tests to run
    python3 tools/map.py tests [paths | --changed]   the test files that reach these files, or the changed ones
    python3 tools/map.py recipe [name]    the steps of a change across layers (map.json, recipes), each at a block
    python3 tools/map.py plan <plan.md>   which parts of a plan can go to two agents at once
    python3 tools/map.py gaps [paths]     the files without tags, the lines outside blocks, the blocks to split
    python3 tools/map.py init             detect the areas, write map.json, print the section for AGENTS.md

Python 3.9 or later, the standard library only. Configuration, all of it optional, in map.json at the root
(python3 tools/map.py init writes one): see CONFIG in this file and docs/CONFIG.md. The same tool exists in
Node, Go and Rust, with the same answers (tests/conformance.py).
"""
import collections
import contextlib
import fnmatch
import hashlib
import io
import json
import math
import os
import pathlib
import re
import subprocess
import sys
import tempfile

VERSION = '1.0.0'
CONFIG = {
    'command': 'python3 tools/map.py',   # how agents run this file, as the map's answers and AGENTS.md say it
    'name': '',                          # the project's name in map.yaml; the root folder's name when empty
    'roots': ['src', 'lib', 'app', 'apps', 'packages', 'pkg', 'internal', 'cmd', 'services'],
    #                                    # a file under one of these takes its next folder as its area: src/shop/x.py → shop
    'areas': {},                         # a path prefix → its area, over the rule above: {"tools": "build", ".github": "ci", ".": "root"}
    'holds': {},                         # an area → what it holds, for map.yaml: {"shop": "the cart, prices and orders"}
    'describe': [],                      # files without code to read, each [pattern, kind, about]: [["*.png", "asset", "a picture"]]
    'ignore': [],                        # paths left out besides .gitignore and the usual folders: ["dist/", "vendor/", "*.min.js"]
    'forms': {},                         # extensions whose comment form the table below lacks: {".kt": "slash", ".nim": "hash"}
    'limits': {'untagged': 30, 'block': 16000, 'answer': 28000},   # non-blank lines outside blocks per tagged file; characters of a block's own code; characters of one ask's answers
    'tests': [],                         # globs of test files, over the usual names: ["tests/**", "**/*.spec.ts"]
    'recipes': {},                       # {name: {about, words, steps: [[block id or file, what to do], …], note}}
    'strict': False,                     # check also fails on files that carry no tags yet (CI, once everything is tagged)
    'guard': {'skip': []},               # paths map-guard.py leaves alone besides ignore: ["tests/fixtures/"]
}
FORMS = {'slash': [('/*', '*/'), ('//', '')], 'hash': [('#', '')], 'html': [('<!--', '-->'), ('/*', '*/'), ('//', '')],
         'dash': [('--', '')], 'semicolon': [(';', '')], 'percent': [('%', '')]}
EXT = {}
for _form, _exts in {
    'slash': '.js .mjs .cjs .jsx .ts .tsx .mts .cts .java .kt .kts .scala .groovy .go .rs .swift .c .h .cc .cpp .cxx .hpp '
             '.hh .cs .m .mm .php .dart .css .scss .less .proto .zig .d .v',
    'hash': '.py .pyi .rb .rake .sh .bash .zsh .fish .pl .pm .r .R .yml .yaml .toml .ps1 .ex .exs .nim .jl .cmake .tf .nix '
            '.cr .coffee .mk',
    'html': '.html .htm .xml .vue .svelte .astro .xhtml',
    'dash': '.sql .lua .hs .elm .ada .vhd',
    'semicolon': '.clj .cljs .cljc .edn .el .lisp .scm .rkt',
    'percent': '.erl .hrl .tex'}.items():
    for _e in _exts.split():
        EXT[_e] = _form
NAMED = {'Makefile': 'hash', 'GNUmakefile': 'hash', 'Dockerfile': 'hash', 'Containerfile': 'hash', 'Rakefile': 'hash',
         'Gemfile': 'hash', 'Justfile': 'hash', 'Vagrantfile': 'hash', 'CMakeLists.txt': 'hash', 'Jenkinsfile': 'slash'}
TEXT = set(EXT) | {'.md', '.markdown', '.rst', '.txt', '.adoc', '.json', '.ini', '.cfg', '.csv', '.editorconfig'}
DOCS = {'.md', '.markdown', '.rst', '.txt', '.adoc'}
SKIP = {'node_modules', 'dist', 'build', 'out', 'target', 'vendor', 'venv', '.venv', '__pycache__', '.git', '.hg', '.svn',
        '.tox', '.mypy_cache', '.pytest_cache', '.cache', 'coverage', '.idea', '.vscode', 'bower_components', '.next',
        '.nuxt', '.terraform', 'Pods', 'DerivedData', 'map'}
BINARY = re.compile(r'\.(png|jpe?g|gif|webp|ico|pdf|zip|gz|woff2?|ttf|otf|mp4|mp3|bin|exe|dylib|so)$', re.I)
ID = r'[a-z][a-z0-9-]*(?:\.[a-z0-9-]+)+'
LARGE = 1_000_000          # bytes: a text file past this is data (a lock, a bundle), listed and never searched or printed


def find_root(argv):
    """--root <path>, $MAP_ROOT, else the nearest folder at or above the working folder holding map.json, or .git;
    else the same above this script; else the working folder."""
    if '--root' in argv:
        i = argv.index('--root')
        root = pathlib.Path(argv[i + 1]).resolve()
        del argv[i:i + 2]
        return root
    if os.environ.get('MAP_ROOT'):
        return pathlib.Path(os.environ['MAP_ROOT']).resolve()
    cwd, here = pathlib.Path.cwd().resolve(), pathlib.Path(__file__).resolve().parent
    for mark in ('map.json', '.git'):
        for start in (cwd, here):
            for base in (start, *start.parents):
                if (base / mark).exists():
                    return base
    return cwd


ROOT = find_root(sys.argv)
MAP = ROOT / 'map.yaml'
ZONES = ROOT / 'map'
CFG = dict(CONFIG)
if (ROOT / 'map.json').is_file():
    try:
        _given = json.loads((ROOT / 'map.json').read_text(encoding='utf-8'))
    except ValueError as e:
        sys.exit(f'map.json: not JSON ({e})')
    for _k, _v in _given.items():
        if _k not in CONFIG:
            sys.exit(f'map.json: unknown setting "{_k}" (the settings: {", ".join(CONFIG)})')
        CFG[_k] = {**CONFIG[_k], **_v} if _k in ('limits', 'guard') else _v
CMD = CFG['command']
UNTAGGED, LARGEST = CFG['limits'].get('untagged', 30), CFG['limits'].get('block', 16000)


def slug(name):
    s = re.sub(r'[^a-z0-9-]+', '-', name.lower()).strip('-')
    return s if s and s[0].isalpha() else 'x' + s


def commas(n):
    return f'{n:,}'


def jstr(s):
    """A string as JSON writes it (what YAML reads as a string): only quotes, backslashes and control characters escaped."""
    out = []
    for ch in str(s):
        if ch == '"':
            out.append('\\"')
        elif ch == '\\':
            out.append('\\\\')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '\t':
            out.append('\\t')
        elif ch == '\b':
            out.append('\\b')
        elif ch == '\f':
            out.append('\\f')
        elif ord(ch) < 0x20:
            out.append('\\u%04x' % ord(ch))
        else:
            out.append(ch)
    return '"' + ''.join(out) + '"'


def jdump(v, indent=None, level=0):
    """A value as JSON: compact with ', ' and ': ' when indent is None, else one item per line, like Python's json."""
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if v is None:
        return 'null'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return jstr(v)
    items = list(v.items()) if isinstance(v, dict) else [(None, x) for x in v]
    if not items:
        return '{}' if isinstance(v, dict) else '[]'
    if indent is None:
        inner = ', '.join((jstr(k) + ': ' if k is not None else '') + jdump(x) for k, x in items)
        return ('{' if isinstance(v, dict) else '[') + inner + ('}' if isinstance(v, dict) else ']')
    pad, pad_in = ' ' * indent * level, ' ' * indent * (level + 1)
    inner = ',\n'.join(pad_in + (jstr(k) + ': ' if k is not None else '') + jdump(x, indent, level + 1) for k, x in items)
    return ('{\n' if isinstance(v, dict) else '[\n') + inner + '\n' + pad + ('}' if isinstance(v, dict) else ']')


def tokens(text):
    """The lowercase words of a name or a sentence: cartTotal → cart, total; HTMLParser → html, parser; a1 → a1."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c.isupper():
            if i + 1 < n and (text[i + 1].islower() or text[i + 1].isdigit()):
                j = i + 1
                while j < n and (text[j].islower() or text[j].isdigit()):
                    j += 1
                out.append(text[i:j].lower())
                i = j
                continue
            j = i
            while j < n and text[j].isupper():
                j += 1
            if j < n and text[j].islower() and j - 1 > i:
                j -= 1
            out.append(text[i:j].lower())
            i = j
        elif c.islower() or c.isdigit():
            j = i
            while j < n and (text[j].islower() or text[j].isdigit()):
                j += 1
            out.append(text[i:j])
            i = j
        else:
            i += 1
    return out


def words_of(text):
    return set(tokens(str(text)))


def bounded(text, word, left='', right=''):
    """Whether word occurs in text with no identifier character around it: not [\\w$] + left before it, not [\\w$] + right after."""
    start = 0
    while True:
        i = text.find(word, start)
        if i < 0:
            return False
        before = text[i - 1] if i else ''
        after = text[i + len(word)] if i + len(word) < len(text) else ''
        if not (before and (before.isalnum() or before in '_$' + left)) and not (after and (after.isalnum() or after in '_$' + right)):
            return True
        start = i + 1

# @end map.core.rules


# @map map.core.files: the repository's files and their comment forms, what .gitignore and map.json leave out, each file's area, the tags' patterns
def forms(path):
    """The comment forms a file writes its tags in, or None when it carries none (data, docs, pictures)."""
    name = path.rsplit('/', 1)[-1]
    suffix = pathlib.PurePath(name).suffix
    form = CFG['forms'].get(suffix, NAMED.get(name) or EXT.get(suffix))
    if form is None and not suffix and (ROOT / path).is_file():
        try:
            with open(ROOT / path, 'rb') as f:
                form = 'hash' if f.read(2) == b'#!' else None
        except OSError:
            form = None
    return FORMS.get(form) if form else None


def ignored(path):
    parts = path.split('/')
    if any(p in SKIP for p in parts[:-1]) or parts[-1] in ('map.yaml',):
        return True
    return any(path == p.rstrip('/') or path.startswith(p.rstrip('/') + '/') or fnmatch.fnmatch(path, p) for p in CFG['ignore'])


_files = None


def git_ignored():
    """The patterns of .gitignore, for a root that git does not list (not a repository, or a folder inside one)."""
    try:
        lines = (ROOT / '.gitignore').read_text(encoding='utf-8').split('\n')
    except OSError:
        return []
    return [p.strip() for p in lines if p.strip() and not p.startswith('#') and not p.startswith('!')]


def repo_files():
    """Every file of the repository: tracked, or new and not ignored, when the root is a git repository's; every file
    under the root otherwise, less what .gitignore and the usual folders leave out."""
    global _files
    if _files is None:
        found, top = [], ''
        try:
            top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        except OSError:
            top = ''
        if top and pathlib.Path(top).resolve() == ROOT.resolve():
            out = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT,
                                 capture_output=True, text=True).stdout.split('\0')
            found = [p for p in out if p and ((ROOT / p).is_file() and not (ROOT / p).is_symlink())]
        else:
            skip = git_ignored()

            def left_out(rel, is_dir):
                parts = rel.split('/')
                for p in skip:
                    folder, q = p.endswith('/'), p.strip('/')
                    if '/' in q:
                        if rel == q or rel.startswith(q + '/') or fnmatch.fnmatch(rel, q):
                            return True
                    elif any(fnmatch.fnmatch(n, q) for n in (parts if is_dir or not folder else parts[:-1])):
                        return True
                return False
            for base, dirs, names in os.walk(ROOT):
                rel = os.path.relpath(base, ROOT).replace(os.sep, '/')
                dirs[:] = sorted(d for d in dirs if d not in SKIP and not left_out(d if rel == '.' else f'{rel}/{d}', True))
                for n in sorted(names):
                    p = n if rel == '.' else f'{rel}/{n}'
                    if not os.path.islink(os.path.join(base, n)) and not left_out(p, False):
                        found.append(p)
        _files = sorted(p for p in found if not ignored(p))
    return _files


def described(path):
    for pattern, kind, about in CFG['describe']:
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path.rsplit('/', 1)[-1], pattern):
            return pattern, kind, about
    return None


def files():
    """Every file that may carry tags: a code file, not described as something else."""
    return [p for p in repo_files() if forms(p) and not described(p)]


def area_of(path):
    """The area a file belongs to: the configured prefix, else the folder under a root, else the top folder."""
    best = None
    for prefix, area in CFG['areas'].items():
        p = prefix.rstrip('/')
        if p in ('', '.'):
            if '/' not in path and best is None:
                best = ('', area)
        elif (path == p or path.startswith(p + '/')) and (best is None or len(p) > len(best[0])):
            best = (p, area)
    if best:
        return slug(best[1])
    parts = path.split('/')
    if len(parts) == 1:
        return 'root'
    if parts[0] in CFG['roots'] and len(parts) > 2:
        return slug(parts[1])
    return slug(parts[0].lstrip('.') or parts[0])


_areas = None


def areas():
    """Every area: those of the code files, the configured ones, and those described in holds."""
    global _areas
    if _areas is None:
        _areas = {area_of(p) for p in files()} | {slug(a) for a in CFG['areas'].values()} | set(CFG['holds'])
    return _areas


def tag_patterns(form):
    tag = '|'.join(r'^[ \t]*' + re.escape(o) + r'[ \t]*@(map|end)[ \t]+(' + ID + r')(?::[ \t]*(.*?))?[ \t]*'
                   + re.escape(c) + r'[ \t]*$' for o, c in form)
    looks = '|'.join(r'^[ \t]*' + re.escape(o) + r'[ \t]*@(?:map|end)\b' for o, _ in form)
    return re.compile(tag), re.compile(looks)


def tag_match(pattern, line):
    """(kind, id, purpose) of a tag line, whichever comment form it is written in."""
    m = pattern.match(line)
    if not m:
        return None
    g = m.groups()
    for i in range(0, len(g), 3):
        if g[i]:
            return g[i], g[i + 1], (g[i + 2] or '').strip()


def strip(text, path):
    """The text without its tag lines: what a build may put in its output."""
    form = forms(path)
    if not form:
        return text
    tag = tag_patterns(form)[0]
    return ''.join(line for line in text.splitlines(keepends=True) if not tag.match(line.rstrip('\n')))


def component(id_):
    return '.'.join(id_.split('.')[:2])


def is_test(path):
    name = path.rsplit('/', 1)[-1]
    if CFG['tests'] and any(fnmatch.fnmatch(path, g) for g in CFG['tests']):
        return True
    return (any(p in ('tests', 'test', 'spec', 'specs', '__tests__') for p in path.split('/')[:-1])
            or bool(re.search(r'(^|[._-])(test|tests|spec)([._-]|$)', name.rsplit('.', 1)[0] + '.')))
# @end map.core.files


# @map map.core.parse: a file's tags into blocks, the problems found on the way, and every block of the repository
def parse(path, text=None):
    """Blocks of one file (id, purpose, first and last line, own size), problems, lines outside any block."""
    lines = (text if text is not None else (ROOT / path).read_text(encoding='utf-8', errors='replace')).split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    blocks, open_, problems = [], [], []
    form = forms(path)
    if not form:
        return blocks, problems, []
    tag, looks = tag_patterns(form)
    known = areas()

    def close(upto, keep=None):
        while open_ and (keep is None or not (keep == open_[-1]['id'] or keep.startswith(open_[-1]['id'] + '.'))):
            open_.pop()['last'] = upto
    for n, line in enumerate(lines, 1):
        m = tag_match(tag, line)
        if not m:
            if looks.match(line):
                problems.append((n, 'a tag that cannot be read: "@map <id>: <purpose>" or "@end <id>", alone on its line'))
            elif line.startswith('#!') and not line.startswith('#![') and n > 1:
                problems.append((n, 'the #! line must stay the first line: put the tag below it'))
            continue
        kind, id_, purpose = m
        if kind == 'map':
            if id_.split('.')[0] not in known:
                problems.append((n, f'{id_}: its first word is not an area ({", ".join(sorted(known))}); '
                                    f'the file\'s area is {area_of(path)}'))
            if len(purpose.split()) < 3:
                problems.append((n, f'{id_} needs a purpose of three words or more'))
            if any(b['id'] == id_ for b in blocks):
                problems.append((n, f'{id_} appears twice in this file'))
            close(n - 1, keep=id_)
            b = {'id': id_, 'purpose': purpose, 'first': n, 'last': None, 'path': path}
            blocks.append(b)
            open_.append(b)
        elif not any(b['id'] == id_ for b in open_):
            problems.append((n, f'@end {id_} closes no open block'))
        else:
            while open_:
                b = open_.pop()
                b['last'] = n
                if b['id'] == id_:
                    break
    close(len(lines))
    depth = [0] * (len(lines) + 1)
    for b in blocks:
        for i in range(b['first'], b['last'] + 1):
            depth[i] += 1
    for b in blocks:
        mine = sum(1 for o in blocks if o['first'] <= b['first'] and o['last'] >= b['last'])
        b['own'] = sum(len(lines[i - 1]) + 1 for i in range(b['first'], b['last'] + 1) if depth[i] == mine)
        b['lines'] = b['last'] - b['first'] + 1
    outside = [i for i in range(1, len(lines) + 1) if not depth[i] and lines[i - 1].strip()]
    return blocks, problems, outside


_cache = None
CACHE = pathlib.Path(tempfile.gettempdir()) / 'code-map' / ('py-' + hashlib.sha1(str(ROOT).encode()).hexdigest()[:12] + '.json')


def facts(path):
    """A file's blocks, declarations, imports and problems, read once per change of the file (a cache in the temp folder)."""
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE.read_text(encoding='utf-8'))
            if _cache.get('version') != VERSION:
                _cache = {}
        except (OSError, ValueError):
            _cache = {}
        _cache['version'] = VERSION
        _cache.setdefault('files', {})
        _cache['dirty'] = False
    st = (ROOT / path).stat()
    key = f'{st.st_mtime_ns}:{st.st_size}:{area_of(path)}'
    kept = _cache['files'].get(path)
    if kept and kept['key'] == key:
        return kept
    text = (ROOT / path).read_text(encoding='utf-8', errors='replace')
    blocks, problems, outside = parse(path, text)
    f = {'key': key, 'blocks': blocks, 'problems': problems, 'outside': outside,
         'decls': declarations_in(path, text), 'imports': imports_in(path, text)}
    _cache['files'][path] = f
    _cache['dirty'] = True
    return f


def save_cache():
    if _cache and _cache.get('dirty'):
        try:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            tmp = CACHE.with_suffix(f'.{os.getpid()}.tmp')
            tmp.write_text(json.dumps({'version': VERSION, 'files': {p: f for p, f in _cache['files'].items()
                                                                     if p in set(repo_files())}}), encoding='utf-8')
            os.replace(tmp, CACHE)
        except OSError:
            pass


def everything():
    """All blocks of the repository, every problem with them, and the files that carry no tag yet."""
    all_blocks, all_problems, untagged = [], [], []
    for path in files():
        f = facts(path)
        all_blocks += [dict(b) for b in f['blocks']]
        all_problems += [(path, n, p) for n, p in f['problems']]
        if not f['blocks']:
            untagged.append(path)
        elif len(f['outside']) > UNTAGGED:
            all_problems.append((path, f['outside'][0], f'{len(f["outside"])} lines outside blocks (at most {UNTAGGED}); '
                                 'the first is this one'))
        for b in f['blocks']:
            if b['own'] > LARGEST:
                all_problems.append((path, b['first'], f'{b["id"]} holds {commas(b["own"])} characters of its own '
                                     f'(at most {commas(LARGEST)}): split it with blocks inside it'))
    return all_blocks, all_problems, untagged
# @end map.core.parse


# @map map.code.declarations: what each file declares (functions, classes, methods, values, headings), by the shape of each language, with each one's lines
KEYWORDS = {'if', 'for', 'while', 'switch', 'catch', 'return', 'else', 'do', 'new', 'function', 'sizeof', 'typeof', 'throw',
            'case', 'super', 'this', 'await', 'yield', 'delete', 'void', 'in', 'of', 'try', 'finally', 'with', 'elif',
            'until', 'unless', 'when', 'match', 'loop', 'defer', 'go', 'select', 'foreach', 'lock', 'using', 'fixed',
            'typedef', 'struct', 'union', 'enum'}
LANG = {'.js': 'js', '.mjs': 'js', '.cjs': 'js', '.jsx': 'js', '.ts': 'js', '.tsx': 'js', '.mts': 'js', '.cts': 'js', '.dart': 'js',
        '.go': 'go', '.rs': 'rust', '.java': 'jvm', '.kt': 'jvm', '.kts': 'jvm', '.scala': 'jvm', '.groovy': 'jvm', '.cs': 'jvm',
        '.swift': 'swift', '.rb': 'ruby', '.rake': 'ruby', '.php': 'php', '.c': 'c', '.h': 'c', '.cc': 'c', '.cpp': 'c',
        '.cxx': 'c', '.hpp': 'c', '.hh': 'c', '.m': 'c', '.mm': 'c', '.sh': 'sh', '.bash': 'sh', '.zsh': 'sh',
        '.ex': 'elixir', '.exs': 'elixir', '.lua': 'lua', '.sql': 'sql', '.pl': 'perl', '.pm': 'perl', '.py': 'py', '.pyi': 'py'}
BRACES = {'js', 'go', 'rust', 'jvm', 'swift', 'php', 'c', 'sh', 'perl'}
DECL = {
    'py': [(r'^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)', 'function'), (r'^\s*class\s+([A-Za-z_]\w*)', 'class'),
           (r'^([A-Za-z_]\w*)\s*(?::[^=]+?)?=', 'value')],
    'js': [(r'^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)', 'function'),
           (r'^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)', 'class'),
           (r'^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+?)?=\s*(?:async\s*)?(?:\([^)]*\)\s*(?::\s*[^=]+?)?=>|function\b|[A-Za-z_$][\w$]*\s*=>|class\b)', 'function'),
           (r'^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+?)?=\s*(?:\{|\[|new\s+\w+|[\'"`\d-]|require\(|await\b)', 'value'),
           (r'^\s*(?:export\s+)?(?:interface|type|enum|namespace)\s+([A-Za-z_$][\w$]*)', 'type'),
           (r'^\s{2,}(?:(?:public|private|protected|static|async|readonly|override|get|set|abstract)\s+)*\*?([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\([^)]*\)\s*(?::\s*[^{;]+)?\s*\{\s*$', 'method')],
    'go': [(r'^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)', 'function'), (r'^type\s+([A-Za-z_]\w*)\s+(?:struct|interface)', 'type'),
           (r'^(?:var|const)\s+([A-Za-z_]\w*)\s', 'value')],
    'rust': [(r'^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:const\s+)?(?:unsafe\s+)?fn\s+([A-Za-z_]\w*)', 'function'),
             (r'^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|type|mod|union)\s+([A-Za-z_]\w*)', 'type'),
             (r'^\s*impl(?:<[^>]*>)?\s+(?:[\w:<>]+\s+for\s+)?([A-Za-z_]\w*)', 'impl'),
             (r'^\s*(?:pub(?:\([^)]*\))?\s+)?(?:static|const)\s+([A-Za-z_]\w*)\s*:', 'value')],
    'jvm': [(r'^\s*(?:(?:public|private|protected|internal|static|final|abstract|sealed|open|data|inner|override|synchronized|native|default|case|partial)\s+)*(?:class|interface|enum|record|object|trait|struct)\s+([A-Za-z_]\w*)', 'class'),
            (r'^\s*(?:(?:public|private|protected|internal|static|final|abstract|override|synchronized|native|default|open|suspend|inline|operator|virtual|async|partial|unsafe|extern|new)\s+)+(?:fun\s+|def\s+)?(?:[\w<>\[\],.?]+\s+)?([A-Za-z_]\w*)\s*(?:<[^>]*>)?\s*\(', 'method'),
            (r'^\s+(?:fun|def)\s+(?:<[^>]*>\s*)?(?:[\w.]+\.)?([A-Za-z_]\w*)\s*\(', 'method')],
    'swift': [(r'^\s*(?:(?:public|private|internal|fileprivate|open|static|final|override|mutating|class|convenience|required)\s+)*(?:func|class|struct|enum|protocol|extension|actor)\s+([A-Za-z_]\w*)', 'function')],
    'ruby': [(r'^\s*def\s+(?:self\.)?([A-Za-z_]\w*[?!=]?)', 'method'), (r'^\s*(?:class|module)\s+([A-Z][\w:]*)', 'class')],
    'php': [(r'^\s*(?:(?:public|private|protected|static|abstract|final)\s+)*function\s+&?([A-Za-z_]\w*)', 'function'),
            (r'^\s*(?:abstract\s+|final\s+|readonly\s+)*(?:class|interface|trait|enum)\s+([A-Za-z_]\w*)', 'class')],
    'c': [(r'^[A-Za-z_][\w\s\*&:<>,]*?[\s\*&]([A-Za-z_]\w*)\s*\([^;{]*\)\s*(?:const\s*)?(?:\{|$)', 'function'),
          (r'^\s*(?:typedef\s+)?(?:struct|union|enum|class)\s+([A-Za-z_]\w*)\s*(?:\{|$)', 'type'),
          (r'^#define\s+([A-Za-z_]\w*)', 'value')],
    'sh': [(r'^\s*(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\s*\)\s*\{?', 'function'), (r'^\s*function\s+([A-Za-z_][\w-]*)', 'function')],
    'elixir': [(r'^\s*defp?\s+([a-z_]\w*[?!]?)', 'function'), (r'^\s*defmodule\s+([\w.]+)', 'class')],
    'lua': [(r'^\s*(?:local\s+)?function\s+([\w.:]+)', 'function')],
    'sql': [(r'^\s*create\s+(?:or\s+replace\s+)?(?:temp(?:orary)?\s+)?(?:table|view|function|procedure|index|trigger|type)\s+(?:if\s+not\s+exists\s+)?([\w."]+)', 'sql')],
    'perl': [(r'^\s*sub\s+([A-Za-z_]\w*)', 'function')],
}
PROTOTYPE = re.compile(r'\)\s*[;=]')


def brace_end(lines, i, most=1500):
    """The last line of the braced body starting on line i (1-based): strings and line comments skipped."""
    depth, quote, seen = 0, None, False
    for k in range(i - 1, min(len(lines), i - 1 + most)):
        s, j = lines[k], 0
        while j < len(s):
            c = s[j]
            if quote:
                if c == '\\':
                    j += 1
                elif c == quote:
                    quote = None
            elif c in '\'"`':
                quote = c
            elif s.startswith('//', j):
                break
            elif c == '{':
                depth, seen = depth + 1, True
            elif c == '}':
                depth -= 1
                if seen and depth == 0:
                    return k + 1
            j += 1
        if quote in ('"', "'"):
            quote = None
        if not seen and k > i and s.strip() and not s.lstrip().startswith(('{', '//', '/*', '*', '#')):
            return i                                  # no body: a prototype, an arrow one-liner, an abstract method
    return i if not seen else min(len(lines), i - 1 + most)


def indent_end(lines, i, indent):
    """The last line of an indented body (Python, Ruby, Elixir, Lua): to the line before the next at the same indent or less."""
    last = i
    for k in range(i, len(lines)):
        s = lines[k]
        if not s.strip():
            continue
        ind = len(s) - len(s.lstrip())
        if ind <= indent and k > i - 1:
            if re.match(r'\s*(?:end|\}|\))\b', s):
                return k + 1
            break
        last = k + 1
    return last


def declarations_in(path, text):
    """[{name, kind, first, last, what}] a file declares, read from the shape of its lines."""
    lines = text.split('\n')
    suffix = pathlib.PurePath(path).suffix.lower()
    if suffix in DOCS:
        out, fence = [], False
        for i, line in enumerate(lines, 1):
            if line.startswith('```'):
                fence = not fence
            elif not fence and (m := re.match(r'(#{1,6})\s+(.*)', line)):
                out.append({'name': m.group(2).strip(), 'kind': 'heading', 'first': i, 'last': i, 'what': line.strip()[:120]})
        return out
    lang = LANG.get(suffix)
    if not lang or lang not in DECL:
        return []
    out, rules = [], [(re.compile(rx, re.I if lang == 'sql' else 0), kind) for rx, kind in DECL[lang]]
    for i, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith(('//', '#', '*', '/*', '--', '"', "'")) and not (lang == 'c' and line.startswith('#define')):
            continue
        for rx, kind in rules:
            m = rx.match(line)
            if not m or m.group(1) in KEYWORDS:
                continue
            if lang == 'py' and kind == 'value' and (m.end() < len(line) and line[m.end()] == '='):
                continue                              # a comparison, not an assignment
            if lang == 'jvm' and kind == 'method' and PROTOTYPE.search(line, m.end() - 1):
                continue                              # a call or a field, not a method
            if lang == 'c' and kind == 'function' and (line[:1].isspace() or line.split()[0] in KEYWORDS):
                continue
            name, first = m.group(1), i
            if lang in BRACES and kind != 'value':
                last = brace_end(lines, i)
            elif kind == 'value':
                last = brace_end(lines, i) if line.rstrip().endswith(('{', '[', '(')) else i
            else:
                last = indent_end(lines, i, len(line) - len(line.lstrip()))
            if lang == 'py' and kind in ('function', 'class'):
                while first > 1 and lines[first - 2].lstrip().startswith('@'):
                    first -= 1                        # the decorators above it belong to it
            out.append({'name': name, 'kind': kind, 'first': first, 'last': max(i, last), 'what': line.strip()[:120]})
            break
    return out
# @end map.code.declarations


# @map map.code.imports: what each file imports, by language, resolved to the repository's own files
IMPORT = {
    'py': [r'^\s*from\s+([\w.]+)\s+import\b', r'^\s*import\s+([\w.]+(?:\s*,\s*[\w.]+)*)'],
    'js': [r'\bfrom\s+[\'"]([^\'"]+)[\'"]', r'\brequire\(\s*[\'"]([^\'"]+)[\'"]\s*\)', r'\bimport\(\s*[\'"]([^\'"]+)[\'"]\s*\)',
           r'^\s*import\s+[\'"]([^\'"]+)[\'"]'],
    'go': [r'^\s*import\s+(?:\w+\s+)?"([^"]+)"', r'^\s+(?:\w+\s+)?"([\w./-]+)"\s*$'],
    'rust': [r'^\s*(?:pub\s+)?use\s+((?:crate|super|self)::[\w:]+)', r'^\s*(?:pub\s+)?mod\s+(\w+)\s*;'],
    'jvm': [r'^\s*import\s+(?:static\s+)?([\w.]+)', r'^\s*using\s+([\w.]+)\s*;'],
    'ruby': [r'\brequire_relative\s+[\'"]([^\'"]+)[\'"]', r'\brequire\s+[\'"]([^\'"]+)[\'"]'],
    'php': [r'\b(?:require|include)(?:_once)?\s*\(?\s*(?:__DIR__\s*\.\s*)?[\'"]([^\'"]+)[\'"]', r'^\s*use\s+([\w\\]+)'],
    'c': [r'^\s*#\s*include\s+"([^"]+)"'],
    'sh': [r'^\s*(?:source|\.)\s+([^\s;|&]+)'],
    'css': [r'@import\s+(?:url\()?[\'"]([^\'"]+)[\'"]', r'@use\s+[\'"]([^\'"]+)[\'"]'],
    'html': [r'<script[^>]+src=["\']([^"\']+)["\']', r'<link[^>]+href=["\']([^"\']+\.css)["\']'],
}
IMPORT_LANG = dict(LANG, **{'.css': 'css', '.scss': 'css', '.less': 'css', '.html': 'html', '.htm': 'html', '.vue': 'js',
                            '.svelte': 'js', '.astro': 'js'})


def imports_in(path, text):
    """[(line, what)] of the imports a file writes, as written."""
    lang = IMPORT_LANG.get(pathlib.PurePath(path).suffix.lower())
    if not lang or lang not in IMPORT:
        return []
    out, rules = [], [re.compile(rx) for rx in IMPORT[lang]]
    in_block = False
    for i, line in enumerate(text.split('\n'), 1):
        if lang == 'go':
            if re.match(r'^\s*import\s*\(', line):
                in_block = True
                continue
            if in_block and line.strip() == ')':
                in_block = False
                continue
            if not in_block and not re.match(r'^\s*import\b', line):
                continue
        for rx in rules:
            for m in rx.finditer(line):
                for one in re.split(r'\s*,\s*', m.group(1)):
                    out.append((i, one.strip()))
    return out


def normpath(p):
    """a/./b/../c → a/c, as os.path.normpath does, with forward slashes."""
    out = []
    for seg in p.replace(os.sep, '/').split('/'):
        if seg in ('', '.'):
            continue
        if seg == '..':
            if out and out[-1] != '..':
                out.pop()
            else:
                out.append(seg)
        else:
            out.append(seg)
    return '/'.join(out) or '.'


class Resolver:
    """Imports resolved to the repository's files, by relative path, dotted module or path suffix."""

    def __init__(self, paths):
        self.paths = set(paths)
        self.by_suffix = collections.defaultdict(list)
        for p in paths:
            parts = p.split('/')
            for k in range(1, min(len(parts), 4) + 1):
                self.by_suffix['/'.join(parts[-k:])].append(p)
        self.gomod = ''
        if (ROOT / 'go.mod').is_file():
            m = re.search(r'^module\s+(\S+)', (ROOT / 'go.mod').read_text(encoding='utf-8', errors='replace'), re.M)
            self.gomod = m.group(1) if m else ''

    def file(self, p):
        p = normpath(p)
        return p if p in self.paths else None

    def candidates(self, base, exts):
        for e in exts:
            yield base + e
        for e in exts:
            yield base + '/index' + e
            yield base + '/__init__' + e
            yield base + '/mod' + e

    def resolve(self, path, what):
        folder = path.rsplit('/', 1)[0] if '/' in path else '.'
        lang = IMPORT_LANG.get(pathlib.PurePath(path).suffix.lower())
        exts = {'js': ['.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.mts', '.cts', '.vue', '.svelte'], 'py': ['.py'],
                'ruby': ['.rb'], 'rust': ['.rs'], 'css': ['.css', '.scss', '.less'], 'go': ['.go'],
                'jvm': ['.java', '.kt', '.scala', '.cs'], 'php': ['.php'], 'c': ['.h', '.hpp', '.c', '.cc', '.cpp'],
                'sh': ['', '.sh'], 'html': ['']}.get(lang, [''])
        found = set()
        if what.startswith(('./', '../', '/')) or (lang in ('c', 'css', 'html', 'sh', 'php', 'ruby') and '/' in what) \
                or (lang == 'js' and not what.startswith('.') and '/' in what and what.split('/')[0] in ('src', 'lib', 'app')):
            base = what.lstrip('/') if what.startswith('/') else folder + '/' + what
            for c in [base] + list(self.candidates(base, exts)):
                if f := self.file(c):
                    found.add(f)
                    break
        elif lang == 'py':
            dots = len(what) - len(what.lstrip('.'))
            name = what.lstrip('.')
            bases = []
            if dots:
                up = folder
                for _ in range(dots - 1):
                    up = up.rsplit('/', 1)[0] if '/' in up else '.'
                bases.append(up)
            else:
                bases = ['.', folder] + [r for r in CFG['roots'] if (ROOT / r).is_dir()]
            rel = name.replace('.', '/')
            for b in bases:
                for c in self.candidates((b + '/' + rel) if rel else b, ['.py']):
                    if f := self.file(c):
                        found.add(f)
                        break
                if found:
                    break
            if not found and rel:
                for c in self.by_suffix.get(rel + '.py', []) + self.by_suffix.get(rel + '/__init__.py', []):
                    found.add(c)
        elif lang == 'go' and self.gomod and what.startswith(self.gomod):
            rel = what[len(self.gomod):].strip('/')
            found |= {p for p in self.paths if p.endswith('.go') and (p.rsplit('/', 1)[0] if '/' in p else '.') == (rel or '.')}
        elif lang == 'rust':
            parts = what.replace('crate::', '').replace('self::', '').replace('super::', '').split('::')
            parts = [p for p in parts if p and p != 'crate']
            roots = ['src', folder]
            for k in range(len(parts), 0, -1):
                for r in roots:
                    for c in self.candidates(r + '/' + '/'.join(parts[:k]), ['.rs']):
                        if f := self.file(c):
                            found.add(f)
                if found:
                    break
        elif lang == 'jvm':
            parts = what.split('.')
            for k in range(len(parts), 1, -1):
                for e in exts:
                    for c in self.by_suffix.get('/'.join(parts[:k][-4:]) + e, []):
                        if c.endswith('/'.join(parts[:k]) + e):
                            found.add(c)
                if found:
                    break
        elif lang == 'php' and '\\' in what:
            parts = what.strip('\\').split('\\')
            for c in self.by_suffix.get('/'.join(parts[-2:]) + '.php', []) + self.by_suffix.get(parts[-1] + '.php', []):
                found.add(c)
        elif lang == 'ruby':
            for c in self.candidates('lib/' + what, ['.rb']):
                if f := self.file(c):
                    found.add(f)
        return found


class Graph:
    """The files joined by their imports, and the blocks and components those lines belong to."""

    def __init__(self, blocks):
        self.blocks = blocks
        self.by_file = collections.defaultdict(list)
        for b in blocks:
            self.by_file[b['path']].append(b)
        self.purpose = {}
        for b in sorted(blocks, key=lambda b: b['path']):
            self.purpose.setdefault(b['id'], b['purpose'])
        self.main = {}                                   # a file's main component: the one holding most of its lines
        for p, bs in self.by_file.items():
            n = collections.Counter()
            for b in bs:
                n[component(b['id'])] += b['lines']
            self.main[p] = n.most_common(1)[0][0]
        paths = [p for p in repo_files() if pathlib.PurePath(p).suffix.lower() in TEXT or forms(p)]
        r = Resolver(paths)
        self.file_edges = collections.defaultdict(set)   # path → the files it imports
        self.edges = collections.defaultdict(int)        # (component, component) → how many import lines
        for p in files():
            for line, what in facts(p)['imports']:
                for target in sorted(r.resolve(p, what)):
                    if target == p:
                        continue
                    self.file_edges[p].add(target)
                    src = self.at(p, line) or self.main.get(p)
                    dst = self.main.get(target)
                    if src and dst and component(src) != dst:
                        self.edges[(component(src), dst)] += 1
        self.importers = collections.defaultdict(set)
        for p, ts in self.file_edges.items():
            for t in ts:
                self.importers[t].add(p)

    def at(self, path, line):
        inside = [b for b in self.by_file.get(path, ()) if b['first'] <= line <= b['last']]
        return max(inside, key=lambda b: (b['first'], -b['last']))['id'] if inside else None
# @end map.code.imports


# @map map.core.write: map.yaml, the central map of the areas, and map/<area>.yaml, each area's components; build and check
def header(name, blocks, per_file):
    """A component with no block of its own name: what its first file's first block says, when the file is all of it."""
    mine = [b for b in blocks if component(b['id']) == name]
    first = min(mine, key=lambda b: (b['path'], b['first']), default=None)
    if first and per_file[first['path']] == len([b for b in mine if b['path'] == first['path']]):
        return first['purpose']
    return None


ID_LIKE = re.compile(r'[a-z][a-z0-9-]*\.[a-z0-9-]+')


def ids_in(text):
    """The id-like words of a text (shop.cart), each bounded: no letter, digit or dot before it, none or a hyphen after."""
    out = set()
    for m in ID_LIKE.finditer(text):
        before = text[m.start() - 1] if m.start() else ''
        after = text[m.end()] if m.end() < len(text) else ''
        if not (before and (before.isalnum() or before in '_.')) and not (after and (after.isalnum() or after in '_-')):
            out.add(m.group(0))
    return out


def docs_naming(comps):
    """The documents that name a component, by its id or by one of its files."""
    paths = [p for p in repo_files() if pathlib.PurePath(p).suffix.lower() in DOCS and (ROOT / p).stat().st_size < LARGE]
    names = collections.Counter(f.rsplit('/', 1)[-1] for c in comps.values() for f in c['files'])
    all_files = {f for c in comps.values() for f in c['files']}
    found = {}
    for path in paths:
        text = (ROOT / path).read_text(encoding='utf-8', errors='replace')
        said = ids_in(text) & set(comps)
        hit = {f for f in all_files if f in text or (names[f.rsplit('/', 1)[-1]] == 1 and '`' + f.rsplit('/', 1)[-1] + '`' in text)}
        found[path] = said | {name for name, c in comps.items() if c['files'] & hit}
    return found


def test_files():
    return [p for p in repo_files() if is_test(p) and (forms(p) or pathlib.PurePath(p).suffix.lower() in TEXT)]


def tests_reaching(g, comps):
    """{component: {test file: why}}: the tests that import one of its files, or name one of its files or ids."""
    out = collections.defaultdict(dict)
    files_of = {}
    for name, c in comps.items():
        for f in c['files']:
            files_of.setdefault(f, set()).add(name)
    for t in test_files():
        for target in sorted(g.file_edges.get(t, ())):
            for name in sorted(files_of.get(target, ())):
                out[name][t] = 'imports ' + target
        try:
            text = (ROOT / t).read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for name, c in comps.items():
            if t in out[name]:
                continue
            if any(f in text for f in c['files'] if f != t) or (name in text and bounded(text, name, '.', '-')):
                out[name][t] = 'names it'
    return out


def components(blocks, g):
    """Every component: what it is, its parts, files, declarations, needs and what needs it, tests and docs."""
    purpose = {}
    for b in sorted(blocks, key=lambda b: b['path']):
        purpose.setdefault(b['id'], b['purpose'])
    comps = {}
    for b in blocks:
        c = comps.setdefault(component(b['id']), {'files': set(), 'parts': set(), 'needs': set(), 'by': set(), 'docs': set(),
                                                  'declares': [], 'blocks': 0, 'lines': 0})
        c['files'].add(b['path'])
        c['blocks'] += 1
        c['lines'] += b['lines']
        if b['id'].count('.') > 1:
            c['parts'].add(b['id'].split('.')[2])
    per_file = collections.Counter(b['path'] for b in blocks)
    first_of = {}
    for b in sorted(blocks, key=lambda b: (b['path'], b['first'])):
        first_of.setdefault(component(b['id']), b['purpose'])
    for name, c in comps.items():
        c['what'] = purpose.get(name) or header(name, blocks, per_file) or purpose.get(name + '.api') or first_of.get(name, '')
    for (s, d) in g.edges:
        if s in comps and d in comps:
            comps[s]['needs'].add(d)
            comps[d]['by'].add(s)
    for p in files():
        for d in facts(p)['decls']:
            if d['kind'] in ('function', 'class', 'method') and (b := g.at(p, d['first'])):
                comps[component(b)]['declares'].append(d['name'])
    for name, found in tests_reaching(g, comps).items():
        comps[name]['tests'] = found
    for name in comps:
        comps[name].setdefault('tests', {})
    for doc, named in docs_naming(comps).items():
        for c in named:
            comps[c]['docs'].add(doc)
    return comps


def areas_of(comps):
    out = collections.defaultdict(list)
    for name in sorted(comps):
        out[name.split('.')[0]].append(name)
    return out


def central(comps, untagged):
    """map.yaml: one line per area with what it needs from the others, then the other files, by folder."""
    name = CFG['name'] or ROOT.name
    out = [f'# The map of {name}: the areas, what each needs from the others (read from imports), and where each one\'s map is.',
           f'# Generated by `{CMD} build`; never edit it. `{CMD} check` fails when it is out of date.',
           '# An area\'s components, what each needs and what needs it: map/<area>.yaml.',
           f'# Reading and finding: `{CMD} brief <words>`, then `{CMD} ask <questions>` (AGENTS.md, "Finding code").',
           'version: 1', '', 'areas:',
           '  # needs: how many of its components import a component of that area; needed_by: the other way']

    def count(area, mine, key):
        n = collections.Counter(o.split('.')[0] for c in mine for o in comps[c][key] if o.split('.')[0] != area)
        return '{' + ', '.join(f'{k}: {v}' for k, v in sorted(n.items(), key=lambda x: (-x[1], x[0]))) + '}'
    for area, mine in areas_of(comps).items():
        nf = len({f for c in mine for f in comps[c]['files']})
        holds = CFG['holds'].get(area)
        out.append(f'  {area}: {{' + (f'holds: {jstr(holds)}, ' if holds else '') + f'components: {len(mine)}, files: {nf}, '
                   f'blocks: {sum(comps[c]["blocks"] for c in mine)}, map: map/{area}.yaml, '
                   f'needs: {count(area, mine, "needs")}, needed_by: {count(area, mine, "by")}}}')
    if untagged:
        out += ['', 'untagged:', f'  # code files that carry no tag yet, by folder ({CMD} gaps lists them)']
        groups = collections.Counter((p.rsplit('/', 1)[0] + '/' if '/' in p else '.') for p in untagged)
        for folder, n in sorted(groups.items()):
            out.append(f'  {jstr(folder)}: {n}')
    out += ['', 'other:', '  # files without code to read, by folder; each kind described in map.json (describe)']
    groups = collections.defaultdict(list)
    for path in sorted(set(repo_files()) | {'map.yaml'} | {f'map/{a}.yaml' for a in areas_of(comps)}):
        if not forms(path) or described(path):
            groups[path.split('/')[0] + '/' if '/' in path else '.'].append(path)
    for folder, paths in sorted(groups.items()):
        names = [p.split('/', 1)[1] if folder != '.' else p for p in paths]
        kinds = collections.Counter((described(p) or (None, pathlib.PurePath(p).suffix.lstrip('.') or 'file', None))[1] for p in paths)
        if len(names) <= 8 or folder == '.':
            out.append(f'  {jstr(folder)}: [{", ".join(jstr(n) for n in names)}]')
        else:
            out.append(f'  {jstr(folder)}: {{files: {len(paths)}, ' + ', '.join(f'{k}: {v}' for k, v in sorted(kinds.items())) + '}')
    return '\n'.join(out) + '\n'


def zone(area, comps):
    """map/<area>.yaml: one line per component of the area."""
    li = lambda xs: '[' + ', '.join(sorted(xs)) + ']'                                  # noqa: E731
    holds = CFG['holds'].get(area)
    out = [f'# The {area} area of the code map' + (f': {holds}.' if holds else '.'),
           f'# One line per component: what it is, its parts ({CMD} ask <component>.<part>), its files, what it',
           '# declares, the components it needs (imports) and those that need it, the tests that reach it (by folder)',
           '# and the docs that name it.',
           f'# Generated by `{CMD} build`; never edit it. All the areas: map.yaml.', '', f'{area}:']
    for name in areas_of(comps)[area]:
        c = comps[name]
        parts = ([f'what: {jstr(c["what"])}'] if c['what'] else []) + ([f'parts: {li(c["parts"])}'] if c['parts'] else [])
        parts.append(f'files: [{", ".join(jstr(f) for f in sorted(c["files"]))}]')
        if c['declares']:
            seen = list(dict.fromkeys(c['declares']))
            parts.append(f'declares: [{", ".join(seen[:8])}' + (f', … {len(seen) - 8} more]' if len(seen) > 8 else ']'))
        for key, label in (('needs', 'needs'), ('by', 'needed_by')):
            if c[key]:
                parts.append(f'{label}: {li(c[key])}')
        if c['tests']:
            folders = collections.Counter((t.split('/')[0] if '/' in t else '.') for t in c['tests'])
            parts.append('tests: {' + ', '.join(f'{k}: {v}' for k, v in sorted(folders.items())) + '}')
        if c['docs']:
            parts.append(f'docs: {li(c["docs"])}')
        out.append(f'  {name}: {{{", ".join(parts)}}}')
    return '\n'.join(out) + '\n'


def written(blocks, comps, untagged):
    texts = {MAP: central(comps, untagged)}
    for area in areas_of(comps):
        texts[ZONES / f'{area}.yaml'] = zone(area, comps)
    return texts


def build():
    blocks, problems, untagged = everything()
    comps = components(blocks, Graph(blocks))
    texts = written(blocks, comps, untagged)
    ZONES.mkdir(exist_ok=True)
    for path, text in texts.items():
        if not path.exists() or path.read_text(encoding='utf-8') != text:
            path.write_text(text, encoding='utf-8')
    for old in ZONES.glob('*.yaml'):
        if old not in texts:
            old.unlink()
    save_cache()
    print(f'{len(blocks)} blocks in {len({b["path"] for b in blocks})} files, {len(comps)} components, '
          f'{len(areas_of(comps))} areas; {len(untagged)} files without tags; {len(problems)} problems')
    return problems


def problems():
    """What check and CI see: the rules, the recipes' blocks, and the map current."""
    blocks, found, untagged = everything()
    if CFG['strict']:
        found += [(p, 0, 'no blocks: tag this file') for p in untagged]
    comps = components(blocks, Graph(blocks))
    for path, text in written(blocks, comps, untagged).items():
        if not path.exists() or path.read_text(encoding='utf-8') != text:
            found.append((str(path.relative_to(ROOT)), 0, f'out of date: run {CMD} build'))
    if ZONES.is_dir():
        for old in sorted(ZONES.glob('*.yaml')):
            if old.stem not in areas_of(comps):
                found.append((str(old.relative_to(ROOT)), 0, f'no such area: run {CMD} build'))
    found += recipe_problems(blocks)
    save_cache()
    return found, len(blocks), len(untagged)
# @end map.core.write


# @map map.query.find: find by words or by an identifier, where, gaps, history from git, deps and impact from imports, tests
def identifier(word):
    """A word written as code names things: renderCart, cart-items, data-price, MAX_ITEMS, #total, .cart-row, --color-warn."""
    return bool(re.search(r'[a-z][A-Z]|[A-Za-z0-9]-[A-Za-z0-9]|_|^[#.][A-Za-z]|^--', word))


SHOWN = 15


def find(words):
    blocks, _, _ = everything()
    raw = [x for w in words for x in w.split()]
    words = [x.lower() for x in raw if not identifier(x) or len(raw) == 1]
    said = False
    if len(raw) == 1 or any(identifier(w) for w in raw):
        repo = Repo(blocks)
        for w in raw:
            if len(raw) == 1 or identifier(w):
                for d in declarations(repo, w.lstrip('#.'))[:5]:
                    rec('declarations', {'name': w, 'what': d[3], 'in': repo.where(d[0], d[1]) or d[0], 'file': d[0], 'first': d[1], 'last': d[2]})
                    print(f'{w}: {d[3]}, declared in {repo.where(d[0], d[1]) or d[0]}  {d[0]}:{d[1]}-{d[2]}')
                    said = True

    def has(text, w):
        return any(h.startswith(w) for h in re.findall(r'[a-z0-9]+', text.lower()))

    def hit(b):
        return all(has(b['id'] + ' ' + b['purpose'] + ' ' + b['path'], w) for w in words)

    def rank(b):
        return (-sum(has(b['id'], w) for w in words), is_test(b['path']), -sum(has(b['purpose'], w) for w in words), b['path'], b['first'])
    hits = sorted((b for b in blocks if words and hit(b)), key=rank)
    if said and len(raw) == 1:
        hits = [b for b in hits if has(b['id'], words[0])]
    for b in hits[:SHOWN]:
        purpose = b['purpose'] if len(b['purpose']) <= 120 else b['purpose'][:b['purpose'].rfind(' ', 0, 119)] + '…'
        rec('blocks', {'id': b['id'], 'file': b['path'], 'first': b['first'], 'last': b['last'], 'lines': b['lines'], 'purpose': b['purpose']})
        print(f'{b["id"]:<44} {b["path"]}:{b["first"]}-{b["last"]} ({b["lines"]} lines)  {purpose}')
    if len(hits) > SHOWN:
        print(f'… {len(hits) - SHOWN} more: add a word to narrow them')
    if not hits and not said:
        print(f"No block matches. Try fewer words, or the code's text: {CMD} ask '<text>'")
    return max(0, len(hits) - SHOWN)


def matching(id_, blocks):
    return [b for b in blocks if b['id'] == id_ or b['id'].startswith(id_ + '.')]


def where(id_):
    hits = matching(id_, everything()[0])
    for b in hits:
        print(f'{b["id"]:<44} {b["path"]}:{b["first"]}-{b["last"]} ({b["lines"]} lines)')
    if not hits:
        sys.exit(f'No block {id_}. Search with: {CMD} find <words>')


def gaps(paths):
    every = files()
    chosen = [f for f in every if any(f == p or f.startswith(p.rstrip('/') + '/') for p in paths)] if paths else every
    untagged, printed = 0, False
    for path in chosen:
        f = facts(path)
        blocks, problems_, outside = f['blocks'], f['problems'], f['outside']
        big = [b for b in blocks if b['own'] > LARGEST]
        elsewhere = sorted({b['id'].split('.')[0] for b in blocks} - {area_of(path)})
        if not blocks:
            untagged, printed = untagged + 1, True
            decls = [d['name'] for d in f['decls'] if d['kind'] in ('function', 'class', 'method')]
            print(f'{path}: no tags ({len(outside)} lines; area {area_of(path)}' + (f'; declares {", ".join(decls[:6])}' + (' …' if len(decls) > 6 else '') if decls else '') + ')')
        elif len(outside) > UNTAGGED or big or problems_ or elsewhere:
            printed = True
            print(f'{path}: {len(blocks)} blocks, {len(outside)} lines outside' + (f' (from line {outside[0]})' if outside else ''))
            if elsewhere:
                print(f'  note: blocks of {", ".join(elsewhere)} live in this file')
            for b in big:
                print(f'  split {b["id"]} (lines {b["first"]}-{b["last"]}, {commas(b["own"])} characters of its own)')
            for n, p in problems_:
                print(f'  line {n}: {p}')
    save_cache()
    if untagged:
        print(f'{untagged} of {len(chosen)} files carry no tag: https://github.com/mars1571/grepless/blob/main/docs/TAGGING.md says how to tag them with an agent')
    elif not printed:
        print(f'All {len(chosen)} code files are tagged, no block to split, no problem.')


def git(*args):
    try:
        return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True).stdout
    except OSError:
        return ''


def history(what):
    """The commits that touched a block's lines (git log -L), or a file."""
    blocks, _, _ = everything()
    hits = [b for b in blocks if b['id'] == what] or matching(what, blocks)[:3]
    if not hits and (ROOT / what).is_file():
        hits = [{'id': what, 'path': what, 'first': None}]
    if not hits:
        sys.exit(f'No block or file {what}. Search with: {CMD} find <words>')
    for b in hits:
        if b['first'] is None:
            out = git('log', '-n', '12', '--format=%h %ad %s', '--date=short', '--', b['path'])
        else:
            out = git('log', '-s', '-n', '12', '--format=%h %ad %s', '--date=short', f'-L{b["first"]},{b["last"]}:{b["path"]}')
        lines = [ln for ln in out.split('\n') if ln.strip()]
        print(f'{b["id"]}  {b["path"]}' + (f':{b["first"]}-{b["last"]}' if b['first'] else '') + f': {len(lines)} commits' + (', latest first' if lines else ' (not in git, or no history yet)'))
        for ln in lines:
            print('  ' + ln)


def deps(what):
    blocks, _, _ = everything()
    g = Graph(blocks)
    paths = {b['path'] for b in matching(what, blocks)} or ({what} if what in g.file_edges or (ROOT / what).is_file() else set())
    if not paths:
        sys.exit(f'No block or file {what}.')
    for p in sorted(paths):
        ts = sorted(g.file_edges.get(p, ()))
        print(f'{p} imports {len(ts)} files of the repository' + (':' if ts else ''))
        for t in ts:
            print(f'  {t}  {g.main.get(t, "")}')


def reaching(g, paths, names=()):
    """The test files that import these files (one step, then one more) or name one of them or of the names."""
    direct = {s for p in paths for s in g.importers.get(p, ())} - set(paths)
    second = {s for p in direct for s in g.importers.get(p, ())} - set(paths) - direct
    found = {}
    for t in test_files():
        if t in paths:
            found[t] = 'the test itself'
        elif t in direct:
            found[t] = 'imports ' + ', '.join(sorted(set(g.file_edges[t]) & set(paths))[:2])
        elif t in second:
            found[t] = 'imports what imports it'
    short_names = {p.rsplit('/', 1)[-1] for p in paths if len(p.rsplit('/', 1)[-1]) > 6} | set(names)
    for t in test_files():
        if t in found:
            continue
        try:
            text = (ROOT / t).read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        if any(p in text for p in paths) or any(bounded(text, n, '.', '-') for n in short_names):
            found[t] = 'names it'
    return found


def impact(what):
    """What imports it (one step, then one more), and the tests to run."""
    blocks, _, _ = everything()
    g = Graph(blocks)
    mine = {b['path'] for b in matching(what, blocks)} or ({what} if (ROOT / what).is_file() else set())
    if not mine:
        sys.exit(f'No block or file {what}.')
    direct = {s for p in mine for s in g.importers.get(p, ())} - mine
    second = {s for p in direct for s in g.importers.get(p, ())} - mine - direct
    print(f'{len(direct)} files import {what} directly' + (':' if direct else '.'))
    for p in sorted(direct):
        print(f'  {p}  {g.main.get(p, "")}')
    if second:
        print(f'{len(second)} more import those: ' + ', '.join(sorted(second)[:12]) + (' …' if len(second) > 12 else ''))
    tests = sorted(reaching(g, sorted(mine), {component(b['id']) for b in matching(what, blocks)}))
    print(f'Tests that reach it ({len(tests)}): ' + (' '.join(tests) if tests else 'none import or name it; run the suite'))


def changed():
    """The files git status shows: staged, unstaged and new."""
    out = []
    for e in git('status', '--porcelain=v1', '-z', '--untracked-files=all').split('\0'):
        if len(e) > 3:
            out.append(e[3:].split('\0')[0])
    return out


def tests(args):
    paths = changed() if args == ['--changed'] or not args else args
    if not paths:
        print('Nothing changed: no test to run.')
        return
    blocks, _, _ = everything()
    g = Graph(blocks)
    chosen = {}
    for p in sorted(paths):
        ids = {component(b['id']) for b in g.by_file.get(p, ())}
        found = reaching(g, [p], ids)
        for t, why in found.items():
            chosen.setdefault(t, why)
        print(f'  {p}: {len(found)} test file{"s" if len(found) != 1 else ""}')
    if chosen:
        print('Run: ' + ' '.join(sorted(chosen)))
        for t, why in sorted(chosen.items()):
            print(f'  {t}  ({why})')
    else:
        print('No test file imports or names these files.')
# @end map.query.find


# @map map.ask.repo: what ask reads (the tagged code and the repository's text), and the block or section holding a line
MANY = 120           # lines found that print as they are; past them, the first ones and a count per place
SMALL = 150          # a file or a block this short is printed whole when asked for; a longer one, its outline
LONG = 80            # a declaration this long is printed whole with a name asked for; a longer one, its start
CUT = 240            # a found line longer than this shows its start
FEW = 12             # the lines naming a name that print whole; past them, their numbers by place


class Repo:
    """The files ask reads, their blocks and their text, read once per call."""

    def __init__(self, blocks=None):
        self.blocks = blocks if blocks is not None else everything()[0]
        self.files = [p for p in repo_files() if (pathlib.PurePath(p).suffix.lower() in TEXT or forms(p)) and not BINARY.search(p)]
        self.known = set(self.files)
        self.by_file = collections.defaultdict(list)
        for b in self.blocks:
            self.by_file[b['path']].append(b)
        self._text, self._sections, self._decls = {}, {}, None

    def lines(self, path):
        if path not in self._text:
            lines = (ROOT / path).read_text(encoding='utf-8', errors='replace').split('\n')
            if len(lines) > 1 and lines[-1] == '':
                lines.pop()
            self._text[path] = lines
        return self._text[path]

    def holder(self, path, n):
        inside = [b for b in self.by_file.get(path, ()) if b['first'] <= n <= b['last']]
        return max(inside, key=lambda b: (b['first'], -b['last'])) if inside else None

    def sections(self, path):
        """A document's headings: [(first, last, level, title)], each section to the next of its level or above."""
        if path not in self._sections:
            heads, fence = [], False
            for i, line in enumerate(self.lines(path), 1):
                if line.startswith('```'):
                    fence = not fence
                elif not fence and (m := re.match(r'(#{1,6})\s+(.*)', line)):
                    heads.append((i, len(m.group(1)), m.group(2).strip()))
            out = []
            for k, (i, level, title) in enumerate(heads):
                last = next((j - 1 for j, lv, _ in heads[k + 1:] if lv <= level), len(self.lines(path)))
                out.append((i, last, level, title))
            self._sections[path] = out
        return self._sections[path]

    def section(self, path, n):
        inside = [s for s in self.sections(path) if s[0] <= n <= s[1]]
        return max(inside, key=lambda s: s[0]) if inside else None

    def decls(self):
        """Every declaration of the code files, by name."""
        if self._decls is None:
            self._decls = collections.defaultdict(list)
            for p in files():
                for d in facts(p)['decls']:
                    if d['kind'] != 'heading':
                        self._decls[d['name']].append((p, d['first'], d['last'], f'{d["kind"]} {d["name"]}', d['what']))
        return self._decls

    def where(self, path, a, b=None):
        if pathlib.PurePath(path).suffix.lower() in DOCS:
            s = self.section(path, a)
            return f'{"#" * s[2]} {s[3]}' if s else ''
        ids = list(dict.fromkeys(h['id'] for n in range(a, (b or a) + 1) if (h := self.holder(path, n))))
        return ', '.join(ids[:4]) + (f' (+{len(ids) - 4})' if len(ids) > 4 else '')


def relative(q):
    p = q[len(str(ROOT)) + 1:] if q.startswith(str(ROOT) + '/') else q
    p = p[2:] if p.startswith('./') else p
    p = p.rstrip('/') or '.'
    return p if (ROOT / p).exists() and not p.startswith('..') else None


def within(path, places):
    return not places or any(path == p or path.startswith(p.rstrip('/') + '/') or fnmatch.fnmatch(path, p) for p in places)


def short(text, most=110):
    return text if len(text) <= most else text[:text.rfind(' ', 0, most - 1)] + '…'


def put(lines, a, b):
    for i in range(a, b + 1):
        print(f'{i}\t{lines[i - 1]}')


VALUE_BEFORE = re.compile(r'(?:\b(?:const|let|var|val|final|static|export)\s+|^\s*)')


def declarations(repo, word):
    """[(path, first, last, what, line)] where word is declared, as the files' shapes show it."""
    out = list(repo.decls().get(word, []))
    if not out and re.fullmatch(r'[A-Za-z_$][\w$]*', word):
        rx = re.compile(r'(?:\b(?:const|let|var|val|final|static|export)\s+|^\s*)' + re.escape(word) + r'\s*[:=]')
        for p in files():
            if word in '\n'.join(repo.lines(p)):
                for i, line in enumerate(repo.lines(p), 1):
                    if len(out) >= 6 or line.lstrip().startswith(('#', '//', '*')):
                        continue
                    m = rx.search(line)
                    if m and not (m.end() < len(line) and line[m.end()] in '=>'):
                        out.append((p, i, i, f'value {word}', line.strip()[:120]))
    return out
# @end map.ask.repo


# @map map.ask.answer: each kind of question answered whole, and the command reading a call's questions
def search(repo, rx, places, skip=()):
    hits, whole = [], re.compile(rx.pattern, rx.flags | re.M)
    for p in repo.files:
        if not within(p, places) or (ROOT / p).stat().st_size > LARGE:
            continue
        lines = repo.lines(p)
        if not whole.search('\n'.join(lines)):
            continue
        for i, line in enumerate(lines, 1):
            if rx.search(line) and not any(sp == p and a <= i <= b for sp, a, b in skip):
                hits.append((p, i, line))
    return hits


def search_word(repo, word, places, skip=(), hyphen=False):
    """The lines naming word as an identifier: no letter, digit, _ or $ around it (nor a hyphen, when it has one)."""
    hits, edge = [], '-' if hyphen else ''
    for p in repo.files:
        if not within(p, places) or (ROOT / p).stat().st_size > LARGE:
            continue
        lines = repo.lines(p)
        if word not in '\n'.join(lines):
            continue
        for i, line in enumerate(lines, 1):
            if word in line and bounded(line, word, edge, edge) and not any(sp == p and a <= i <= b for sp, a, b in skip):
                hits.append((p, i, line))
    return hits


FLAGS = {'json': False, 'literal': False}      # --json: one JSON document instead of the text; --literal: ask searches its text as it is
REC = {}                                        # the structured facts of the answer being built (only with --json)


def rec(kind, value):
    if FLAGS['json']:
        REC.setdefault(kind, []).append(value)


BRIEF_JSON = []                                 # the brief's document, built beside its text


def block_json(b):
    return {'id': b['id'], 'file': b['path'], 'first': b['first'], 'last': b['last'], 'purpose': b['purpose']}


def print_json(doc):
    sys.stdout.write(json.dumps(doc, ensure_ascii=False, separators=(',', ':')) + '\n')


def show_hits(repo, hits, every, numbers=False):
    places = collections.OrderedDict()
    for p, i, line in hits:
        b = repo.holder(p, i)
        rec('hits', {'file': p, 'line': i, 'text': line, 'block': b['id'] if b else None})
        if b:
            key, label = (p, b['id'], b['first']), f'{b["id"]}  {p}:{b["first"]}-{b["last"]}  {short(b["purpose"])}'
        elif pathlib.PurePath(p).suffix.lower() in DOCS and (s := repo.section(p, i)):
            key, label = (p, s[0]), f'{p}:{s[0]}-{s[1]}  {"#" * s[2]} {s[3]}'
        else:
            key, label = (p,), p
        places.setdefault(key, [label, []])[1].append((i, line))
    if len(hits) > MANY and not every:
        print(f'  {len(hits)} lines in {len(places)} places; the places (their lines: --all, or --in <file, folder or glob>)')
        for label, found in list(places.values())[:60]:
            print(f'    {label}  ({len(found)} lines)')
        if len(places) > 60:
            print(f'    … {len(places) - 60} more places')
        return
    for label, found in places.values():
        if numbers:
            print(f'    {label}: {", ".join(str(i) for i, _ in found)}')
            continue
        print(f'  {label}')
        for i, line in found:
            print(f'{i}\t{line if len(line) <= CUT else line[:CUT] + f" …(+{len(line) - CUT})"}')


def answer_lines(repo, path, a, b):
    lines = repo.lines(path)
    a0, b_none = a, b is None
    if b is None:
        h = repo.holder(path, a)
        s = repo.section(path, a) if pathlib.PurePath(path).suffix.lower() in DOCS else None
        a, b, label = ((h['first'], h['last'], f'{h["id"]}: {h["purpose"]}') if h else
                       (s[0], s[1], f'{"#" * s[2]} {s[3]}') if s else (max(1, a - 15), a + 15, ''))
    else:
        label = repo.where(path, a, b)
    a, b = max(1, a), min(len(lines), b)
    if b_none and (held := repo.holder(path, a0)):
        rec('blocks', block_json(held))
    print(f'  {path}:{a}-{b}' + (f'  {label}' if label else ''))
    put(lines, a, b)


# @map map.ask.answer.file: a file answered whole, by its outline, its sections, its keys or its declarations
def answer_file(repo, path):
    lines = repo.lines(path)
    suffix = pathlib.PurePath(path).suffix.lower()
    if (ROOT / path).stat().st_size > LARGE:
        print(f'  {path}: {len(lines)} lines, {commas((ROOT / path).stat().st_size)} bytes: data, not printed (ask {path}:<first>-<last>)')
    elif len(lines) <= SMALL:
        print(f'  {path}: {len(lines)} lines, whole')
        put(lines, 1, len(lines))
    elif suffix in DOCS and repo.sections(path):
        print(f'  {path}: {len(lines)} lines; its sections (one: ask {path}#<words of its heading>)')
        for first, last, level, title in repo.sections(path):
            print(f'{first:>6}-{last:<6}{"  " * (level - 1)}{"#" * level} {title}')
    elif suffix == '.json':
        try:
            data = json.loads('\n'.join(lines))
        except ValueError:
            data = None
        if isinstance(data, (dict, list)):
            print(f'  {path}: {len(lines)} lines; its keys (one: ask {path}#<key>)')
            for k, v in (data.items() if isinstance(data, dict) else enumerate(data)):
                sub = f' {{{", ".join(list(v)[:8])}{", …" if len(v) > 8 else ""}}}' if isinstance(v, dict) else ''
                print(f'    {k}: {type(v).__name__}, {commas(len(jdump(v)))} characters{sub}')
        else:
            print(f'  {path}: {len(lines)} lines; the first {SMALL} (more: ask {path}:<first>-<last>)')
            put(lines, 1, SMALL)
    elif repo.by_file.get(path):
        named = collections.defaultdict(list)
        for d in facts(path)['decls'] if forms(path) else []:
            if d['kind'] in ('function', 'class', 'method') and (h := repo.holder(path, d['first'])):
                named[h['id']].append(d['name'])
        print(f'  {path}: {len(lines)} lines; its blocks (one: ask <id>, or {path}:<first>-<last>)')
        outer = []
        for b in sorted(repo.by_file[path], key=lambda b: (b['first'], -b['last'])):
            while outer and outer[-1] < b['first']:
                outer.pop()
            rec('blocks', block_json(b))
            print(f'{b["first"]:>6}-{b["last"]:<6}{"  " * len(outer)}{b["id"]}  {short(b["purpose"])}'
                  + (f'  [{", ".join(named[b["id"]][:8])}{" …" if len(named[b["id"]]) > 8 else ""}]' if named[b['id']] else ''))
            outer.append(b['last'])
    elif forms(path) and [d for d in facts(path)['decls'] if d['kind'] != 'heading']:
        decls = facts(path)['decls']
        print(f'  {path}: {len(lines)} lines, no tags yet; what it declares (one: ask <name>, or {path}:<first>-<last>)')
        for d in decls[:80]:
            print(f'{d["first"]:>6}-{d["last"]:<6}{d["kind"]} {d["name"]}  {short(d["what"], 90)}')
        if len(decls) > 80:
            print(f'    … {len(decls) - 80} more')
    else:
        print(f'  {path}: {len(lines)} lines; the first {SMALL} (more: ask {path}:<first>-<last>)')
        put(lines, 1, SMALL)

# @end map.ask.answer.file


def answer_files(repo, paths, about):
    print(f'  {about}: {len(paths)} files')
    for p in paths:
        first = min(repo.by_file.get(p, []), key=lambda b: b['first'], default=None)
        heads = repo.sections(p) if pathlib.PurePath(p).suffix.lower() in DOCS else []
        what = short(first['purpose'], 90) if first else (heads[0][3] if heads else '')
        rec('files', {'file': p, 'lines': len(repo.lines(p)), 'what': what})
        print(f'    {p}  ({len(repo.lines(p))} lines)  {what}')


def answer_folder(repo, path):
    base = '' if path == '.' else path.rstrip('/') + '/'
    under = [p for p in repo.files if p.startswith(base)]
    here = [p for p in under if '/' not in p[len(base):]]
    folders = collections.Counter(p[len(base):].split('/')[0] for p in under if '/' in p[len(base):])
    answer_files(repo, here, path)
    for f, n in sorted(folders.items()):
        print(f'    {base}{f}/  ({n} files)')


def answer_part(repo, path, words):
    ws = re.findall(r'[a-z0-9]+', words.lower())
    has = lambda text: all(any(t.startswith(w) for t in re.findall(r'[a-z0-9]+', text.lower())) for w in ws)  # noqa: E731
    if path.endswith('.json'):
        try:
            data, keys = json.loads('\n'.join(repo.lines(path))), words.split('.')
            for k in keys:
                data = data[int(k)] if isinstance(data, list) else data[k]
            print(f'  {path}#{words}')
            print(jdump(data, 1))
            return True
        except (KeyError, IndexError, ValueError, TypeError):
            return False
    if pathlib.PurePath(path).suffix.lower() in DOCS:
        found = [s for s in repo.sections(path) if has(s[3])]
        for first, last, level, title in found:
            print(f'  {path}:{first}-{last}  {"#" * level} {title}')
            put(repo.lines(path), first, last)
        return bool(found)
    found = [b for b in repo.by_file.get(path, []) if has(b['id'] + ' ' + b['purpose'])]
    for b in found:
        rec('blocks', block_json(b))
        print(f'  {path}:{b["first"]}-{b["last"]}  {b["id"]}: {b["purpose"]}')
        put(repo.lines(path), b['first'], b['last'])
    return bool(found)


def answer_block(repo, q):
    exact = [b for b in repo.blocks if b['id'] == q]
    inside = [b for b in repo.blocks if b['id'].startswith(q + '.')]
    if exact:
        for b in exact:
            rec('blocks', block_json(b))
            nested = [x for x in repo.by_file[b['path']] if x is not b and b['first'] <= x['first'] and x['last'] <= b['last']]
            print(f'  {b["path"]}:{b["first"]}-{b["last"]}  {b["id"]}: {b["purpose"]}')
            if b['last'] - b['first'] + 1 > SMALL and nested:
                print(f'  {b["last"] - b["first"] + 1} lines; the blocks inside it (one: ask <id>, or {b["path"]}:<first>-<last>)')
                for x in nested:
                    rec('blocks', block_json(x))
                    print(f'{x["first"]:>6}-{x["last"]:<6}{x["id"]}  {short(x["purpose"])}')
            else:
                put(repo.lines(b['path']), b['first'], b['last'])
    elif len(inside) <= 60:
        print(f'  {len(inside)} blocks under {q} (one: ask <id>)')
        for b in inside:
            rec('blocks', block_json(b))
            print(f'    {b["id"]:<44} {b["path"]}:{b["first"]}-{b["last"]}  {short(b["purpose"])}')
    else:
        parts = collections.OrderedDict()
        for b in inside:
            parts.setdefault('.'.join(b['id'].split('.')[:len(q.split('.')) + 1]), []).append(b)
        print(f'  {len(inside)} blocks under {q}, in {len(parts)} parts (one: ask <id>)')
        for part, bs in parts.items():
            print(f'    {part:<40} {len(bs):>3} blocks  {", ".join(sorted({b["path"] for b in bs}))[:80]}  {short(bs[0]["purpose"], 70)}')


def answer_name(repo, q, places, every):
    """What an identifier names: the code declaring it and the other lines naming it; False when nothing holds it."""
    word = q if q.startswith('--') else q.lstrip('#.')
    decls = declarations(repo, word) if re.fullmatch(r'[A-Za-z_$][\w$]*', word) else []
    if len(decls) > 3:
        print(f'  declared in {len(decls)} places (the code of one: ask <file>:<first>-<last>)')
    for path, first, last, what, _ in decls:
        rec('declarations', {'what': what, 'file': path, 'first': first, 'last': last})
        print(f'  {what}: {path}:{first}-{last}  in {repo.where(path, first) or path}')
        if len(decls) <= 3 and last - first < LONG:
            put(repo.lines(path), first, last)
        elif len(decls) <= 3:
            put(repo.lines(path), first, first + 11)
            print(f'  … {last - first - 11} more lines: ask {path}:{first + 12}-{last}')
    hyphen = '-' in word or q.startswith('--') or not word[:1].isalnum()
    hits = search_word(repo, word, places, skip=[(p, a, b) for p, a, b, _, _ in decls], hyphen=hyphen)
    if hits:
        print(f'  named on {len(hits)} other lines' if decls else f'  on {len(hits)} lines')
        show_hits(repo, hits, every, numbers=len(hits) > FEW and not every)
    return bool(decls or hits)


DECLARED = re.compile(r'^\^?\s*(?:(?:export|async|static|pub|public|private)\s+)*(?:function\*?|def|fn|func|class|const|let|var|val)\s+([A-Za-z_$][\w$]*)\b.*$'
                      r'|^(?:global\.|window\.|\.)?([A-Za-z_$][\w$]*)\s*(?:\\?\(|=)\s*$')


def names_in(q):
    """The names a question written as for grep asks for (function renderCart, renderCart(, const SIZE=, a\\|b)."""
    out = []
    for alt in re.split(r'\\\||\|', q):
        m = DECLARED.match(alt.strip())
        if not m:
            return []
        out.append(m.group(1) or m.group(2))
    return list(dict.fromkeys(out))


def unescaped_pipe(q):
    return any(c == '|' and (i == 0 or q[i - 1] != '\\') for i, c in enumerate(q))


def answer_text(repo, q, places, every):
    literal = FLAGS['literal']
    if not literal and '\\|' in q and not unescaped_pipe(q):
        q = q.replace('\\|', '|')
    try:
        rx = re.compile(re.escape(q) if literal else q)
    except re.error:
        rx = re.compile(re.escape(q))
    hits = search(repo, rx, places)
    if hits:
        show_hits(repo, hits, every)
        return True
    if not literal and ' ' in q.strip():
        print('  no line holds it; the blocks whose id, purpose or file have these words:')
        find(q.split())
        return True
    return False


# @map map.ask.answer.call: the command reading a call's questions, each answered into its own part of the output, then fitted to the budget
def ask(args):
    every = '--all' in args
    budget, questions, waiting, i = CFG['limits'].get('answer', 28000), [], [], 0
    while i < len(args):
        if args[i] == '--in' and i + 1 < len(args):
            places = [relative(x) or x.lstrip('./') for x in args[i + 1].split(',') if x]
            questions += [(q, places) for q in waiting]
            waiting, i = [], i + 2
            continue
        if args[i] == '--budget' and i + 1 < len(args) and args[i + 1].isdigit():
            budget, i = int(args[i + 1]), i + 2
            continue
        if args[i] == '--json':
            FLAGS['json'] = True
            i += 1
            continue
        if args[i] in ('--literal', '-F'):
            FLAGS['literal'] = True
            i += 1
            continue
        if args[i] != '--all':
            waiting.append(args[i])
        i += 1
    questions += [(q, []) for q in waiting]
    if not questions:
        sys.exit(__doc__)
    repo = Repo()
    ids = {b['id'] for b in repo.blocks}
    answers, docs = [], []
    for q, places in questions:
        REC.clear()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            answer(repo, ids, q, places, every)
        answers.append((q, out.getvalue()))
        if FLAGS['json']:
            doc = {'question': q, 'blocks': [], 'declarations': [], 'files': [], 'hits': [], **REC}
            doc['found'] = 'nothing in the code or the docs holds it' not in out.getvalue()
            doc['text'] = out.getvalue()
            docs.append(doc)
    if FLAGS['json']:
        print_json({'questions': docs})
        save_cache()
        return
    sys.stdout.write(''.join(fit(answers, budget)))
    save_cache()


def answer(repo, ids, q, places, every):
    """One question of a call, answered whole."""
    print(f'== {q}')
    if FLAGS['literal']:
        if not answer_text(repo, q, places, every):
            print('  nothing in the code or the docs holds it')
        return
    m = re.fullmatch(r'(.+?):(\d+)(?:-(\d+))?', q)
    path = relative(m.group(1)) if m else None
    if path and (ROOT / path).is_file():
        answer_lines(repo, path, int(m.group(2)), int(m.group(3)) if m.group(3) else None)
        return
    head, _, part = q.partition('#')
    path = relative(head) if part and head else None
    if path and (ROOT / path).is_file():
        if not answer_part(repo, path, part):
            print(f'  nothing in {path} is called "{part}"; its outline:')
            answer_file(repo, path)
        return
    path = relative(q)
    if path and (ROOT / path).is_file():
        answer_file(repo, path)
    elif path and (ROOT / path).is_dir():
        answer_folder(repo, path)
    elif re.search(r'[*?]', q) and '/' in q and not re.search(r'[\\|()+^$]', q):
        answer_files(repo, [p for p in repo.files if fnmatch.fnmatch(p, q.lstrip('./'))], q)
    elif names_in(q):
        for name in names_in(q):
            print(f'  {name}:' if len(names_in(q)) > 1 else f'  the name {name}')
            if not answer_name(repo, name, places, every):
                print('  nothing in the code or the docs holds it')
    elif q in ids or any(x.startswith(q + '.') for x in ids):
        answer_block(repo, q)
    elif (identifier(q) or re.fullmatch(r'[A-Za-z_$][\w$]*', q)) and answer_name(repo, q, places, every):
        pass
    elif not answer_text(repo, q, places, every):
        print('  nothing in the code or the docs holds it')

# @end map.ask.answer.call


# @map map.ask.answer.fit: a call's answers kept within its budget of characters: the longest leave their code out, and say so
CODE = re.compile(r'\d+\t')


def fit(answers, budget):
    """A call's answers within its budget of characters: while they run over it, the longest answer (the first of equals)
    keeps its places and leaves out its lines of code, and says so. One question is always answered whole."""
    texts = [t for _, t in answers]
    total = sum(len(t) for t in texts)
    if budget <= 0 or len(texts) < 2:
        return texts
    for k in sorted(range(len(texts)), key=lambda k: (-len(texts[k]), k)):
        if total <= budget:
            break
        lines = texts[k].rstrip('\n').split('\n')
        kept = [x for x in lines if not CODE.match(x)]
        if len(kept) == len(lines):
            continue
        short_ = '\n'.join(kept + [f'  … {len(lines) - len(kept)} lines of code left out to keep this call under '
                                   f'{commas(budget)} characters: ask {answers[k][0]} in a call of its own']) + '\n'
        total += len(short_) - len(texts[k])
        texts[k] = short_
    return texts
# @end map.ask.answer.fit
# @end map.ask.answer


# @map map.brief.print: where a task starts: the components its words name, ranked, each with its parts, declarations, relations, tests, docs and commits
STOP = set('a an and are as at be by can do does for from has have how i in into is it its me my new of on or our '
           'should so that the their them then there these this to us was we what when where which who why will '
           'with add change changes make fix use using want need needs'.split())


def words_in(args):
    return [w for w in re.findall(r'[a-z0-9]+', ' '.join(args).lower()) if w not in STOP and len(w) > 1]


def ranked(blocks, g, words):
    """[(score, block)] best first: a word in the id counts three, in the purpose two, in a file or a name one."""
    names = collections.defaultdict(set)
    for p in files():
        for d in facts(p)['decls']:
            if d['kind'] != 'heading' and (b := g.at(p, d['first'])):
                names[b] |= words_of(d['name'])
    seen = {}
    for b in blocks:
        seen[(b['id'], b['path'])] = (b, {'id': words_of(b['id']), 'purpose': set(re.findall(r'[a-z0-9]+', b['purpose'].lower())),
                                          'other': set(re.findall(r'[a-z0-9]+', b['path'].lower())) | names.get(b['id'], set())})
    has = lambda pool, w: any(h.startswith(w) or (len(w) > 3 and w[-1] == 's' and h.startswith(w[:-1])) for h in pool)  # noqa: E731
    df = {w: sum(1 for _, p in seen.values() if has(p['id'] | p['purpose'] | p['other'], w)) for w in words}
    out = []
    for b, p in seen.values():
        s = 0.0
        for w in words:
            weight = 3 if has(p['id'], w) else 2 if has(p['purpose'], w) else 1 if has(p['other'], w) else 0
            s += weight * math.log(1 + len(seen) / (1 + df[w]))
        if s:
            out.append((round(s - (0.5 if is_test(b['path']) else 0), 9), b))
    return sorted(out, key=lambda x: (-x[0], x[1]['path'], x[1]['first']))


def brief(args, strict=True):
    """Prints the brief and returns its first round of questions; without strict, words that match nothing say so and
    return none instead of ending the command."""
    words = words_in(args)
    if not words:
        if not strict:
            return []
        sys.exit('Say the task in a few words, as the code names things: brief cart totals discount')
    blocks, _, untagged = everything()
    g = Graph(blocks)
    comps = components(blocks, g)
    hits = ranked(blocks, g, words)
    per = collections.defaultdict(list)
    for s, b in hits:
        if not is_test(b['path']):
            per[component(b['id'])].append((s, b))
    score = {c: round(sum(s * (1, 0.5, 0.25)[i] for i, (s, _) in enumerate(sorted(xs, key=lambda x: -x[0])[:3])), 9) for c, xs in per.items()}
    order = sorted(score, key=lambda c: -score[c])
    if not order:
        if not strict:
            print(f'No block matches {" ".join(words)}.')
            return []
        sys.exit(f'No block matches those words. Try others, or {CMD} find <word>.')
    near = [c for c in order if score[c] >= 0.25 * score[order[0]]][:10]
    chosen, also = near[:3], near[3:]
    doc_components, doc_also, doc_recipes = [], [], []
    print(f'brief {" ".join(words)}: {len(near)} of {len(order)} components that match, best first. ask <id or name> reads a block.')
    for c in chosen:
        info = comps[c]
        fs = sorted(info['files'])
        print(f'\n{c}  {short(info["what"] or "", 100)}  [{", ".join(fs[:4])}{" …" if len(fs) > 4 else ""}]')
        best = {}
        for _, b in sorted(per[c], key=lambda x: -x[0]):
            best.setdefault(b['id'], [b, 0])[1] += 1
        shown_parts = list(best.values())[:5 if c in chosen[:2] else 3]
        parts_json = [{'id': b['id'], 'file': b['path'], 'first': b['first'], 'last': b['last'], 'purpose': b['purpose'], 'more_files': n - 1} for b, n in shown_parts]
        for i, (b, n) in enumerate(shown_parts):
            more = f' (+{n - 1} files)' if n > 1 else ''
            print(f'  {"parts:" if not i else "      "} {b["id"]} {b["path"]}:{b["first"]}-{b["last"]}{more} — {short(b["purpose"], 70)}')
        decl = list(dict.fromkeys(info['declares']))
        if decl:
            about = [d for d in decl if any(h.startswith(w) for h in words_of(d) for w in words)]
            shown = (about + [d for d in decl if d not in about])[:8]
            print(f'  declares ({len(decl)}): {", ".join(shown)}' + (' …' if len(decl) > 8 else ''))
        near_ = ', '.join(sorted(info['needs'])[:5]) + (' …' if len(info['needs']) > 5 else '')
        by = ', '.join(sorted(info['by'])[:5]) + (' …' if len(info['by']) > 5 else '')
        if near_ or by:
            print(f'  needs (imports): {near_ or "—"}; needed by: {by or "—"}')
        ts = sorted(info['tests'])
        print(f'  tests ({len(ts)}): ' + (' '.join(ts[:6]) + (' …' if len(ts) > 6 else '') if ts else 'none import or name it'))
        if info['docs']:
            print(f'  docs: {", ".join(sorted(info["docs"])[:5])}')
        log = git('log', '-n', '2', '--format=%ad %h %s', '--date=short', '--', *fs)
        changed = [x for x in log.split('\n') if x.strip()]
        for ln in changed:
            print(f'  changed {short(ln, 110)}')
        doc_components.append({'name': c, 'what': info['what'] or '', 'files': fs, 'parts': parts_json, 'declares': decl, 'needs': sorted(info['needs']),
                               'needed_by': sorted(info['by']), 'tests': ts, 'docs': sorted(info['docs']), 'changed': changed})
    if also:
        print('\nalso:')
    for c in also:
        b = sorted(per[c], key=lambda x: -x[0])[0][1]
        doc_also.append({'component': c, 'id': b['id'], 'file': b['path'], 'first': b['first'], 'last': b['last'], 'purpose': b['purpose'], 'tests': len(comps[c]['tests'])})
        print(f'{c}  {b["id"]} {b["path"]}:{b["first"]}-{b["last"]} — {short(b["purpose"], 70)}; {len(comps[c]["tests"])} tests')
    checks = [b for _, b in hits if is_test(b['path'])][:3]
    if checks:
        print('tests that say it: ' + '; '.join(f'{b["id"]} {b["path"]}:{b["first"]}-{b["last"]}' for b in checks))
    for name, about in recipes_matching(words):
        doc_recipes.append({'name': name, 'about': about})
        print(f'recipe {name}: {about} ({CMD} recipe {name})')
    if untagged:
        print(f'{len(untagged)} files carry no tag yet ({CMD} gaps): ask <file> gives their declarations')
    first = list(dict.fromkeys(b['id'] for _, b in hits if not is_test(b['path'])))[:4]
    if first:
        print(f'Next, one call for the whole first round (add every other question to it): {CMD} ask ' + ' '.join(first))
    print(f'End each change with: {CMD} check')
    if FLAGS['json']:
        BRIEF_JSON.append({'words': words, 'matching': len(near), 'total': len(order), 'components': doc_components, 'also': doc_also,
                           'tests_that_say_it': [{'id': b['id'], 'file': b['path'], 'first': b['first'], 'last': b['last']} for b in checks],
                           'recipes': doc_recipes, 'untagged_files': len(untagged), 'first_round': first, 'check': f'{CMD} check'})
    save_cache()
    return first
# @end map.brief.print


# @map map.brief.pack: where a task starts, in one call: a recipe's steps and the brief of the task's words, then that first round answered within the budget
def pack(args):
    """pack <recipe> [words…] | pack <words…> [--budget N]: the recipe's steps (when the first word names one) and the
    brief of the other words, then their blocks and files asked in one round, as ask answers it."""
    words, budget, i = [], [], 0
    while i < len(args):
        if args[i] == '--budget' and i + 1 < len(args):
            budget, i = args[i:i + 2], i + 2
            continue
        words.append(args[i])
        i += 1
    first = []
    with contextlib.redirect_stdout(io.StringIO()) as out:
        if words and words[0] in CFG['recipes']:
            recipe(words[0])
            first = [target for target, _ in CFG['recipes'][words[0]].get('steps', [])]
            words = words[1:]
            if words:
                print()
        if words or not first:
            first += brief(words, strict=not first)
        first = list(dict.fromkeys(first))
        if first:
            print(f'\nThe first round, answered ({CMD} ask {" ".join(first)}):')
    sys.stdout.write(out.getvalue())
    sys.stdout.flush()
    if first:
        limit = int(budget[1]) if budget and budget[1].isdigit() else CFG['limits'].get('answer', 28000)
        ask(first + ['--budget', str(max(limit - len(out.getvalue()), 1) if limit > 0 else 0)])   # the whole call within it
# @end map.brief.pack


# @map map.recipes.steps: recipes from map.json, the steps of a change across layers, each checked against a block that still exists; plans whose parts can run at once
def recipe(name=None):
    rs = CFG['recipes']
    if not name or name not in rs:
        if name:
            print(f'No recipe {name}.')
        for key, r in rs.items():
            print(f'{key:<15} {r.get("about", "")}')
        if not rs:
            print('No recipes in map.json yet (docs/CONFIG.md says how to write one).')
        return
    r = rs[name]
    at = {}
    for b in sorted(everything()[0], key=lambda b: b['path']):
        at.setdefault(b['id'], f'{b["path"]}:{b["first"]}-{b["last"]}')
    print(f'{name}: {r.get("about", "")}.' + (f' Checked against {r["checked"]}.' if r.get('checked') else ''))
    for i, (target, what) in enumerate(r.get('steps', []), 1):
        print(f'{i}. {target}  {at.get(target, "")}'.rstrip() + f'\n   {what}')
    if r.get('note'):
        print(f'Note: {r["note"]}')


def recipes_matching(words):
    out = []
    for key, r in CFG['recipes'].items():
        mine = set(str(r.get('words', '')).split()) | set(key.split('-'))
        if len(mine & set(words)) >= 2:
            out.append((key, r.get('about', '')))
    return out


def recipe_problems(blocks):
    ids = {b['id'] for b in blocks}
    out = []
    for key, r in CFG['recipes'].items():
        for target, _ in r.get('steps', []):
            if '/' in target or target.endswith(('.md', '.txt')):
                if not (ROOT / target).exists():
                    out.append(('map.json', 0, f'recipe {key} names {target}, which is not in the repository'))
            elif target not in ids:
                out.append(('map.json', 0, f'recipe {key} names the block {target}, which no file tags: find where it went ({CMD} find …)'))
    return out


SHARED = ('map/', 'map.yaml', 'CHANGELOG', 'changes/', 'docs/plans/')


def plan(path):
    """Which parts of a plan ('## Part <n>: …' sections with a '- Files:' line) can go to two agents at once."""
    text = pathlib.Path(path).read_text(encoding='utf-8')
    parts, current = [], None
    for line in text.split('\n'):
        m = re.match(r'## Part (\d+)\b[:.\s-]*(.*)', line)
        if m:
            current = [int(m.group(1)), m.group(2).strip(), set()]
            parts.append(current)
        elif line.startswith('## '):
            current = None
        elif current and (m := re.match(r'\s*-\s*Files:(.*)', line)):
            current[2] |= {w.strip('`*,;:()[]').rstrip('.') for w in re.split(r'[\s,]+', m.group(1)) if '/' in w or (ROOT / w.strip('`*,;:()[]')).is_file()}
    if not parts:
        sys.exit(f'{path}: no "## Part <n>: …" sections with a "- Files:" line each')
    g = Graph(everything()[0])
    print(f'{path}: {len(parts)} parts')
    apart = []
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            common = sorted(f for f in a[2] & b[2] if not f.startswith(SHARED))
            why = ('both change ' + ', '.join(common)) if common else None
            if not why:
                for x, y in ((a, b), (b, a)):
                    for f in sorted(x[2]):
                        if g.file_edges.get(f, set()) & y[2]:
                            why = f'part {x[0]} imports what part {y[0]} changes ({f})'
                            break
                    if why:
                        break
            print(f'  {a[0]} and {b[0]}: ' + (f'one after the other: {why}' if why else 'at once'))
            if not why:
                apart.append((a[0], b[0]))
    if apart:
        print('At once: ' + ', '.join(f'{a} with {b}' for a, b in apart) + ' (each agent in a worktree of its own: git worktree add ../<name>-<part> -b <branch>)')
    else:
        print('No two parts can run at once: one agent after another, in order.')
# @end map.recipes.steps


# @map map.cli.init: init: the areas detected, map.json written, the section for AGENTS.md printed; and the command line
AGENTS_SECTION = """## Finding code

Every block of code carries a tag naming it (`@map <area>.<topic>.<part>: what it does`), and the map is read
from the tags and the code: `map.yaml` (the areas and what each needs from the others) and `map/<area>.yaml`
(each area's components). The map, not grep, is how this repository is read. Every call of an agent re-reads the
whole conversation, so questions go in rounds: every question of a round in one call, each answered whole.

1. **Start with `{cmd} brief <the task's words>`**, as the code names things: the components
   the words name, their blocks and lines, what they declare, need and are needed by, their tests, docs and
   latest commits; then the first round of questions, as one call.
2. **Then one `ask` for each round of questions.** Write down every question the brief leaves open and ask them
   together; a later round asks only what the answers opened:
   `{cmd} ask <question> [<question> …] [--in <paths>] [--all]` reads and locates everything:
   a block id (its code), an identifier (what it is, the code declaring it, every line naming it), a file (whole,
   or its outline), a folder, `src/x.js:120-180`, `docs/X.md#heading`, `data.json#key`, `'src/**/*.css'`, or any
   text (every line holding it, by block or section). `--in` narrows the questions before it.
   Beside `ask`: `find <words>`, `history <id>` (its commits), `deps` and `impact <id or file>` (imports, and
   the tests to run), `recipe [name]` (the steps of a change across layers).
3. **Do not read or search the code and the docs with `grep`, `rg`, `sed`, `cat`, `head`, `tail`, `ls`, `find`,
   with a script that only prints them, or with a file-reading tool on whole files**: `ask` answers the same
   question, by block, with the code. Counting, computing over data, editing and other files go ahead; so does a
   range of lines before an edit.
4. **Tag what you add or move** (`https://github.com/mars1571/grepless/blob/main/docs/TAGGING.md`): a tag on the line above each block, in the file's comment form,
   `@end <id>` when other code follows it; keep purposes true. **End each change with `{cmd} check`**, which also
   checks that the map is current (`{cmd} build` writes it again).
"""


def guard_command():
    """The guard's command beside the map's: python3 tools/map.py → python3 tools/map-guard.py, tools/map → tools/map-guard."""
    words = CMD.split()
    for k, w in enumerate(words):
        folder, slash, name = w.rpartition('/')
        if name in ('map', 'map.py', 'map.mjs'):
            words[k] = folder + slash + 'map-guard' + name[3:]
            return ' '.join(words)
    return 'python3 tools/map-guard.py'


def init(args):
    counts = collections.Counter(area_of(p) for p in files())
    untagged = [p for p in files() if not facts(p)['blocks']]
    print(f'Root: {ROOT} (--root <path> or MAP_ROOT names another)')
    if not (ROOT / 'map.json').is_file() or '--force' in args:
        cfg = {'command': CMD, 'holds': {a: '' for a, _ in counts.most_common()}}
        if any(area_of(p) == 'root' for p in files()):
            cfg['areas'] = {'.': 'root'}
        (ROOT / 'map.json').write_text(jdump(cfg, 2) + '\n', encoding='utf-8')
        print(f'map.json written: {len(counts)} areas detected, each with an empty "holds" to fill in (one line: what the area holds).')
    else:
        print('map.json is there already (--force writes it again).')
    print('Areas (code files each): ' + ', '.join(f'{a} {n}' for a, n in counts.most_common()))
    print(f'{len(files())} code files, {len(files()) - len(untagged)} tagged, {len(untagged)} without tags yet.')
    print()
    print(f'Next: 1. tag the code (https://github.com/mars1571/grepless/blob/main/docs/TAGGING.md; {CMD} gaps lists what is left), 2. {CMD} build, 3. paste this in AGENTS.md')
    print(f'(CLAUDE.md imports it with a line "@AGENTS.md"), 4. install the guard: {guard_command()} install <agent>.')
    print()
    print(AGENTS_SECTION.format(cmd=CMD))
    save_cache()


USAGE = """The code map: a map of the areas (map.yaml) and of each area's components (map/<area>.yaml), read from the tags
in the code; what agents ask it instead of grepping. Start a task with brief, read with ask, end each change with check.

    {cmd} build            write map.yaml (the areas) and map/<area>.yaml (each area's components)
    {cmd} check            the rules, and that the map matches the code (for CI); exit 1 when not
    {cmd} brief <words>    where a task starts: the components the words name, their blocks and lines, what
                                they declare, need and are needed by, their tests, docs and latest commits, then
                                the first round of questions to ask, in one call
    {cmd} pack [recipe] <words>   brief (and the recipe's steps) with that first round already answered, in one call
    {cmd} ask <question> [<question> …] [--in <paths>] [--all] [--budget N]
                                the one way to read and locate: every question of a round in one call, each
                                answered whole: a block id (its code), an identifier (what it is, the code declaring
                                it, every line naming it), a file (whole, or its outline), a folder, src/x.js:120-180,
                                docs/X.md#heading, data.json#key, 'src/**/*.css', or any text (every line holding it)
    {cmd} find <words>     blocks whose id, purpose or file has every word; an identifier first
    {cmd} history <id|file>      the commits that touched a block's lines (git log -L)
    {cmd} deps|impact <id|file>  what it imports; what imports it, and the tests to run
    {cmd} tests [paths | --changed]   the test files that reach these files, or the changed ones
    {cmd} recipe [name]    the steps of a change across layers (map.json, recipes), each at a block
    {cmd} plan <plan.md>   which parts of a plan can go to two agents at once
    {cmd} gaps [paths]     the files without tags, the lines outside blocks, the blocks to split
    {cmd} init             detect the areas, write map.json, print the section for AGENTS.md

Configuration, all of it optional, in map.json at the root ({cmd} init writes one): docs/CONFIG.md. The same
tool exists in Python, Node, Go and Rust, with the same answers (tests/conformance.py).""".replace('{cmd}', CMD)
QUERIES = {'deps': deps, 'impact': impact, 'history': history, 'where': where}
if __name__ == '__main__':
    command, rest = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ('check', [])
    if command in ('find', 'brief') and '--json' in rest:
        FLAGS['json'] = True
        rest = [w for w in rest if w != '--json']
        if not rest:
            sys.exit(__doc__)
        with contextlib.redirect_stdout(io.StringIO()):
            more = find(rest) if command == 'find' else brief(rest)
        print_json({'declarations': [], 'blocks': [], **REC, 'more': more} if command == 'find' else BRIEF_JSON[0])
    elif command == 'find' and rest:
        find(rest)
    elif command in QUERIES and len(rest) == 1:
        QUERIES[command](rest[0])
    elif command == 'ask' and rest:
        ask(rest)
    elif command == 'brief' and rest:
        brief(rest)
    elif command == 'pack' and rest:
        pack(rest)
    elif command == 'tests':
        tests(rest)
    elif command == 'recipe' and len(rest) <= 1:
        recipe(*rest)
    elif command == 'plan' and len(rest) == 1:
        plan(rest[0])
    elif command == 'gaps':
        gaps(rest)
    elif command == 'init':
        init(rest)
    elif command == 'build':
        found = build()
        for path, n, p in found:
            print(f'{path}:{n}: {p}' if n else f'{path}: {p}')
        sys.exit(1 if found else 0)
    elif command == 'check':
        found, n_blocks, n_untagged = problems()
        for path, n, p in found:
            print(f'{path}:{n}: {p}' if n else f'{path}: {p}')
        print(f'{n_blocks} blocks, {len(found)} problems' + (f', {n_untagged} files without tags ({CMD} gaps)' if n_untagged else ''))
        sys.exit(1 if found else 0)
    elif command in ('help', '-h', '--help'):
        print(USAGE)
    elif command in ('version', '--version'):
        print(VERSION)
    else:
        sys.exit(USAGE)
# @end map.cli.init
