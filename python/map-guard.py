#!/usr/bin/env python3
# @map map.guard.scope: what the map reads (the code and the docs of the repository), how a command's paths resolve, and the agents' hook formats
"""map-guard: a pre-tool hook that keeps agents reading the code and the docs through the map.

A call that would search or read the repository's code or docs with grep, rg, sed, cat, head, tail, awk, ls,
find, with a script that only prints them, or with the agent's own file-reading tool on a whole file, is
refused, and the refusal names the `ask` that answers the same question (the agent's own filters kept:
| head, | cut). Everything else goes ahead: counting (grep -c, wc), editing (sed -i), writing, pipes, tests,
builds, the map itself, files git ignores, files outside the repository, a range of lines before an edit.

    python3 tools/map-guard.py [--agent claude|codex|cursor|copilot|gemini]   the hook: stdin in, the decision out
    python3 tools/map-guard.py install <agent>      write the agent's hook settings for this repository
    python3 tools/map-guard.py try '<shell line>'   what the guard would answer for that line (nothing: it goes ahead)

Agents and their formats, as their docs give them (agents/README.md has the sources):
  claude   Claude Code: PreToolUse, stdin {tool_name, tool_input, cwd}; {"hookSpecificOutput": {"permissionDecision": "deny"}}
  codex    Codex: PreToolUse with the same fields and answer (.codex/hooks.json)
  cursor   Cursor: beforeShellExecution {command, cwd} and beforeReadFile {file_path}; {"permission": "deny", "agent_message"}
  copilot  GitHub Copilot: preToolUse {toolName, toolArgs} or {tool_name, tool_input}; {"permissionDecision": "deny"}
  gemini   Gemini CLI: BeforeTool {tool_name, tool_input}; {"decision": "deny", "reason"}
Without --agent, the format is told from the fields. A guard that fails, or that cannot read its input, lets the
call go ahead. Python 3.9 or later, the standard library only; map.json (at the root) gives the command agents
run (`command`) and the paths the guard leaves alone (`guard.skip`, `ignore`).
"""
import fnmatch
import json
import os
import re
import sys


def find_root():
    if os.environ.get('MAP_ROOT'):
        return os.path.realpath(os.environ['MAP_ROOT'])
    here = os.path.dirname(os.path.abspath(__file__))
    for start in (os.getcwd(), here):
        for mark in ('map.json', '.git'):
            base = start
            while True:
                if os.path.exists(os.path.join(base, mark)):
                    return base
                up = os.path.dirname(base)
                if up == base:
                    break
                base = up
    return os.getcwd()


ROOT = find_root()
CFG = {}
try:
    with open(os.path.join(ROOT, 'map.json'), encoding='utf-8') as _f:
        CFG = json.load(_f)
except (OSError, ValueError):
    CFG = {}
ASK = (CFG.get('command') or 'python3 tools/map.py') + ' ask '
SKIPPED = list((CFG.get('guard') or {}).get('skip', [])) + list(CFG.get('ignore', []))
TEXT = set(('.js .mjs .cjs .jsx .ts .tsx .mts .cts .java .kt .kts .scala .groovy .go .rs .swift .c .h .cc .cpp .cxx .hpp .hh .cs '
            '.m .mm .php .dart .css .scss .less .proto .zig .d .v .py .pyi .rb .rake .sh .bash .zsh .fish .pl .pm .r .R .yml '
            '.yaml .toml .ps1 .ex .exs .nim .jl .cmake .tf .nix .cr .coffee .mk .html .htm .xml .vue .svelte .astro .xhtml '
            '.sql .lua .hs .elm .ada .vhd .clj .cljs .cljc .edn .el .lisp .scm .rkt .erl .hrl .tex .md .markdown .rst .txt '
            '.adoc .json .ini .cfg .csv .editorconfig').split()) | set(CFG.get('forms', {}))
NAMED = {'Makefile', 'GNUmakefile', 'Dockerfile', 'Containerfile', 'Rakefile', 'Gemfile', 'Justfile', 'Vagrantfile',
         'CMakeLists.txt', 'Jenkinsfile'}
SKIP = {'node_modules', 'dist', 'build', 'out', 'target', 'vendor', 'venv', '.venv', '__pycache__', '.git', '.hg', '.svn',
        '.tox', '.mypy_cache', '.pytest_cache', '.cache', 'coverage', '.idea', '.vscode', 'bower_components', '.next',
        '.nuxt', '.terraform', 'Pods', 'DerivedData', 'map'}
SEARCH = {'grep', 'egrep', 'fgrep', 'rg', 'ag', 'ack'}
READ = {'cat', 'sed', 'head', 'tail', 'awk', 'nl', 'less', 'more', 'bat', 'cut', 'strings', 'xxd', 'od', 'perl', 'ruby'}
LIST = {'ls', 'find', 'tree', 'fd'}
FILTERS = {'head', 'tail', 'cut', 'grep', 'egrep', 'sort', 'uniq', 'wc', 'sed', 'awk', 'tr', 'column'}
REASON = ("This repository's code and docs are read and located through its map, every question of a round in one call "
          '(AGENTS.md, "Finding code"); it answers what this would, by block, with the code. None of this command ran: '
          'send its other steps again. Run instead:\n  ')


def inside(path, base):
    """The path relative to the repository, or None when it is outside it."""
    full = os.path.realpath(os.path.join(base, os.path.expanduser(path)))
    rel = os.path.relpath(full, ROOT)
    return None if rel.startswith('..') else rel


IGNORED = []


def ignored(rel):
    """Whether .gitignore, map.json (ignore, guard.skip) or the usual folders leave the path out."""
    if not IGNORED:
        try:
            with open(os.path.join(ROOT, '.gitignore'), encoding='utf-8') as f:
                lines = f.read().split('\n')
        except OSError:
            lines = []
        IGNORED.extend(p.strip() for p in lines if p.strip() and not p.startswith('#'))
        IGNORED.extend(SKIPPED)
        IGNORED.append('')                                    # read once, even when empty
    parts = rel.split(os.sep)
    if any(p in SKIP for p in parts[:-1]) or parts[0] in SKIP:
        return True
    for p in IGNORED:
        if not p:
            continue
        folder, q = p.endswith('/'), p.strip('/')
        if '/' in q:
            if rel == q or rel.startswith(q + os.sep) or fnmatch.fnmatch(rel, q):
                return True
        elif any(fnmatch.fnmatch(n, q) for n in (parts[:-1] if folder and not os.path.isdir(os.path.join(ROOT, rel)) else parts)):
            return True
    return False


def is_text(rel):
    name = os.path.basename(rel)
    if name in NAMED or os.path.splitext(name)[1].lower() in TEXT:
        return True
    if '.' not in name:
        try:
            with open(os.path.join(ROOT, rel), 'rb') as f:
                return f.read(2) == b'#!'
        except OSError:
            return False
    return False


def expand(rel):
    """The files a pattern with wildcards in its last segment names (a/b/*.py), relative to the root; [] otherwise."""
    folder, _, name = rel.rpartition('/')
    if re.search(r'[*?[]', folder):
        return []
    try:
        names = sorted(os.listdir(os.path.join(ROOT, folder) if folder else ROOT))
    except OSError:
        return []
    return [(folder + '/' + n) if folder else n for n in names if fnmatch.fnmatch(n, name)]


def mapped(rel, folder_ok=True):
    """Whether the map answers for this path: a text file of the repository, or a folder holding them."""
    if rel is None:
        return False
    if re.search(r'[*?[]', rel):
        return any(mapped(x, folder_ok) for x in expand(rel)[:50])
    if rel == '.':
        return folder_ok
    if rel in ('map.yaml',) or rel.split(os.sep)[0] == 'map':
        return False
    full = os.path.join(ROOT, rel)
    if os.path.isdir(full):
        return folder_ok and not ignored(rel)
    if not os.path.exists(full):
        return False
    return is_text(rel) and not ignored(rel)


SAFE = re.compile(r'^[A-Za-z0-9@%+=:,./_-]+$')


def quote_word(w):
    """A word quoted for the shell: as it is when it is safe, else in single quotes."""
    if not w:
        return "''"
    if SAFE.match(w):
        return w
    return "'" + w.replace("'", "'\"'\"'") + "'"


def quote(words):
    return ' '.join(quote_word(w) for w in words)
# @end map.guard.scope


# @map map.guard.commands: a shell line into its commands (heredocs left out, cd followed), and each command's map question
PUNCT = '();<>|&'


def shell_words(line):
    """The words of a shell line: quotes and backslashes resolved, a run of ();<>|& a word of its own, a word starting
    with # a comment to the end of the line."""
    out, word, i, n, quote_, had = [], [], 0, len(line), None, False
    while i < n:
        c = line[i]
        if quote_:
            if c == quote_:
                quote_ = None
            elif quote_ == '"' and c == '\\' and i + 1 < n and line[i + 1] in '"\\$`\n':
                word.append(line[i + 1])
                i += 1
            else:
                word.append(c)
        elif c in '\'"':
            quote_, had = c, True
        elif c == '\\' and i + 1 < n:
            word.append(line[i + 1])
            had = True
            i += 1
        elif c.isspace():
            if had:
                out.append(''.join(word))
                word, had = [], False
        elif c in PUNCT:
            if had:
                out.append(''.join(word))
                word, had = [], False
            j = i
            while j < n and line[j] in PUNCT:
                j += 1
            out.append(line[i:j])
            i = j
            continue
        elif c == '#' and not had:
            break
        else:
            word.append(c)
            had = True
        i += 1
    if had:
        out.append(''.join(word))
    return out


def heredocs(line):
    """[(start, end, head, tag, body)] for each heredoc in the line: the text from '<<' to the end of the closing tag line."""
    out, pos = [], 0
    while (i := line.find('<<', pos)) >= 0:
        m = re.match(r"<<-?\s*(['\"]?)(\w+)\1", line[i:])
        if not m:
            pos = i + 2
            continue
        head_end = line.find('\n', i)
        if head_end < 0:
            pos = i + 2
            continue
        tag, k = m.group(2), head_end + 1
        body_start, end = k, None
        while k <= len(line):
            nl = line.find('\n', k)
            seg = line[k:] if nl < 0 else line[k:nl]
            if seg.strip() == tag:
                end = len(line) if nl < 0 else nl
                body = line[body_start:k - 1] if k > body_start else ''
                out.append((i, end, line[line.rfind('\n', 0, i) + 1:i], tag, body))
                break
            if nl < 0:
                break
            k = nl + 1
        pos = end if end is not None else i + 2
    return out


def without_heredocs(line):
    """The line with each heredoc replaced by the rest of its head line (what follows the <<TAG marker)."""
    for start, end, _, _, _ in reversed(heredocs(line)):
        head_end = line.find('\n', start)
        marker = re.match(r"<<-?\s*(['\"]?)(\w+)\1", line[start:]).group(0)
        line = line[:start] + line[start + len(marker):head_end] + line[end:]
    return line


def commands(line, cwd):
    """[(words, piped, base)]: each simple command, whether a pipe feeds it, and the folder it runs in."""
    line = without_heredocs(line)
    line = line.replace('\\\n', ' ').replace('\n', ' ; ')
    line = re.sub(r'\d?>&\d|\d?>\s*/dev/null', ' ', line)
    tokens = shell_words(line)
    split = []
    for t in tokens:
        split += re.findall(r'\|\||&&|\|&|;;|>>|&>|[|&;()<>]', t) if re.fullmatch(r'[|&;()<>]+', t) else [t]
    out, words, piped, base = [], [], False, cwd
    for t in split + [';']:
        if t in ('|', '||', '&&', ';', '&', '(', ')', '|&', ';;', '\n'):
            if words:
                if words[0] == 'cd' and len(words) > 1:
                    base = os.path.join(base, os.path.expanduser(words[1]))
                else:
                    out.append((words, piped, base))
            piped, words = t in ('|', '|&'), []
        else:
            words.append(t)
    return out


def grep_question(words, base):
    """The ask for a grep-like search over the code or the docs, or None when it searches elsewhere."""
    pats, paths, includes, flags, i = [], [], [], set(), 1
    while i < len(words):
        a = words[i]
        if a in ('-e', '--regexp'):
            pats.append(words[i + 1] if i + 1 < len(words) else '')
            i += 2
            continue
        if a.startswith('--include='):
            includes.append(a.split('=', 1)[1])
        elif a in ('-A', '-B', '-C', '-m', '--max-count', '-g', '--glob', '-t', '--type', '--include', '--exclude'):
            if a in ('-g', '--glob', '--include'):
                includes.append(words[i + 1] if i + 1 < len(words) else '')
            i += 2
            continue
        elif a.startswith('--'):
            flags.add(a)
        elif a.startswith('-') and len(a) > 1:
            flags.update(a[1:])
        else:
            paths.append(a)
        i += 1
    if not pats and paths:
        pats, paths = [paths[0]], paths[1:]
    if flags & {'c', 'q', 'l', 'L', '--count', '--quiet', '--silent', '--files-with-matches', '--files-without-match'}:
        return None                                              # a count, a yes or file names: nothing of the files is read
    recursive = words[0] in ('rg', 'ag', 'ack') or flags & {'r', 'R', '--recursive'}
    if not paths and not recursive:
        return None
    rels = [inside(p, base) for p in paths] if paths else [inside('.', base)]
    if not any(mapped(r) for r in rels):
        return None
    places = [r for r in rels if r and r != '.']
    if includes:
        places = [os.path.join(p, '*' + g.lstrip('*')) for p in (places or ['']) for g in includes]
        places = [p.lstrip('/') for p in places]
    pattern = '|'.join(pats)
    if '@map' in pattern:
        tag = re.search(r'@map\s+([\w.-]+)', pattern)
        return [tag.group(1)] if tag else places or ['.']
    if re.fullmatch(r'\^#+.*', pattern) and all(p.endswith('.md') for p in places):
        return places
    alternatives = [a for p in pats for a in re.split(r'\\\||\|' if words[0] == 'grep' and not flags & {'E', 'P'} else r'\|', p)]
    names = [re.sub(r'^\^?\s*(?:(?:export|async|pub|public|private|static)\s+)*(?:function\*?|def|fn|func|class|const|let|var|val)\s+|(?:\\?\(|\\s\*=|\s*=|\\b)$', '', a)
             for a in alternatives]
    if names and all(re.fullmatch(r'[#.]?[A-Za-z_$][\w$-]*', n) for n in names) and not flags & {'v', 'F'}:
        return list(dict.fromkeys(names)) + (['--in', ','.join(places)] if places else [])
    if 'F' in flags:
        rx = re.escape(pattern)
    elif flags & {'E', 'P'} or words[0] in ('egrep', 'rg', 'ag', 'ack'):
        rx = pattern
    else:
        rx = re.sub(r'\\([|(){}+?])|([|(){}+?])', lambda m: m.group(1) or '\\' + m.group(2), pattern)
    if 'w' in flags:
        rx = rf'\b(?:{rx})\b'
    if 'i' in flags:
        rx = '(?i)' + rx
    return [rx] + (['--in', ','.join(places)] if places else [])


def read_question(words, base):
    """The ask for reading a file of the code or the docs, or None when it reads elsewhere or writes."""
    tool, args = words[0], words[1:]
    if tool == 'sed' and any(a.startswith('-i') or a == '--in-place' for a in args):
        return None
    if tool in ('perl', 'ruby') and any(re.fullmatch(r'-\w*i\S*', a) for a in args):
        return None
    script = None
    if tool == 'sed':
        rest = [a for a in args if not a.startswith('-')]
        script, files = (rest[0], rest[1:]) if rest else (None, [])
    elif tool == 'awk':
        rest = [a for a in args if not a.startswith('-')]
        files = rest[1:]
    else:
        files = [a for k, a in enumerate(args) if not a.startswith('-') and not (k and args[k - 1] in ('-n', '-c', '-f', '-d'))]
    n, from_start = 10, False
    for k, a in enumerate(args):
        m = re.fullmatch(r'-n(\+?\d+)?|-(\d+)', a)
        if a.startswith('-c'):
            n = None
        elif m:
            v = m.group(1) or m.group(2) or (args[k + 1] if k + 1 < len(args) else '10')
            n, from_start = (int(v.lstrip('+')) if v.lstrip('+').isdigit() else 10), v.startswith('+')
    rels = []
    for f in files:
        r = inside(f, base)
        rels += expand(r) if r and re.search(r'[*?[]', f) else [r]
    if not files or not any(mapped(r, folder_ok=False) for r in rels):
        return None
    out = []
    for rel in rels:
        if not mapped(rel, folder_ok=False):
            continue
        with open(os.path.join(ROOT, rel), encoding='utf-8', errors='replace') as f:
            count = sum(1 for _ in f)
        m = re.fullmatch(r"(\d+)(?:,(\d+|\$))?p", script or '')
        named = re.search(r'/\^?\s*(?:(?:export|async|pub)\s+)*(?:function|def|fn|func|class|const)\s+([A-Za-z_$][\w$]*)', script or '')
        if m:
            out.append(f'{rel}:{m.group(1)}-{m.group(2) if m.group(2) and m.group(2) != "$" else (count if m.group(2) else m.group(1))}')
        elif named:
            out += [named.group(1), '--in', rel]
        elif tool == 'head' and n:
            out.append(f'{rel}:1-{min(count, n)}')
        elif tool == 'tail' and n:
            out.append(f'{rel}:{n if from_start else max(1, count - n + 1)}-{count}')
        else:
            out.append(rel)
    return out


def list_question(words, base):
    """The ask for listing a folder of the code or the docs, or None."""
    args = [a for a in words[1:] if not a.startswith('-')]
    if words[0] == 'find':
        if any(a in ('-newer', '-mtime', '-mmin', '-size', '-exec', '-delete', '-empty', '-perm') for a in words):
            return None
        pattern = next((words[k + 1] for k, a in enumerate(words) if a in ('-name', '-iname') and k + 1 < len(words)), None)
        roots = [a for a in words[1:] if not a.startswith('-') and a != pattern][:1] or ['.']
        rel = inside(roots[0], base)
        if not mapped(rel) or rel == '.' and not pattern:
            return None
        return [os.path.join('' if rel == '.' else rel, '*' + pattern.lstrip('*')) if pattern else rel]
    rels = [inside(a, base) for a in args]
    return [r for r in rels if mapped(r) and r != '.'] or None


# @map map.guard.commands.scripts: a script that opens a file of the code only to print it: python -c, node -e, a heredoc fed to them, a scratch script run by name
READ_ARG = re.compile(r"""\b(?:open|readFileSync|readFile|read_text|read_bytes|Path)\s*\(\s*(?:['"`]([^'"`\n]+)['"`]|([A-Za-z_$][\w$]*)\s*[,)])""")
NAMED_VAR = re.compile(r"""\b([A-Za-z_$][\w$]*)\s*=\s*['"`]([^'"`\n]+)['"`]""")
WRITES_OTHER = re.compile(r"""write_text\(|write_bytes\(|writeFileSync\(|writeFile\(|appendFileSync\(|open\([^)\n]*,\s*['"][wax+]""")
SHOWS = re.compile(r'\bprint\(|console\.(?:log|dir|table)\(|(?:process|sys)\.stdout\.write\(')
INLINE = re.compile(r"""\b(?:python3?\s+-c|node\s+(?:-e|--eval|-p|--print))\s+(['"])""")
FILE_SCRIPT = re.compile(r'\b(?:python3?|node)\s+(?:--?[\w=-]+\s+)*[^\s|;&-][^\s|;&]*\.(?:py|mjs|cjs|js)\b')
DATA = ('.json', '.yaml', '.yml', '.toml')
PATH_LITERAL = re.compile(r"""['"`]([^'"`\s]+\.(?:js|mjs|cjs|ts|css|html|py|rb|go|rs|java|sh|md|json|yaml|yml|toml|txt))['"`]""")
LOOP = re.compile(r"""\bfor\s*\(?\s*(?:const\s+|let\s+|var\s+)?(\w+)\s+(?:in|of)\s+[\[(]([^\])]*)[\])]""")
LOADED = re.compile(r'\b(\w+)\s*=\s*(?:json\.load|JSON\.parse)\(')


def writes(text):
    """Whether a script writes a file: a write call, or .write( not on stdout or stderr."""
    if WRITES_OTHER.search(text):
        return True
    pos = 0
    while (i := text.find('.write(', pos)) >= 0:
        if not text[:i].endswith(('stdout', 'stderr')):
            return True
        pos = i + 7
    return False


def inline_scripts(line):
    """The code of each python -c or node -e in the line, up to its closing quote (one not escaped)."""
    out = []
    for m in INLINE.finditer(line):
        q, i = m.group(1), m.end()
        while (j := line.find(q, i)) >= 0:
            if line[j - 1] != '\\':
                out.append(line[m.end():j])
                break
            i = j + 1
    return out


def scripts(line, cwd):
    """The scripts a shell line runs: python -c and node -e code, a heredoc fed to python or node, a heredoc that cat
    writes outside the repository, and a script outside it run by name. A heredoc that is data is none."""
    env = dict(re.findall(r'(?:^|[;&\s])([A-Za-z_]\w*)=([^\s;&|]+)', line))
    expand_ = lambda p: re.sub(r'\$\{?(\w+)\}?', lambda m: env.get(m.group(1), m.group(0)), p.strip('\'"'))  # noqa: E731
    out = inline_scripts(line)
    for _, _, head, _, body in heredocs(line):
        if re.search(r'\b(?:python3?|node)\b', head) and not FILE_SCRIPT.search(head):
            out.append(body)
        elif (to := re.search(r'\bcat\s*>>?\s*(\S+)', head)) and ('$' in expand_(to.group(1)) or inside(expand_(to.group(1)), cwd) is None):
            out.append(body)
    for words, _, base in commands(line, cwd):
        if os.path.basename(words[0]) in ('node', 'python', 'python3') and len(words) > 1 and not words[1].startswith('-'):
            name = expand_(words[1])
            f = os.path.join(base, os.path.expanduser(name))
            if inside(name, base) is None and os.path.isfile(f) and os.path.getsize(f) < 300000:
                with open(f, encoding='utf-8', errors='replace') as script:
                    out.append(script.read())
    return out


def script_question(line, cwd):
    """The ask for a script that opens a file of the code or the docs and prints it without writing anything back."""
    out = []
    for text in scripts(line, cwd):
        if not SHOWS.search(text) or writes(text):
            continue
        names, paths = dict(NAMED_VAR.findall(text)), []
        for literal, var in READ_ARG.findall(text):
            if literal or var in names:
                paths.append(literal or names[var])
            else:
                paths += [p for v, items in LOOP.findall(text) if v == var for p in PATH_LITERAL.findall(items)]
        dumped = any(re.search(r'(?:json\.dumps|JSON\.stringify)\(\s*' + re.escape(v) + r'\b|(?:print|console\.log)\(\s*'
                               + re.escape(v) + r'\s*\)', text) for v in LOADED.findall(text))
        for p in paths:
            rel = inside(p, cwd)
            if mapped(rel, folder_ok=False) and (not rel.endswith(DATA) or dumped):
                out.append(rel)
    return list(dict.fromkeys(out)) or None
# @end map.guard.commands.scripts


def question(words, base):
    tool = os.path.basename(words[0])
    if tool == 'git' and words[1:2] == ['grep']:
        return grep_question(['grep', '-r'] + words[2:], base)
    if tool == 'xargs' and len(words) > 1 and os.path.basename(words[1]) in SEARCH:
        return grep_question(words[1:] + ['-r', '.'], base)
    if tool in SEARCH:
        return grep_question([tool] + words[1:], base)
    if tool in READ:
        return read_question([tool] + words[1:], base)
    if tool in LIST:
        return list_question([tool] + words[1:], base)
    return None


def shell_question(line, cwd):
    """The ask replacing a shell line, or None when it may go ahead."""
    if 'map.py' in line or ' map ' in ' ' + line.split('\n')[0] + ' ' and ASK.startswith('map '):
        return None
    asked, filtered, parts = script_question(line, cwd) or [], [], commands(line, cwd)
    for k, (words, piped, base) in enumerate(parts):
        if piped or any(w in ('>', '>>', '&>') for w in words) or not words:
            continue
        after = parts[k + 1] if k + 1 < len(parts) else None
        if words[0] == 'find' and after and after[1] and after[0][:1] == ['xargs'] and os.path.basename(after[0][1]) in SEARCH:
            pattern = next((words[j + 1] for j, a in enumerate(words) if a in ('-name', '-iname') and j + 1 < len(words)), '*')
            root = next((a for a in words[1:] if not a.startswith('-')), '.')
            q = grep_question(after[0][1:] + ['-r', root, '--include=' + pattern], base)
        else:
            q = question(words, base)
        if not q:
            continue
        pipe = []
        for w, fed, _ in parts[k + 1:]:
            if not fed or os.path.basename(w[0]) not in FILTERS:
                break
            pipe.append(quote(w))
        if pipe:
            filtered.append(ASK + quote(q) + ' | ' + ' | '.join(pipe))
        else:
            asked += q
    return '; '.join(([ASK + quote(asked)] if asked else []) + filtered) or None
# @end map.guard.commands


# @map map.guard.decide: each agent's input read into one shape, the ask that replaces the call, and the answer in the agent's format
def read_question_tool(file_path, cwd, offset=None, limit=None):
    """A file-reading tool on a whole mapped file: its ask; a range of lines (before an edit) goes ahead."""
    rel = inside(file_path or '', cwd)
    if not mapped(rel, folder_ok=False) or limit or offset:
        return None
    return ASK + quote([rel])


def normalise(agent, data):
    """(tool, given, cwd): the call as one shape, whichever agent sent it; tool is 'shell', 'read', 'grep', 'glob' or 'list'."""
    roots = data.get('workspace_roots')
    cwd = data.get('cwd') or (roots[0] if isinstance(roots, list) and roots else ROOT)
    if agent == 'cursor':
        if 'command' in data and 'tool_name' not in data:                    # beforeShellExecution
            return 'shell', {'command': data['command']}, cwd
        if 'file_path' in data and 'tool_name' not in data:                  # beforeReadFile
            return 'read', {'file_path': data['file_path']}, cwd
        name, given = str(data.get('tool_name', '')).lower(), data.get('tool_input') or {}
        cwd = given.get('working_directory') or cwd
        kind = 'shell' if name in ('shell', 'bash', 'terminal') else 'read' if name in ('read', 'read_file') else None
        return kind, given, cwd
    if agent == 'copilot':
        name = str(data.get('toolName') or data.get('tool_name') or '').lower()
        given = data.get('toolArgs') if 'toolArgs' in data else data.get('tool_input')
        if isinstance(given, str):
            try:
                given = json.loads(given)
            except ValueError:
                given = {'command': given}
        given = given or {}
        kind = {'bash': 'shell', 'powershell': 'shell', 'view': 'read', 'grep': 'grep', 'glob': 'glob'}.get(name)
        return kind, given, cwd
    if agent == 'gemini':
        name, given = str(data.get('tool_name', '')).lower(), data.get('tool_input') or {}
        kind = ('shell' if 'shell' in name else 'read' if name in ('read_file', 'read_many_files') else 'grep' if 'grep' in name or 'search_file' in name
                else 'glob' if name == 'glob' else 'list' if name == 'list_directory' else None)
        return kind, given, cwd
    name, given = data.get('tool_name', ''), data.get('tool_input') or {}          # claude, codex
    kind = {'Bash': 'shell', 'Read': 'read', 'Grep': 'grep', 'Glob': 'glob'}.get(name)
    return kind, given, cwd


def replacement(agent, data):
    """The map's question for this call, or None when the call may go ahead."""
    kind, given, cwd = normalise(agent, data)
    if not isinstance(given, dict):
        return None
    if kind == 'shell':
        return shell_question(given.get('command') or given.get('cmd') or '', cwd)
    if kind == 'read':
        paths = given.get('paths')
        path = given.get('file_path') or given.get('absolute_path') or given.get('path') or (paths[0] if isinstance(paths, list) and paths else '')
        return read_question_tool(path, cwd, given.get('offset'), given.get('limit'))
    if kind == 'grep':
        if given.get('output_mode') == 'count':
            return None
        words = ['rg'] + (['-i'] if given.get('-i') or given.get('case_insensitive') else []) + ['-e', given.get('pattern', '')]
        words += [given.get('path') or '.'] + (['--glob', given['glob']] if given.get('glob') else []) + (['--glob', given['include']] if given.get('include') else [])
        q = grep_question(words, cwd)
        return ASK + quote(q) if q else None
    if kind == 'glob':
        rel = inside(given.get('path') or '.', cwd)
        return ASK + quote([os.path.join('' if rel in (None, '.') else rel, given.get('pattern', ''))]) if mapped(rel) else None
    if kind == 'list':
        rel = inside(given.get('path') or '.', cwd)
        return ASK + quote([rel]) if mapped(rel) and rel != '.' else None
    return None


def detect(data):
    if 'cursor_version' in data or ('command' in data and 'tool_name' not in data) or ('file_path' in data and 'tool_name' not in data):
        return 'cursor'
    if 'toolName' in data or str(data.get('tool_name', '')) in ('bash', 'powershell', 'view', 'grep', 'glob', 'create', 'edit'):
        return 'copilot'
    if data.get('hook_event_name') == 'BeforeTool':
        return 'gemini'
    return 'claude'


def answer(agent, asked):
    reason = REASON + asked
    if agent == 'cursor':
        return {'permission': 'deny', 'user_message': 'map-guard: read it through the map (ask). ' + asked, 'agent_message': reason}
    if agent == 'copilot':
        return {'permissionDecision': 'deny', 'permissionDecisionReason': reason}
    if agent == 'gemini':
        return {'decision': 'deny', 'reason': reason}
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': reason}}


SETTINGS = {
    'claude': ('.claude/settings.json', lambda me: {'hooks': {'PreToolUse': [{'matcher': 'Bash|Read|Grep|Glob', 'hooks': [
        {'type': 'command', 'command': f'python3 "$CLAUDE_PROJECT_DIR/{me}"'}]}]}}),
    'codex': ('.codex/hooks.json', lambda me: {'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [
        {'type': 'command', 'command': f'python3 "$(git rev-parse --show-toplevel)/{me}" --agent codex', 'statusMessage': 'map-guard'}]}]}}),
    'cursor': ('.cursor/hooks.json', lambda me: {'version': 1, 'hooks': {
        'beforeShellExecution': [{'command': f'python3 {me} --agent cursor'}],
        'beforeReadFile': [{'command': f'python3 {me} --agent cursor'}]}}),
    'copilot': ('.github/hooks/map-guard.json', lambda me: {'version': 1, 'hooks': {'preToolUse': [
        {'type': 'command', 'bash': f'python3 {me} --agent copilot', 'timeoutSec': 10}]}}),
    'gemini': ('.gemini/settings.json', lambda me: {'hooks': {'BeforeTool': [{'matcher': 'run_shell_command|read_file|read_many_files|grep_search|glob|list_directory', 'hooks': [
        {'name': 'map-guard', 'type': 'command', 'command': f'python3 "$GEMINI_PROJECT_DIR/{me}" --agent gemini', 'timeout': 5000}]}]}}),
}


def merge(old, new):
    """new's hooks added to old's: lists joined (an entry already there once), dicts merged, other values taken from new."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = dict(old)
        for k, v in new.items():
            out[k] = merge(old[k], v) if k in old else v
        return out
    if isinstance(old, list) and isinstance(new, list):
        return old + [x for x in new if x not in old]
    return new


def install(agent):
    if agent not in SETTINGS:
        sys.exit(f'install <agent>: one of {", ".join(SETTINGS)}')
    me = os.path.relpath(os.path.abspath(__file__), ROOT).replace(os.sep, '/')
    path, make = SETTINGS[agent]
    full = os.path.join(ROOT, path)
    try:
        with open(full, encoding='utf-8') as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = {}
    new = merge(old, make(me))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as f:
        json.dump(new, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print(f'{path}: the map guard installed for {agent} ({me}).' + (' Codex runs project hooks once the .codex folder is trusted.' if agent == 'codex' else ''))


def main(argv):
    if argv[:1] == ['install'] and len(argv) == 2:
        return install(argv[1])
    if argv[:1] == ['try'] and len(argv) == 2:
        asked = shell_question(argv[1], os.getcwd())
        print(asked or 'goes ahead')
        return
    agent = argv[argv.index('--agent') + 1] if '--agent' in argv and argv.index('--agent') + 1 < len(argv) else None
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            return
        agent = agent or detect(data)
        asked = replacement(agent, data)
    except Exception:                                       # noqa: BLE001 — a guard that fails lets the call go ahead
        return
    if asked:
        print(json.dumps(answer(agent, asked), ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1:])
# @end map.guard.decide
