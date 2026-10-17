#!/usr/bin/env python3
# @map article.analysis.transcripts: the article's measurements over many sessions, read from Claude Code's transcripts: scale, tokens by kind, cost shares, response time by context
"""The numbers the article measures across sessions, from the transcripts Claude Code keeps on disk
(~/.claude/projects/<project>/*.jsonl, and <session>/subagents/*.jsonl for the sub-agents a session starts).
Run it on your own transcripts to see whether your sessions look like the article's:

    python3 article/analysis/transcripts.py [--root DIR] [--until YYYY-MM-DD] [--exclude TEXT] [--min-calls 20] [--out DIR]

A model call is one assistant message id; its context is the input, cache-read and cache-write tokens of its usage.
Its response time is the seconds from the transcript line before it (usually a tool's result) to its last line;
calls under 0.3 s or over 300 s are left out of the times. Prints what it finds; with --out DIR it also writes
scale.json and latency-by-context.json there (the article's data: --out article/data). Nothing is sent anywhere,
and no transcript text is copied, only counts.

The article's data: --until 2026-10-12 --exclude <the session that wrote the article> --out article/data.
"""
import collections
import json
import pathlib
import statistics
import sys
from datetime import date, datetime

USAGE = __doc__.split('\n\n')[1]
# List prices in dollars per million tokens, from https://platform.claude.com/docs/en/about-claude/pricing (read
# 2026-10-17): input, 5-minute cache write, 1-hour cache write, cache read, output. A model not listed here is priced
# as the first one; the article's sessions made 97 % of their calls to these two.
PRICES = {'claude-opus-5-5': (4.0, 5.0, 8.0, 0.20, 20.0), 'claude-sonnet-5-5': (2.0, 2.5, 4.0, 0.10, 10.0)}
SHORT = 200            # a reply of fewer output tokens than this is "short": its time is mostly reading the context


def opt(args, name, default):
    return args[args.index(name) + 1] if name in args else default


def stamp(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()


# @map article.analysis.read: one transcript read into its model calls: context, tokens by kind, model, response time
def read(path):
    calls, order, prev = {}, [], None
    for line in open(path, encoding='utf-8', errors='replace'):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        m, t = o.get('message') or {}, o.get('timestamp')
        if not t:
            continue
        if o.get('type') == 'assistant' and m.get('id'):
            c = calls.get(m['id'])
            if not c:
                c = calls[m['id']] = {'first': stamp(t), 'last': stamp(t), 'prev': prev, 'model': m.get('model'),
                                      'u': collections.Counter()}
                order.append(m['id'])
            c['last'] = max(c['last'], stamp(t))
            u = m.get('usage') or {}
            for k in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'output_tokens'):
                c['u'][k] = max(c['u'][k], u.get(k) or 0)
            for k in ('ephemeral_5m_input_tokens', 'ephemeral_1h_input_tokens'):
                c['u'][k] = max(c['u'][k], (u.get('cache_creation') or {}).get(k) or 0)
        prev = stamp(t)
    out = []
    for k in order:
        c = calls[k]
        u = c['u']
        out.append({'ctx': u['input_tokens'] + u['cache_read_input_tokens'] + u['cache_creation_input_tokens'],
                    'u': u, 'model': c['model'], 'first': c['first'],
                    'secs': c['last'] - c['prev'] if c['prev'] is not None else None})
    return out
# @end article.analysis.read


# @map article.analysis.measure: the sessions chosen, then their scale, tokens by kind, cost shares and response time by context
def main(args):
    if '-h' in args or '--help' in args:
        print(USAGE)
        return 0
    root = pathlib.Path(opt(args, '--root', str(pathlib.Path.home() / '.claude' / 'projects'))).expanduser()
    until = opt(args, '--until', None)
    until = date.fromisoformat(until) if until else None
    exclude = opt(args, '--exclude', None)
    least = int(opt(args, '--min-calls', '20'))
    out = opt(args, '--out', None)
    sessions = []
    for f in sorted(root.rglob('*.jsonl')):
        if exclude and exclude in str(f):
            continue
        calls = read(f)
        if len(calls) < least:
            continue
        if until and datetime.fromtimestamp(min(c['first'] for c in calls)).date() > until:
            continue
        sessions.append({'kind': 'sub-agent' if 'subagents' in f.parts else 'session',
                         'project': f.relative_to(root).parts[0], 'calls': calls})
    if not sessions:
        print(f'no transcript with {least} or more model calls under {root}', file=sys.stderr)
        return 1
    calls = [c for s in sessions for c in s['calls']]
    kinds = collections.Counter()
    for c in calls:
        kinds.update(c['u'])
    context = kinds['input_tokens'] + kinds['cache_read_input_tokens'] + kinds['cache_creation_input_tokens']
    total = context + kinds['output_tokens']
    cost = collections.Counter()
    priced = 0
    for c in calls:
        u = c['u']
        inp, w5p, w1p, readp, outp = PRICES.get(c['model'], next(iter(PRICES.values())))
        priced += c['model'] in PRICES
        w5, w1 = u['ephemeral_5m_input_tokens'], u['ephemeral_1h_input_tokens']
        w_other = max(0, u['cache_creation_input_tokens'] - w5 - w1)
        cost['cache reads'] += readp * u['cache_read_input_tokens'] / 1e6
        cost['cache writes'] += (w5p * (w5 + w_other) + w1p * w1) / 1e6
        cost['uncached input'] += inp * u['input_tokens'] / 1e6
        cost['output'] += outp * u['output_tokens'] / 1e6
    days = [datetime.fromtimestamp(c['first']).date() for c in calls]
    main_n = sum(1 for s in sessions if s['kind'] == 'session')
    scale = {'sessions': len(sessions), 'main_sessions': main_n, 'sub_agents': len(sessions) - main_n,
             'projects': len({s['project'] for s in sessions}), 'calls': len(calls), 'tokens_B': round(context / 1e9, 2),
             'first_day': str(min(days)), 'last_day': str(max(days)),
             'tokens_by_kind_percent': {'cache reads (context already seen)': round(kinds['cache_read_input_tokens'] * 100 / total, 2),
                                        'cache writes (new context)': round(kinds['cache_creation_input_tokens'] * 100 / total, 2),
                                        'uncached input': round(kinds['input_tokens'] * 100 / total, 2),
                                        'output (what the model wrote)': round(kinds['output_tokens'] * 100 / total, 2)},
             'tokens_by_kind_M': {'cache reads': round(kinds['cache_read_input_tokens'] / 1e6, 1),
                                  'cache writes': round(kinds['cache_creation_input_tokens'] / 1e6, 1),
                                  'uncached input': round(kinds['input_tokens'] / 1e6, 1), 'output': round(kinds['output_tokens'] / 1e6, 1)},
             'cost_shares_percent': {k: round(v * 100 / sum(cost.values()), 1) for k, v in cost.items()},
             'cost_at_list_prices_usd': round(sum(cost.values())),
             'calls_priced_at_their_own_model_percent': round(priced * 100 / len(calls), 1),
             'prices_usd_per_million': {m: dict(zip(('input', 'cache write 5m', 'cache write 1h', 'cache read', 'output'), v))
                                        for m, v in PRICES.items()},
             'calls_by_model': dict(collections.Counter(c['model'] or 'unknown' for c in calls).most_common()),
             'source': f'every Claude Code transcript under the projects folder with {least} or more model calls (sessions and the '
                       'sub-agents they started); context = input + cache read + cache write tokens of each call'}

    def median_by_bucket(pick):
        rows = []
        for lo in range(0, 1000, 100):
            lat = sorted(c['secs'] for c in calls if pick(c) and c['secs'] and 0.3 < c['secs'] < 300
                         and lo * 1000 <= c['ctx'] < (lo + 100) * 1000)
            rows.append((lo, lat))
        return rows
    buckets = []
    short = dict(median_by_bucket(lambda c: c['u']['output_tokens'] < SHORT))
    top = collections.Counter(c['model'] for c in calls).most_common(1)[0][0]
    one = dict(median_by_bucket(lambda c: c['model'] == top))
    for lo, lat in median_by_bucket(lambda c: True):
        if len(lat) < 30:
            continue
        outs = [c['u']['output_tokens'] for c in calls if lo * 1000 <= c['ctx'] < (lo + 100) * 1000]
        b = {'from_k': lo, 'to_k': lo + 100, 'calls': len(lat), 'median_s': round(statistics.median(lat), 2),
             'p25_s': round(lat[len(lat) // 4], 2), 'p75_s': round(lat[3 * len(lat) // 4], 2),
             'median_output_tokens': int(statistics.median(outs))}
        if len(short[lo]) >= 30:
            b.update(short_calls=len(short[lo]), short_median_s=round(statistics.median(short[lo]), 2))
        if len(one[lo]) >= 30:
            b.update(one_model_calls=len(one[lo]), one_model_median_s=round(statistics.median(one[lo]), 2))
        buckets.append(b)
    latency = {'buckets': buckets, 'sessions': len(sessions), 'projects': scale['projects'], 'short_reply_tokens': SHORT,
               'one_model': top,
               'source': 'the same sessions: seconds from the transcript line before each call (usually a tool result) to the '
                         f'call\'s last line; calls under 0.3 s or over 300 s left out. Short: a reply under {SHORT} output tokens.'}
    if out:
        out = pathlib.Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / 'scale.json').write_text(json.dumps(scale, indent=1) + '\n', encoding='utf-8')
        (out / 'latency-by-context.json').write_text(json.dumps(latency, indent=1) + '\n', encoding='utf-8')
    print(f'{scale["sessions"]} sessions ({scale["main_sessions"]} sessions, {scale["sub_agents"]} sub-agents) in '
          f'{scale["projects"]} projects, {scale["calls"]:,} calls, {scale["tokens_B"]} billion tokens of context, '
          f'{scale["first_day"]} to {scale["last_day"]}')
    print('tokens by kind:', scale['tokens_by_kind_percent'])
    print('cost shares:', scale['cost_shares_percent'], f'${scale["cost_at_list_prices_usd"]:,} at list prices,',
          f'{scale["calls_priced_at_their_own_model_percent"]} % of calls priced at their own model')
    for b in buckets:
        print(f'{b["from_k"]:>4}k  median {b["median_s"]:>5} s  short replies {b.get("short_median_s", "-"):>5} s  '
              f'{top} {b.get("one_model_median_s", "-"):>5} s  n={b["calls"]}')
    return 0
# @end article.analysis.measure


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
