#!/usr/bin/env python3
# @map article.analysis.rates: one project's cost of writing code: tokens of context and work time per 1,000 lines the agent wrote, read from its transcripts
"""Tokens re-read and work time per 1,000 lines an agent wrote, over one project's Claude Code sessions. The
article's projection multiplies these rates by the size of a large codebase.

    python3 article/analysis/rates.py --project ~/.claude/projects/<project folder> [--exclude TEXT] [--min-calls 20] [--out DIR]

Lines written: every line of a file the agent wrote whole (Write), of each replacement it made (Edit or the new
text of a search-and-replace script, between ======= and >>>>>>>), and of the files it wrote from a shell
here-document; rewrites count again, so this is more than the lines that survive.
Work time: the gaps of the transcript that end in the model's answer (the model working) or in a tool's result (the
tool working); the time a session waits for the person is left out. Prints the rates; with --out DIR it also writes
rates.json there (the article's data: --out article/data).
"""
import json
import pathlib
import re
import sys
from datetime import datetime

USAGE = __doc__.split('\n\n')[1]


def opt(args, name, default):
    return args[args.index(name) + 1] if name in args else default


def stamp(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()


# @map article.analysis.lines: one session's lines written, context tokens and work time (model and tools)
def lines_in(name, given, command):
    if name == 'Write':
        return str(given.get('content', '')).count('\n') + 1
    if name == 'Edit':
        return str(given.get('new_string', '')).count('\n') + 1
    if name == 'Bash' and '=======\n' in command and '\n>>>>>>>' in command:     # a search-and-replace script's new text
        return sum(b.count('\n') + 1 for b in re.findall(r'=======\n(.*?)\n>>>>>>>', command, re.S))
    if name == 'Bash' and re.search(r'cat\s*>\s*\S+\s*<<', command):
        return sum(b.count('\n') + 1 for b in re.findall(r"<<-?\s*'?\w+'?\n(.*?)\n\w+\s*(?:\n|$)", command, re.S))
    return 0


def session(path):
    context, lines, model_s, tool_s = {}, 0, 0.0, 0.0
    prev = None
    for raw in open(path, encoding='utf-8', errors='replace'):
        try:
            o = json.loads(raw)
        except ValueError:
            continue
        t = o.get('timestamp')
        if not t:
            continue
        m = o.get('message') or {}
        content = m.get('content')
        is_tool_result = o.get('type') == 'user' and isinstance(content, list) and any(
            isinstance(x, dict) and x.get('type') == 'tool_result' for x in content)
        now = stamp(t)
        if prev is not None and o.get('type') == 'assistant':
            model_s += now - prev
        elif prev is not None and is_tool_result:
            tool_s += now - prev
        prev = now
        if o.get('type') == 'assistant' and m.get('id'):
            u = m.get('usage') or {}
            context[m['id']] = max(context.get(m['id'], 0), sum(u.get(k) or 0 for k in
                                   ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')))
            for x in content or []:
                if isinstance(x, dict) and x.get('type') == 'tool_use':
                    given = x.get('input') or {}
                    lines += lines_in(x.get('name'), given, str(given.get('command', '')))
    return {'calls': len(context), 'tokens': sum(context.values()), 'lines': lines, 'model_s': model_s, 'tool_s': tool_s}
# @end article.analysis.lines


# @map article.analysis.total: the project's sessions summed into rates per 1,000 lines written
def main(args):
    if '-h' in args or '--help' in args or '--project' not in args:
        print(USAGE)
        return 0 if '--project' in args else 2
    folder = pathlib.Path(opt(args, '--project', '')).expanduser()
    exclude = opt(args, '--exclude', None)
    least = int(opt(args, '--min-calls', '20'))
    out = opt(args, '--out', None)
    rows = []
    for f in sorted(folder.glob('*.jsonl')):
        if exclude and exclude in f.name:
            continue
        s = session(f)
        if s['calls'] >= least and s['lines']:
            rows.append(s)
    if not rows:
        print(f'no session with {least} or more calls that wrote code in {folder}', file=sys.stderr)
        return 1
    tokens, lines = sum(r['tokens'] for r in rows), sum(r['lines'] for r in rows)
    model_h, tool_h = sum(r['model_s'] for r in rows) / 3600, sum(r['tool_s'] for r in rows) / 3600
    rates = {'sessions': len(rows), 'calls': sum(r['calls'] for r in rows), 'lines_written': lines,
             'tokens_B': round(tokens / 1e9, 2), 'work_hours': round(model_h + tool_h, 1),
             'model_hours': round(model_h, 1), 'tool_hours': round(tool_h, 1),
             'per_1000_lines': {'tokens_M': round(tokens / lines / 1e3, 2), 'work_min': round((model_h + tool_h) * 60 / lines * 1000, 2)},
             'source': f'the main sessions of one project with {least} or more model calls that wrote code; lines written as '
                       'Write, Edit, search-and-replace scripts and here-documents count them (rewrites included); work time = '
                       'the model answering plus the tools running, waits for the person left out'}
    if out:
        out = pathlib.Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / 'rates.json').write_text(json.dumps(rates, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(rates, indent=1))
    return 0
# @end article.analysis.total


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
