#!/usr/bin/env python3
# @map map.guard.scope: what the map reads (the code and the docs of the repository), how a command's paths resolve, and the agents' hook formats
"""map-guard: a pre-tool hook that keeps agents reading the code and the docs through the map.

A call that would search or read the repository's code or docs with grep, rg, sed, cat, head, tail, awk, ls,
find, with a script that only prints them, or with the agent's own file-reading tool on a whole file, is
refused, and the refusal names the `ask` that answers the same question (the agent's own filters kept:
| head, | cut). In Claude Code a shell line made only of such reads (with the map, echo and filters that run no
command) is not refused: it runs through the map in its place, each read as its ask, and the agent is told so.
Everything else goes ahead: counting (grep -c, | wc), editing (sed -i, a redirection, a script that writes) and the
reads that check that edit in the same line, writing, pipes, tests, builds, the map itself, files git ignores, files
outside the repository, a range of lines before an edit.

    python3 tools/map-guard.py [--agent claude|codex|cursor|copilot|gemini]   the hook: stdin in, the decision out
    python3 tools/map-guard.py install <agent>      write the agent's hook settings for this repository
    python3 tools/map-guard.py try '<shell line>'   what the guard would answer for that line (nothing: it goes ahead)

Agents and their formats, as their docs give them (agents/README.md has the sources):
  claude   Claude Code: PreToolUse, stdin {tool_name, tool_input, cwd}; {"hookSpecificOutput": {"permissionDecision": "deny"}},
           or "allow" with "updatedInput" (the line run in its place) and "additionalContext"
  codex    Codex: PreToolUse with the same fields and answer (.codex/hooks.json)
  cursor   Cursor: beforeShellExecution {command, cwd} and beforeReadFile {file_path}; {"permission": "deny", "agent_message"}
  copilot  GitHub Copilot: preToolUse {toolName, toolArgs} or {tool_name, tool_input}; {"permissionDecision": "deny"}
  gemini   Gemini CLI: BeforeTool {tool_name, tool_input}; {"decision": "deny", "reason"}
Without --agent, the format is told from the fields. A guard that fails, or that cannot read its input, lets the
call go ahead. Python 3.9 or later, the standard library only; map.json (at the root) gives the command agents
run (`command`) and the paths the guard leaves alone (`guard.skip`, `ignore`).
"""
import fnmatch
import functools
import json
import os
import posixpath
import re
import sys

if os.name == 'nt':     # Windows: UTF-8 in and out, and LF out, as elsewhere (the default is the ANSI code page and CRLF)
    for _s in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(_s, 'reconfigure'):
            _s.reconfigure(encoding='utf-8', **({} if _s is sys.stdin else {'newline': '\n'}))


def root_form(p):
    """The root in the form realpath gives the paths under it: canonical on Windows (the drive letter's case, no \\\\?\\),
    and as found elsewhere."""
    return os.path.realpath(p) if os.name == 'nt' else p


def find_root():
    if os.environ.get('MAP_ROOT'):
        return os.path.realpath(os.environ['MAP_ROOT'])
    here = os.path.dirname(os.path.abspath(__file__))
    for start in (os.getcwd(), here):
        for mark in ('map.json', '.git'):
            base = start
            while True:
                if os.path.exists(os.path.join(base, mark)):
                    return root_form(base)
                up = os.path.dirname(base)
                if up == base:
                    break
                base = up
    return root_form(os.getcwd())


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
READ = {'cat', 'sed', 'head', 'tail', 'awk', 'nl', 'less', 'more', 'bat', 'cut', 'sort', 'uniq', 'strings', 'xxd', 'od', 'perl', 'ruby'}
FILE_FILTERS = {'cut': 'bcdf', 'sort': 'ktTS', 'uniq': 'fsw'}                            # filters that read a file given to them: the flags that take a value
LIST = {'ls', 'find', 'tree', 'fd'}
FILTERS = {'head', 'tail', 'cut', 'grep', 'egrep', 'sort', 'uniq', 'wc', 'sed', 'awk', 'tr', 'column'}
KEPT = {'head', 'tail', 'cut', 'grep', 'egrep', 'sort', 'uniq', 'wc', 'tr', 'column'}    # filters a line run in its place keeps: none runs a command or writes
QUIET = {'echo', 'printf', 'true', ':', 'wc'}                                            # steps a line run in its place keeps as they are
REASON = ("This repository's code and docs are read and located through its map, every question of a round in one call "
          '(AGENTS.md, "Finding code"); it answers what this would, by block, with the code. None of this command ran: '
          'send its other steps again. Run instead:\n  ')
REASON_LINE = ("This repository's code and docs are read and located through its map, every question of a round in one call "
               '(AGENTS.md, "Finding code"); it answers what this would, by block, with the code. None of this command ran: '
               'send this line instead, its reads already through the map. Run instead:\n  ')
NOTE = ('map-guard ran this line through the map, each read of the code or the docs as its ask (AGENTS.md, "Finding code"; '
        'next time, ask every question of a round in one call):\n  ')


def msys_path(p):
    """A Git Bash drive path (/c/Users/x, /cygdrive/c/x) as Windows names it (C:/Users/x); None on other systems and for any other path."""
    if os.name != 'nt':
        return None
    m = re.fullmatch(r'(?:/cygdrive)?/([A-Za-z])(/.*)?', p, re.S)
    return m and f'{m.group(1).upper()}:{m.group(2) or "/"}'


def expanduser(p):
    """os.path.expanduser; on Windows $HOME (else the profile) for a leading ~, and Git Bash's drive paths as Windows names them."""
    if os.name != 'nt':
        return os.path.expanduser(p)
    if p.startswith('~'):
        home = os.environ.get('HOME') or os.environ.get('USERPROFILE')
        if home:
            return os.path.join(msys_path(home) or home, p[1:].lstrip('/'))
    return msys_path(p) or p


def normpath(p):
    """os.path.normpath; on Windows with `/`, which the bash of the agent's lines reads as it is (it takes a backslash for an escape)."""
    p = os.path.normpath(p)
    return p.replace('\\', '/') if os.name == 'nt' else p


def root_word():
    """The root as a word of the shell line: on Windows with `/`, which bash reads as it is."""
    return quote_word(ROOT.replace('\\', '/') if os.name == 'nt' else ROOT)


def inside(path, base):
    """The path relative to the repository, or None when it is outside it."""
    full = os.path.realpath(os.path.join(base, expanduser(path)))
    if os.name == 'nt':
        if os.path.splitdrive(full)[0].lower() != os.path.splitdrive(ROOT)[0].lower():
            return None                                       # another drive: there is no relative path to it
        rel = os.path.relpath(full, ROOT).replace('\\', '/')   # agents write `/` on Windows too
    else:
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
    parts = rel.split('/')
    if any(p in SKIP for p in parts[:-1]) or parts[0] in SKIP:
        return True
    for p in IGNORED:
        if not p:
            continue
        folder, q = p.endswith('/'), p.strip('/')
        if '/' in q:
            if rel == q or rel.startswith(q + '/') or fnmatch.fnmatch(rel, q):
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
    """Whether the map answers for this path: a text file of the repository, or a folder holding one."""
    if rel is None:
        return False
    if re.search(r'[*?[]', rel):
        return any(mapped(x, folder_ok) for x in expand(rel)[:50])
    if rel == '.':
        return folder_ok
    if rel in ('map.yaml',) or rel.split('/')[0] == 'map':
        return False
    full = os.path.join(ROOT, rel)
    if os.path.isdir(full):
        return folder_ok and not ignored(rel) and holds_mapped(rel)
    if not os.path.exists(full):
        return False
    return is_text(rel) and not ignored(rel)


# @map map.guard.scope.folder: whether a folder holds a file the map reads (one that holds none is never sent to an ask)
FOLDER_SEEN = 50000                                     # files looked at in a folder; past them it is taken to hold one


@functools.lru_cache(maxsize=None)
def holds_mapped(rel):
    """Whether a folder holds a file the map reads, below the folders it leaves out: one that holds none is not sent to
    an ask, which would answer nothing."""
    seen = 0
    for base, dirs, names in os.walk(os.path.join(ROOT, rel)):
        here = os.path.relpath(base, ROOT).replace(os.sep, '/')
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not ignored(f'{here}/{d}'))
        for n in names:
            seen += 1
            if is_text(f'{here}/{n}') and not ignored(f'{here}/{n}'):
                return True
        if seen > FOLDER_SEEN:
            return True
    return False
# @end map.guard.scope.folder


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
QUIET_REDIRECT = r'&>\s*/dev/null|\d?>&\d|\d?>\s*/dev/null'     # stderr or all output thrown away: no word of the command


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
    line = re.sub(QUIET_REDIRECT, ' ', line)
    tokens = shell_words(line)
    split = []
    for t in tokens:
        split += re.findall(r'\|\||&&|\|&|;;|>>|&>|[|&;()<>]', t) if re.fullmatch(r'[|&;()<>]+', t) else [t]
    out, words, piped, base = [], [], False, cwd
    for t in split + [';']:
        if t in ('|', '||', '&&', ';', '&', '(', ')', '|&', ';;', '\n'):
            if words:
                if words[0] == 'cd' and len(words) > 1:
                    base = os.path.join(base, expanduser(words[1]))
                else:
                    out.append((words, piped, base))
            piped, words = t in ('|', '|&'), []
        else:
            words.append(t)
    return out


def grep_parts(words):
    """(patterns, paths, includes, flags) of a grep-like search."""
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
    return pats, paths, includes, flags


def grep_question(words, base):
    """The ask for a grep-like search over the code or the docs, or None when it searches elsewhere."""
    pats, paths, includes, flags = grep_parts(words)
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
        places = [posixpath.join(p, '*' + g.lstrip('*')) for p in (places or ['']) for g in includes]
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


def file_filter(words):
    """(the filter's words without its files, the files) of cut, sort or uniq; None when it writes (sort -o, uniq's output)."""
    tool, keep, files, skip = os.path.basename(words[0]), [words[0]], [], False
    for a in words[1:]:
        if skip:
            keep.append(a)
            skip = False
        elif a.startswith('--') and len(a) > 2:
            if a.startswith('--output'):
                return None
            keep.append(a)
        elif a.startswith('-') and len(a) > 1:
            if tool == 'sort' and 'o' in a[1:]:
                return None
            keep.append(a)
            skip = len(a) == 2 and a[1] in FILE_FILTERS[tool]
        else:
            files.append(a)
    return None if tool == 'uniq' and len(files) > 1 else (keep, files)


def read_files(words):
    """(script, files) of a read: sed's script (awk's program is passed over), and the files it names."""
    tool, args = words[0], words[1:]
    if tool in FILE_FILTERS:
        found = file_filter(words)
        return None, (found[1] if found else [])
    if tool in ('sed', 'awk'):
        rest = [a for a in args if not a.startswith('-')]
        return (rest[0] if rest and tool == 'sed' else None), rest[1:]
    return None, [a for k, a in enumerate(args) if not a.startswith('-') and not (k and args[k - 1] in ('-n', '-c', '-f', '-d'))]


def read_question(words, base):
    """The ask for reading a file of the code or the docs, or None when it reads elsewhere or writes."""
    tool, args = words[0], words[1:]
    if tool == 'sed' and any(a.startswith('-i') or a == '--in-place' for a in args):
        return None
    if tool in ('perl', 'ruby') and any(re.fullmatch(r'-\w*i\S*', a) for a in args):
        return None
    script, files = read_files(words)
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
        return [posixpath.join('' if rel == '.' else rel, '*' + pattern.lstrip('*')) if pattern else rel]
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
            f = os.path.join(base, expanduser(name))
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


def counts(pipe):
    """Whether a run of filters counts what it is fed: wc, or grep -c."""
    return any(os.path.basename(w[0]) == 'wc' or (os.path.basename(w[0]) in ('grep', 'egrep', 'fgrep')
               and grep_parts(w)[3] & {'c', '--count'}) for w in pipe)


def shell_question(line, cwd):
    """The ask replacing a shell line, or None when it may go ahead."""
    if 'map.py' in line or ' map ' in ' ' + line.split('\n')[0] + ' ' and ASK.startswith('map '):
        return None
    if line_writes(line, cwd):                              # an edit: the reads beside it check it
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
            pipe.append(w)
        if counts(pipe):
            continue                                        # a count: nothing of the files is read
        own = file_filter(words)[0] if os.path.basename(words[0]) in FILE_FILTERS else None      # cut -c1-9 file: the ask, then cut
        if own or pipe:
            filtered.append(ASK + quote(q) + ' | ' + ' | '.join(quote(w) for w in ([own] if own else []) + pipe))
        else:
            asked += q
    return '; '.join(([ASK + quote(asked)] if asked else []) + filtered) or None


# @map map.guard.commands.rewrite: a line that edits a file, whose reads check the edit; a line of reads only, run through the map in its place
SIMPLE_SED = re.compile(r'(?:\d+|\$)(?:,(?:\d+|\$))?p|\d+q')                       # sed -n 5,20p: a range of lines, nothing that runs or writes
SIMPLE_AWK = re.compile(r'NR\s*(?:>=|<=|==|<|>)\s*\d+(?:\s*&&\s*NR\s*(?:>=|<=|==|<|>)\s*\d+)?')   # awk 'NR>=5 && NR<=20'
SYNTAX = {'for', 'in', 'case', 'select', 'done', 'fi', 'esac', 'do', 'then', 'else', 'elif', 'if', 'while', 'until', '{', '}', '!', 'function'}
SEGMENT = re.compile(r'(\s*)((?:(?:do|then|else|elif|if|while|until|!|\{|time)\s+)*)(.*?)(\s*)', re.S)
GIT_READ = {'status', 'log', 'diff', 'show', 'rev-parse', 'branch'}
GIT_BRANCH_FLAGS = {'--list', '--all', '--remotes', '--verbose', '--show-current', '--no-color', '--color', '--ignore-case', '--merged',
                    '--no-merged', '--contains', '--no-contains', '--points-at', '--sort', '--format', '--abbrev', '--column', '--no-column'}
GIT_BRANCH_VALUES = {'--merged', '--no-merged', '--contains', '--no-contains', '--points-at', '--sort', '--format', '--abbrev'}


def line_writes(line, cwd):
    """Whether the line changes a file of the repository: sed -i, perl -i, a redirection or tee into it, patch, git
    apply, a script that writes."""
    for words, _, base in commands(line, cwd):
        tool = os.path.basename(words[0])
        targets = [words[k + 1] for k, w in enumerate(words[:-1]) if w in ('>', '>>', '&>')] + (words[1:] if tool == 'tee' else [])
        if any('$' not in t and not t.startswith('-') and inside(t, base) is not None for t in targets):
            return True
        if tool == 'patch' or (tool == 'git' and words[1:2] == ['apply']):
            return True
        if tool == 'sed' and any(a.startswith('-i') or a == '--in-place' for a in words[1:]):
            return True
        if tool in ('perl', 'ruby') and any(re.fullmatch(r'-\w*i\S*', a) for a in words[1:]):
            return True
    return any(writes(text) for text in scripts(line, cwd))


def is_map(words):
    """Whether a command runs the map itself (the command of map.json, any of its commands)."""
    head = ASK.split()[:-1]
    return words[:len(head)] == head


def whole(words, base):
    """Whether the map answers all a read names: no file or folder of it would be left out of its ask."""
    tool = os.path.basename(words[0])
    if tool == 'git' and words[1:2] == ['grep']:
        tool, words = 'grep', words[1:]
    if tool in SEARCH:
        return all(mapped(inside(p, base)) for p in grep_parts([tool] + words[1:])[1])
    if tool in READ:
        return all(mapped(inside(f, base), folder_ok=False) for f in read_files([tool] + words[1:])[1])
    if tool in ('ls', 'tree'):
        return all(mapped(inside(a, base)) for a in words[1:] if not a.startswith('-'))
    return tool == 'find'


def split_line(line):
    """[(separator before, text)]: the line cut at each ; && || | |& & newline ( ) outside quotes, every text exactly as
    written; None when it holds a heredoc, a $( ) or backticks that run (the line cannot be rebuilt)."""
    if heredocs(line):
        return None
    out, buf, sep, quote_, i, n = [], [], '', None, 0, len(line)
    while i < n:
        c, nxt = line[i], line[i + 1:i + 2]
        if quote_ == "'":
            quote_ = None if c == "'" else quote_
        elif c == '\\' and nxt:
            buf.append(line[i:i + 2])
            i += 2
            continue
        elif c == '`' or line.startswith('$(', i):
            return None
        elif quote_ == '"':
            quote_ = None if c == '"' else quote_
        elif c in '\'"':
            quote_ = c
        elif c == '#' and (not buf or buf[-1][-1:].isspace()):
            j = line.find('\n', i)
            j = n if j < 0 else j
            buf.append(line[i:j])
            i = j
            continue
        else:
            op = ('\n' if c == '\n' else ';;' if line.startswith(';;', i) else ';' if c == ';' else '||' if line.startswith('||', i)
                  else '|&' if line.startswith('|&', i) else '|' if c == '|' else '(' if c == '(' else ')' if c == ')' else
                  None if c != '&' or (buf and buf[-1][-1:] in ('<', '>')) or nxt == '>' else '&&' if nxt == '&' else '&')
            if op:
                out.append((sep, ''.join(buf)))
                sep, buf, i = op, [], i + len(op)
                continue
        buf.append(c)
        i += 1
    out.append((sep, ''.join(buf)))
    return out


def steps(line, cwd):
    """The line as a list of steps, each a dict: sep, lead, prefix (do, then, if …), core, trail (the text around it, kept as
    written), words (redirections to /dev/null left out), kind (syntax, cd or cmd), piped (a pipe feeds it) and base (the
    folder it runs in, cd and ( ) followed); None when the line cannot be rebuilt or a folder is unknown."""
    segs = split_line(line)
    if segs is None:
        return None
    out, base, stack = [], cwd, []
    for k, (sep, text) in enumerate(segs):
        if sep == '(':
            stack.append(base)
        elif sep == ')' and stack:
            base = stack.pop()
        lead, prefix, core, trail = SEGMENT.fullmatch(text).groups()
        words = shell_words(re.sub(QUIET_REDIRECT, ' ', core))
        names = [w for w in words if not re.fullmatch(r'[A-Za-z_]\w*=.*', w)]
        piped = k > 0 and sep in ('|', '|&')
        kind = 'syntax' if not names or words[0] in SYNTAX or not words else 'cd' if words[0] == 'cd' and not piped else 'cmd'
        step = {'sep': sep, 'lead': lead, 'prefix': prefix, 'core': core, 'trail': trail, 'words': words, 'kind': kind, 'piped': piped,
                'base': base, 'redirected': any(re.fullmatch(r'[<>&]+', w) for w in words)}
        out.append(step)
        if kind == 'cd':
            target = words[1] if len(words) == 2 else None
            base = None if target is None or '$' in target or target == '-' else normpath(os.path.join(base, expanduser(target)))
        if base is None and k + 1 < len(segs):
            return None
    return out


def anchored(base, text):
    """The text run in the folder it was written for: as it is at the root, else in a (cd root && …) of its own."""
    return text if os.path.realpath(base) == os.path.realpath(ROOT) else f'(cd {root_word()} && {text})'


# @map map.guard.commands.rewrite.readonly: the steps that only read and touch nothing outside the repository (git's read-only forms, which, --version, date, counts, filters), and the reads safe to keep as written
def git_read_only(words, base):
    """Whether a git command only reads this repository: status, log, diff, show, rev-parse, branch (listing)."""
    args, i = words[1:], 0
    while i < len(args) and args[i].startswith('-'):
        if args[i] == '-C' and i + 1 < len(args):
            base, i = os.path.join(base, expanduser(args[i + 1])), i + 2
        elif args[i] in ('--no-pager', '--no-optional-locks'):
            i += 1
        else:
            return False
    if inside('.', base) is None or i >= len(args) or args[i] not in GIT_READ:
        return False
    sub, rest = args[i], args[i + 1:]
    if sub == 'branch':
        listing = any(a in ('-l', '--list') or re.fullmatch(r'-[a-z]*l[a-z]*', a) for a in rest)
        for k, a in enumerate(rest):
            if a.startswith('--'):
                if a.split('=')[0] not in GIT_BRANCH_FLAGS:
                    return False
            elif a.startswith('-'):
                if not re.fullmatch(r'-[arvli]+', a):
                    return False
            elif not (listing or (k and rest[k - 1] in GIT_BRANCH_VALUES)):
                return False                                  # a name with no listing flag makes a branch
        return True
    return not any(a in ('-O', '--open-files-in-pager', '--no-index', '--ext-diff', '--output') or a.startswith(('-O', '--output=')) for a in rest)


def date_read_only(args):
    return all(a.startswith('+') or a in ('-u', '--utc', '--universal', '-R', '--rfc-email') or re.fullmatch(r'-I\w*|--iso-8601(=\w+)?', a) for a in args)


def inside_all(operands, base):
    return all(inside(a, base) is not None for a in operands)


def safe_head(words, base):
    """Whether a read of the repository stays safe as it was written: a search that only counts, cat, head, tail, ls …, sed
    with a range, awk with NR conditions; every file in the repository and nothing that runs a command or writes."""
    tool, args = os.path.basename(words[0]), words[1:]
    operands = [a for a in args if not a.startswith('-')]
    if tool in SEARCH:
        pats, paths, _, _ = grep_parts(words)
        return not any(a.split('=')[0] in ('--pre', '--hostname-bin') for a in args) and inside_all(paths or ['.'], base)
    if tool in ('cat', 'head', 'tail', 'nl', 'ls', 'tree'):
        return inside_all(operands, base)
    if tool in FILE_FILTERS:
        return file_filter(words) is not None and inside_all(operands, base)
    if tool == 'find':
        return not any(a in ('-exec', '-execdir', '-ok', '-okdir', '-delete') or a.startswith(('-fprint', '-fls')) for a in args) and inside_all(operands[:1] or ['.'], base)
    if tool == 'sed':
        return set(a for a in args if a.startswith('-')) <= {'-n', '-E', '-r'} and bool(operands) and SIMPLE_SED.fullmatch(operands[0]) is not None and inside_all(operands[1:], base)
    if tool == 'awk':
        return not any(a.startswith('-') for a in args) and bool(operands) and SIMPLE_AWK.fullmatch(operands[0]) is not None and inside_all(operands[1:], base)
    return False


def safe_step(words, base):
    """Whether a step that is no read of the map's may stay in a line Claude Code runs without asking: it only reads and
    touches nothing outside the repository."""
    tool, args = os.path.basename(words[0]), words[1:]
    if is_map(words) or tool in ('echo', 'printf', 'true', ':', 'pwd'):
        return True
    if tool == 'wc':
        return inside_all([a for a in args if not a.startswith('-')], base)
    if tool == 'date':
        return date_read_only(args)
    if tool == 'which':
        return all(not a.startswith('-') or a in ('-a', '-s') for a in args)
    if words[0] == 'command':
        return len(words) > 2 and words[1] in ('-v', '-V')
    if len(words) == 2 and args == ['--version'] and '/' not in words[0]:
        return True
    if tool == 'git':
        return git_read_only(words, base)
    return tool in SEARCH and safe_head(words, base)                                   # grep -c file, grep -q …: a count or a yes


def filter_ok(words):
    """Whether a filter in a pipe is kept: head, tail, cut, grep, sort, uniq, wc, tr, column, or sed -n with a range."""
    if os.path.basename(words[0]) in KEPT:
        return True
    return (os.path.basename(words[0]) == 'sed' and set(a for a in words[1:] if a.startswith('-')) <= {'-n'}
            and [a for a in words[1:] if not a.startswith('-')] != [] and len([a for a in words[1:] if not a.startswith('-')]) == 1
            and SIMPLE_SED.fullmatch([a for a in words[1:] if not a.startswith('-')][0]) is not None)


# @end map.guard.commands.rewrite.readonly


def chain_read(chain):
    """What a pipeline's first command is: ('read', ask, steps replaced) for a read the map answers, ('count',) for one that
    only counts, ('step',) for anything else, ('syntax',) for a loop's keywords, an assignment or a cd."""
    first = chain[0]
    words, base = first['words'], first['base']
    if first['kind'] != 'cmd':
        return ('syntax',)
    if first['redirected']:
        return ('step',)
    if os.path.basename(words[0]) == 'find' and len(chain) > 1 and chain[1]['words'][:1] == ['xargs'] and len(chain[1]['words']) > 1 and os.path.basename(chain[1]['words'][1]) in SEARCH:
        pattern = next((words[j + 1] for j, a in enumerate(words) if a in ('-name', '-iname') and j + 1 < len(words)), '*')
        root = next((a for a in words[1:] if not a.startswith('-')), '.')
        q = grep_question(chain[1]['words'][1:] + ['-r', root, '--include=' + pattern], base)
        return ('read', ASK + quote(q), 2) if q else ('step',)
    q = question(words, base)
    if not q:
        return ('step',)
    run = []
    for s in chain[1:]:
        if not s['words'] or os.path.basename(s['words'][0]) not in FILTERS:
            break
        run.append(s['words'])
    if counts(run):
        return ('count',)
    own = file_filter(words)[0] if os.path.basename(words[0]) in FILE_FILTERS else None
    return ('read', ASK + quote(q) + (' | ' + quote(own) if own else ''), 1)


def rebuild(line, cwd, in_place):
    """(text, replaced, ok, pure) of the line with each read of the code or the docs as its ask, every other step as it was
    written: in place (Claude Code: from the root, cd steps dropped, steps outside the root in a (cd …) of their own) or to
    send again (each ask in a (cd root && …) when the line is not at the root). ok: every step only reads; pure: reads and
    their filters only. None when the line cannot be rebuilt."""
    st = steps(line, cwd)
    if st is None or script_question(line, cwd):
        return None
    out, replaced, ok, pure, k = [], False, True, True, 0
    while k < len(st):
        j = k + 1
        while j < len(st) and st[j]['piped']:
            j += 1
        chain, first = st[k:j], st[k]
        kind = chain_read(chain)
        used = kind[2] if kind[0] == 'read' else 1
        for s in chain[used:]:
            ok = ok and bool(s['words']) and filter_ok(s['words']) and not s['redirected']
            pure = pure and bool(s['words']) and os.path.basename(s['words'][0]) in FILTERS
        if kind[0] == 'syntax':
            if first['kind'] == 'cd' and in_place:
                out.append({**first, 'drop': 'transfer'})
            else:
                out.append(first)
        elif kind[0] == 'read':
            replaced = True
            ok = ok and used == 1 and whole(first['words'], first['base'])          # xargs could run anything
            text = first['lead'] + first['prefix'] + (kind[1] if in_place else anchored(first['base'], kind[1])) + first['trail']
            out.append({**first, 'text': text})
            if used == 2:
                out.append({**chain[1], 'drop': 'own'})
        else:
            pure = False
            words = first['words']
            ok = ok and not first['redirected'] and (safe_head(words, first['base']) and whole(words, first['base']) if kind[0] == 'count' else safe_step(words, first['base']))
            text = first['lead'] + first['prefix'] + first['core'] + first['trail']
            if in_place and os.path.realpath(first['base']) != os.path.realpath(ROOT):
                text = first['lead'] + first['prefix'] + f'(cd {quote_word(first["base"])} && {first["core"].strip()})' + first['trail']
            out.append({**first, 'text': text})
        out += [s for s in chain[used:]]
        k = j
    pieces, carry = [], None
    for s in out:
        sep = s['sep'] if carry is None else carry
        if s.get('drop') == 'transfer':
            carry = s['sep']
            continue
        carry = None
        if s.get('drop') == 'own':
            continue
        pieces.append((sep, s.get('text', s['lead'] + s['prefix'] + s['core'] + s['trail'])))
    text = ''.join(sep + t for sep, t in pieces)
    return text, replaced, ok, pure


def rewrite(line, cwd):
    """The line run through the map in its place, from the root: each read of the code or the docs as its ask, every other step
    as written, in order; None when a step does more than read, or a filter could run a command."""
    built = rebuild(line, cwd, True)
    if not built or not built[1] or not built[2]:
        return None
    return f'(cd {root_word()} && ' + built[0].strip() + ')'


def resend(line, cwd):
    """The whole line to send again when it is refused and mixed (reads beside other steps): each read as its ask, every other
    step exactly as written, the same separators; None when it is reads only (the refusal names their asks) or cannot be rebuilt."""
    built = rebuild(line, cwd, False)
    return built[0] if built and built[1] and not built[3] else None
# @end map.guard.commands.rewrite
# @end map.guard.commands


# @map map.guard.decide: each agent's input read into one shape, the ask that replaces the call, and the answer in the agent's format
def read_question_tool(file_path, cwd, offset=None, limit=None):
    """A file-reading tool on a whole mapped file: its ask; a range of lines (before an edit) goes ahead."""
    rel = inside(file_path or '', cwd)
    if not mapped(rel, folder_ok=False) or limit or offset:
        return None
    return ASK + quote([rel])


# @map map.guard.decide.glob: the ask for a Glob, only when the map holds a file the pattern names (never an ask that answers 0 files)
GLOB_WILD = re.compile(r'[*?[{]')
GLOB_SEEN = 50000                                       # files looked at for a match; past them the call goes ahead


def glob_question(folder, pattern, cwd):
    """The ask for a Glob, or None when it goes ahead, as a Grep, a Read or a shell line on the same place does. The
    pattern is split at its first wildcard segment (* ? [ {): the literal folder before it, under the tool's folder, must
    be a place the map reads (inside the repository, not ignored, not the map's own), and the pattern, matched as ask
    matches it (fnmatch on the path less its leading . and /), must name a file the map reads there. A pattern with
    no wildcard is that file or folder."""
    pat = expanduser(pattern)
    if os.name == 'nt':
        pat = pat.replace('\\', '/')                    # a Windows pattern may use either separator
    parts = pat.split('/')
    k = next((i for i, s in enumerate(parts) if GLOB_WILD.search(s)), len(parts))
    lit = '/'.join(parts[:k]) or ('/' if pat.startswith('/') else '')
    rel = inside(os.path.join(folder, lit + '/' if re.fullmatch(r'[A-Za-z]:', lit) else lit), cwd)
    if rel is None:
        return None
    rest = '/'.join(parts[k:])
    if not rest:
        return ASK + quote([rel]) if mapped(rel) and rel != '.' else None
    q = posixpath.join('' if rel == '.' else rel, rest)
    if not mapped(rel) or '/' not in q or not re.search(r'[*?]', q) or re.search(r'[\\|()+^$]', q):
        return None                                     # ignored, or a pattern that ask does not read as a glob
    want, seen = q.lstrip('./'), 0
    for base, dirs, names in os.walk(os.path.join(ROOT, rel)):
        here = os.path.relpath(base, ROOT).replace(os.sep, '/')
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not ignored(d if here == '.' else f'{here}/{d}'))
        for n in names:
            path = n if here == '.' else f'{here}/{n}'
            seen += 1
            if fnmatch.fnmatch(path, want) and mapped(path, folder_ok=False):
                return ASK + quote([q])
        if seen > GLOB_SEEN:
            break
    return None
# @end map.guard.decide.glob


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
    if kind == 'read':                                      # a range is offset and limit, or Gemini's start_line and end_line
        paths = given.get('paths')
        path = given.get('file_path') or given.get('absolute_path') or given.get('path') or (paths[0] if isinstance(paths, list) and paths else '')
        return read_question_tool(path, cwd, given.get('offset') or given.get('start_line'), given.get('limit') or given.get('end_line'))
    folder = given.get('path') or given.get('dir_path') or '.'         # Gemini names the folder dir_path
    if kind == 'grep':
        if given.get('output_mode') == 'count':
            return None
        words = ['rg'] + (['-i'] if given.get('-i') or given.get('case_insensitive') else []) + ['-e', given.get('pattern', '')]
        words += [folder] + (['--glob', given['glob']] if given.get('glob') else []) + (['--glob', given['include']] if given.get('include') else [])
        q = grep_question(words, cwd)
        return ASK + quote(q) if q else None
    if kind == 'glob':
        return glob_question(folder, given.get('pattern') or '', cwd)
    if kind == 'list':
        rel = inside(folder, cwd)
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


def decide(agent, data):
    """The hook's answer for this call, or None when it goes ahead: in Claude Code a shell line of reads only runs
    through the map in its place; any other read of the code or the docs is refused with its ask."""
    asked = replacement(agent, data)
    if not asked:
        return None
    kind, given, cwd = normalise(agent, data)
    command = given.get('command') or ''
    line = rewrite(command, cwd) if agent == 'claude' and kind == 'shell' else None
    if line:
        return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'allow',
                                       'permissionDecisionReason': 'map-guard: read through the map',
                                       'updatedInput': {**given, 'command': line}, 'additionalContext': NOTE + line}}
    return answer(agent, asked, resend(command, cwd) if kind == 'shell' else None)


def answer(agent, asked, again=None):
    """The refusal: the asks, or, for a line of reads beside other steps, the whole line to send again."""
    reason = (REASON_LINE + again) if again else REASON + asked
    if agent == 'cursor':
        return {'permission': 'deny', 'user_message': 'map-guard: read it through the map (ask). ' + (again or asked), 'agent_message': reason}
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
        {'type': 'command', 'bash': f'python3 {me} --agent copilot',
         **({'powershell': f'python3 {me} --agent copilot'} if os.name == 'nt' else {}),                         # Windows: PowerShell too
         'cwd': '.', 'timeoutSec': 10}]}}),                                                                      # cwd: the repository's root
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
    here, top = os.path.realpath(__file__), os.path.realpath(ROOT)                  # links resolved on both sides
    me = (here if os.name == 'nt' and os.path.splitdrive(here)[0].lower() != os.path.splitdrive(top)[0].lower()
          else os.path.relpath(here, top)).replace(os.sep, '/')                      # on another drive: the full path
    path, make = SETTINGS[agent]
    full = os.path.join(ROOT, path)
    try:
        with open(full, encoding='utf-8') as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = {}
    new = merge(old, make(me))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8', newline='\n') as f:                      # LF on every system
        json.dump(new, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print(f'{path}: the map guard installed for {agent} ({me}).' + (' Codex runs project hooks once the .codex folder is trusted.' if agent == 'codex' else ''))


def main(argv):
    if argv[:1] == ['install'] and len(argv) == 2:
        return install(argv[1])
    if argv[:1] == ['try'] and len(argv) == 2:
        asked = shell_question(argv[1], os.getcwd())
        print(asked or 'goes ahead')
        line = asked and rewrite(argv[1], os.getcwd())
        if line:
            print('Claude Code runs in its place: ' + line)
        elif asked and resend(argv[1], os.getcwd()):
            print('Send instead: ' + resend(argv[1], os.getcwd()))
        return
    agent = argv[argv.index('--agent') + 1] if '--agent' in argv and argv.index('--agent') + 1 < len(argv) else None
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            return
        agent = agent or detect(data)
        out = decide(agent, data)
    except Exception:                                       # noqa: BLE001 — a guard that fails lets the call go ahead
        return
    if out:
        print(json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1:])
# @end map.guard.decide
