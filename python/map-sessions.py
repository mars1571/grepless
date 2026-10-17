#!/usr/bin/env python3
# @map map.sessions.read: a Claude Code transcript's model calls: the context each re-read, whether it only searched or read, its response time
"""map-sessions: how the agents' sessions on this repository went, read from Claude Code's transcripts
(~/.claude/projects/<this folder's slug>/*.jsonl). Measure before claiming: run it before and after adopting the map.

    python3 tools/map-sessions.py [--since YYYY-MM-DD] [session-id-prefix …]

One line per session: model calls; context re-read (every call's input, cache read and cache write tokens, in millions);
the calls that only searched or read (Read, Grep, Glob, tools/map.py, or shell lines made only of grep, sed, cat, head,
tail, ls, find and the like) and their share; how many of those went through the map; the asks and the questions per
ask (a round of questions in one call is the aim); the reads of the code or the docs that ran outside the map (judged
by map-guard.py's own rule); runs of 8 or more calls in a row that only searched or read; and the median response time
of the model under and over 300k tokens of context (seconds from the tool's result to the answer).
"""
import importlib.util
import json
import os
import pathlib
import re
import sys
from datetime import datetime

ROOT = pathlib.Path(os.environ.get('MAP_ROOT') or pathlib.Path(__file__).resolve().parent.parent)
PROJECTS = pathlib.Path.home() / '.claude' / 'projects'
LOOK = {'grep', 'egrep', 'fgrep', 'rg', 'ag', 'ack', 'cat', 'sed', 'head', 'tail', 'awk', 'nl', 'less', 'more',
        'ls', 'find', 'tree', 'wc', 'cut', 'sort', 'uniq', 'tr', 'xargs', 'column', 'echo', 'printf'}


def looks(tool, given):
    """'map', 'other' (grep, sed, Read … anywhere) or None: what a tool call does when it only searches or reads."""
    if tool in ('Read', 'Grep', 'Glob'):
        return 'other'
    if tool != 'Bash':
        return None
    line = given.get('command', '')
    if re.search(r'map(?:\.py|\.mjs)?\s+(ask|brief|find|history|deps|impact|recipe|where)\b', line):
        return 'map'
    line = re.sub(r'\d?>&\d|\d?>\s*/dev/null', ' ', line)
    if re.search(r'\bsed\s+-i|>\s*\S|\bnode\b|\bmake\b|\bnpx\b', line):
        return None
    for m in re.finditer(r'\bpython3?\s+(\S*)', line):
        if not m.group(1).endswith('map.py'):
            return None
    words = line.replace('|', ' | ').replace(';', ' ; ').replace('&&', ' && ').split()
    firsts = [w for k, w in enumerate(words) if k == 0 or words[k - 1] in ('|', ';', '&&', '||')]
    return 'other' if firsts and all(os.path.basename(w) in LOOK or w == 'cd' for w in firsts) else None


def guard():
    """map-guard.py's replacement(), the one judge of a read outside the map; None without it."""
    hook = pathlib.Path(__file__).resolve().parent / 'map-guard.py'
    if not hook.exists():
        return None
    spec = importlib.util.spec_from_file_location('map_guard', hook)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return lambda tool, given, cwd: module.replacement('claude', {'tool_name': tool, 'tool_input': given, 'cwd': cwd})


def questions(line):
    """The questions of each ask in a shell line: [n, …]."""
    out = []
    for m in re.finditer(r'map(?:\.py|\.mjs)?\s+ask\s+', line):
        rest = line[m.end():]
        end = len(rest)
        for stop in re.finditer(r'\d?>|\||;|&&|\n', rest):         # a redirection, a pipe or the next step
            end = stop.start()
            break
        words = rest[:end].split()
        out.append(sum(1 for k, w in enumerate(words) if not w.startswith('--') and (k == 0 or words[k - 1] != '--in')))
    return out


def stamp(s):
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def calls(path, judge=None):
    """[(context tokens, kind, response seconds)] per model call; the questions per ask; the reads outside the map that ran."""
    out, order, asked, uses, refused = {}, [], [], {}, set()
    prev = None
    for line in open(path, encoding='utf-8', errors='replace'):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        m, t = o.get('message') or {}, stamp(o.get('timestamp') or '')
        for x in m.get('content') or [] if isinstance(m.get('content'), list) else []:
            if isinstance(x, dict) and x.get('type') == 'tool_result' and 'through its map' in json.dumps(x.get('content')):
                refused.add(x.get('tool_use_id'))
        if o.get('type') != 'assistant' or not m.get('id'):
            prev = t or prev
            continue
        for x in m.get('content') or []:
            if isinstance(x, dict) and x.get('type') == 'tool_use':
                uses[x.get('id')] = (x.get('name'), x.get('input') or {}, o.get('cwd') or str(ROOT))
                n = sum(questions((x.get('input') or {}).get('command', ''))) if x.get('name') == 'Bash' else 0
                asked += [n] if n else []
        u = m.get('usage') or {}
        c = out.get(m['id'])
        if not c:
            c = out[m['id']] = {'ctx': 0, 'kinds': [], 'since': prev, 'last': t}
            order.append(m['id'])
        c['last'] = t or c['last']
        c['ctx'] = max(c['ctx'], sum(u.get(k) or 0 for k in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')))
        c['kinds'] += [looks(x.get('name'), x.get('input') or {}) for x in m.get('content') or []
                       if isinstance(x, dict) and x.get('type') == 'tool_use']
        prev = t or prev
    outside = sum(1 for k, (tool, given, cwd) in uses.items() if k not in refused and judge and judge(tool, given, cwd))
    rows = []
    for k in order:
        c = out[k]
        secs = (c['last'] - c['since']) if c['since'] and c['last'] and 0 < c['last'] - c['since'] < 600 else None
        rows.append((c['ctx'], None if not c['kinds'] or None in c['kinds'] else 'map' if 'map' in c['kinds'] else 'other', secs))
    return rows, asked, outside
# @end map.sessions.read


# @map map.sessions.report: one line per session and a total: calls, context re-read, the share that only searched or read, its runs, response times
def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def report(paths):
    judge, total = guard(), [0] * 9
    print(f'{"session":<19}{"calls":>6}{"read M":>8}{"search/read":>16}{"their M":>8}{"via map":>8}'
          f'{"asks":>6}{"q/ask":>6}{"outside":>8}{"runs 8+":>8}{"s <300k":>8}{"s >300k":>8}')

    def line(name, r, lo=None, hi=None):
        print(f'{name:<19}{r[0]:>6}{r[1] / 1e6:>8.1f}{r[2]:>9} ({r[2] / r[0]:>4.0%}){r[3] / 1e6:>8.1f}{r[4]:>8}'
              f'{r[5]:>6}{(r[6] / r[5] if r[5] else 0):>6.1f}{r[7] if judge else "-":>8}{r[8]:>8}'
              f'{(f"{lo:.1f}" if lo else "-"):>8}{(f"{hi:.1f}" if hi else "-"):>8}')
    all_lo, all_hi = [], []
    for p in paths:
        cs, asked, outside = calls(p, judge)
        if not cs:
            continue
        nav = [c for c in cs if c[1]]
        runs, run = 0, 0
        for c in cs + [(0, None, None)]:
            if c[1]:
                run += 1
            else:
                runs, run = runs + (run >= 8), 0
        row = [len(cs), sum(c[0] for c in cs), len(nav), sum(c[0] for c in nav), sum(1 for c in nav if c[1] == 'map'),
               len(asked), sum(asked), outside, runs]
        total = [total[k] + row[k] for k in range(len(row))]
        lo, hi = [c[2] for c in cs if c[2] and c[0] < 300_000], [c[2] for c in cs if c[2] and c[0] >= 300_000]
        all_lo, all_hi = all_lo + lo, all_hi + hi
        day = next((json.loads(x).get('timestamp', '')[:10] for x in open(p, encoding='utf-8', errors='replace')
                    if '"timestamp"' in x), '')
        line(f'{day} {p.stem[:8]}', row, median(lo), median(hi))
    if total[0]:
        line('all', total, median(all_lo), median(all_hi))


def main(args):
    since = args[args.index('--since') + 1] if '--since' in args else ''
    named = [a for k, a in enumerate(args) if a != '--since' and (k == 0 or args[k - 1] != '--since')]
    slug = str(ROOT).replace('/', '-').replace('.', '-')
    folders = [f for f in PROJECTS.glob(slug + '*') if f.is_dir()]
    found = sorted((p for f in folders for p in f.glob('*.jsonl')), key=lambda p: p.stat().st_mtime)
    if named:                                                    # a transcript named by its path is read wherever it is
        found = [x for a in named for x in ([pathlib.Path(a)] if a.endswith('.jsonl') else [p for p in found if p.stem.startswith(a)])]
    if not found:
        sys.exit(f'No transcripts for {ROOT} under {PROJECTS} (Claude Code writes them there).')
    report([p for p in dict.fromkeys(found) if not since or
            next((json.loads(x).get('timestamp', '') for x in open(p, encoding='utf-8', errors='replace')
                  if '"timestamp"' in x), '') >= since])


if __name__ == '__main__':
    main(sys.argv[1:])
# @end map.sessions.report
