#!/usr/bin/env python3
# @map article.figures.style: the figures' one design, a research report's: white, grey for the sessions as they ran, one blue for the map, type sized for Medium's column
"""Every figure of the article as an HTML page, drawn from the measured data in article/data/. Run it, then
render.mjs turns each page into a PNG at twice its size, and the scene into a GIF:

    python3 article/src/figures.py
    cd article && npm install && node src/render.mjs      (article/README.md has the steps)

One design for all of them: a title that says what is plotted, a subtitle with the sample and what it shows, the
source and the caveats under the plot. Grey is what the sessions did as they ran; blue, the only accent, is the
map. Every number comes from the data files."""
import html
import json
import pathlib
from decimal import ROUND_HALF_UP, Decimal

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE.parent / 'data'
OUT = HERE / 'html'

W, PAD = 860, 32                 # CSS pixels; Medium shows the figure 680 wide, so type is drawn about a quarter larger
PW = W - 2 * PAD
INK, TEXT, MUTE, GRID, AXIS = '#111111', '#333333', '#666666', '#e6e6e6', '#9a9a9a'
DARK, GREY, LIGHT, PALE = '#3a3a3a', '#8c8c8c', '#bdbdbd', '#e8e8e8'
ACC, ACC_L = '#2b62a6', '#c9d8ec'
LINES_K = 40_000                 # the projection's codebase: 40 million lines, in thousands
YEAR_H = 365.25 * 24

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:#fff}
body{font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;color:#333;-webkit-font-smoothing:antialiased;
font-variant-numeric:tabular-nums lining-nums}
.fig{width:860px;background:#fff;padding:30px 32px 22px}
h1{font-size:26px;line-height:1.24;font-weight:700;color:#111;letter-spacing:-.01em;text-wrap:balance}
.sub{font-size:16.5px;line-height:1.46;color:#4a4a4a;margin-top:8px;text-wrap:pretty}
.key{display:flex;flex-wrap:wrap;gap:6px 24px;margin-top:14px;font-size:14.5px;color:#333}
.key span{display:inline-flex;align-items:center;gap:8px}
.key i{display:inline-block;width:13px;height:13px;flex:none}
.plot{margin-top:18px}
.notes{margin-top:16px;padding-top:10px;border-top:1px solid #e6e6e6;font-size:13.5px;line-height:1.45;color:#666}
.notes p{text-wrap:pretty}.notes p+p{margin-top:3px}
svg{display:block;overflow:visible}
svg text{font-family:"Helvetica Neue",Helvetica,Arial,sans-serif}
svg text.m{font-family:"SF Mono",Menlo,Consolas,monospace;white-space:pre}
.mono,pre{font-family:"SF Mono",Menlo,Consolas,monospace}
"""


def esc(s):
    return html.escape(str(s), quote=True)


def load(name):
    return json.loads((DATA / name).read_text(encoding='utf-8'))


def page(name, body, width=W, css='', script=''):
    OUT.mkdir(parents=True, exist_ok=True)
    doc = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>' + esc(name) + '</title><style>'
           + CSS + css + 'body{width:%dpx}' % width + '</style></head><body>' + body + script + '</body></html>')
    (OUT / f'{name}.html').write_text(doc, encoding='utf-8')
    print(f'{name}.html')


def text(x, y, s, size=14.5, fill=TEXT, anchor='start', weight=400, italic=False, halo=False):
    it = ' font-style="italic"' if italic else ''
    ha = ' stroke="#fff" stroke-width="4" stroke-linejoin="round" paint-order="stroke"' if halo else ''
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="{weight}"{it}{ha}>{s}</text>')


def line(x1, y1, x2, y2, stroke=GRID, width=1.0, dash=''):
    d = f' stroke-dasharray="{dash}"' if dash else ''
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{width}"{d}/>'


def rect(x, y, w, h, fill):
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{h:.1f}" fill="{fill}"/>'


def circle(x, y, r, fill, stroke='none', width=0.0):
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>'


def points(pts):
    return ' '.join(f'{x:.1f},{y:.1f}' for x, y in pts)


def polygon(pts, fill):
    return f'<polygon points="{points(pts)}" fill="{fill}"/>'


def polyline(pts, stroke, width=1.5, dash=''):
    d = f' stroke-dasharray="{dash}"' if dash else ''
    return (f'<polyline points="{points(pts)}" fill="none" stroke="{stroke}" stroke-width="{width}" '
            f'stroke-linejoin="round" stroke-linecap="round"{d}/>')


def svg(w, h, parts):
    body = ''.join(parts)
    return f'<svg width="{w:.0f}" height="{h:.0f}" viewBox="0 0 {w:.0f} {h:.0f}" xmlns="http://www.w3.org/2000/svg">{body}</svg>'


def box(color):
    return f'<i style="background:{color}"></i>'


def stroke_key(color, dash='', dot='filled'):
    d = f' stroke-dasharray="{dash}"' if dash else ''
    fill = color if dot == 'filled' else '#fff'
    return (f'<svg width="30" height="12"><line x1="1" y1="6" x2="29" y2="6" stroke="{color}" stroke-width="2"{d}/>'
            f'<circle cx="15" cy="6" r="3.6" fill="{fill}" stroke="{color}" stroke-width="1.6"/></svg>')


def figure(name, title, sub, plot, notes, key=None, width=W):
    k = ''
    if key:
        k = '<div class="key">' + ''.join(f'<span>{sw}{t}</span>' for sw, t in key) + '</div>'
    n = ''.join(f'<p>{x}</p>' for x in notes)
    page(name, f'<div class="fig" id="fig"><h1>{title}</h1><div class="sub">{sub}</div>{k}'
               f'<div class="plot">{plot}</div><div class="notes">{n}</div></div>', width=width)


def num(x, digits=0):
    """x rounded half up, as a reader rounds (2.25 → 2.3, 84.5 → 85), with thousands separators."""
    return f'{Decimal(str(x)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP):,}'


def rng(lo, hi, digits=0):
    a, b = num(lo, digits), num(hi, digits)
    return a if a == b else f'{a}–{b}'


def words(n):
    return ('zero one two three four five six seven eight nine'.split()[n] if 0 <= n < 10 else f'{n:,}')
# @end article.figures.style


# @map article.figures.problem: the problem in two figures: the context one session carried call by call, and the reply slowing as the context grows
def context_svg(pw, ph, labels=True):
    ys = load('context-per-call.json')['ctx_k']
    n = len(ys)
    x0, x1, y0, y1 = 50, pw - 10, 34, ph - (44 if labels else 26)
    step = (x1 - x0) / n
    sx = lambda i: x0 + (i + .5) * step                                       # noqa: E731
    sy = lambda v: y1 - v * (y1 - y0) / 1000                                  # noqa: E731
    parts = []
    for v, lbl in ((0, '0'), (250, '250k'), (500, '500k'), (750, '750k'), (1000, '1M')):
        if v:
            parts.append(line(x0, sy(v), x1, sy(v), '#b0b0b0' if v == 500 else GRID, 1, '4 3' if v == 500 else ''))
        parts.append(text(x0 - 9, sy(v) + 5, lbl, 13.5, MUTE, 'end'))
    if labels:
        parts.append(text(0, 14, 'Tokens of context per call', 13.5, MUTE))
    pts = [(sx(i), sy(v)) for i, v in enumerate(ys)]
    parts.append(polygon([(x0, y1), (x0, pts[0][1])] + pts + [(x1, pts[-1][1]), (x1, y1)], '#dcdcdc'))
    i = 0
    while i < n:                                                               # calls of 500k or more: their whole column darker
        if ys[i] < 500:
            i += 1
            continue
        j = i
        while j + 1 < n and ys[j + 1] >= 500:
            j += 1
        parts.append(polygon([(sx(i) - step / 2, y1), (sx(i) - step / 2, sy(ys[i]))] + pts[i:j + 1]
                             + [(sx(j) + step / 2, sy(ys[j])), (sx(j) + step / 2, y1)], '#8f8f8f'))
        i = j + 1
    parts.append(polyline(pts, DARK, 1.3))
    parts.append(line(x0, y1, x1, y1, AXIS, 1))
    for i in (k for k in range(1, n) if ys[k] < ys[k - 1] * 0.6):              # compactions: the context summarized
        x = (sx(i - 1) + sx(i)) / 2
        parts.append(line(x, 25, x, sy(ys[i - 1]) - 5, '#9a9a9a', 1))
        parts.append(circle(sx(i - 1), sy(ys[i - 1]), 2.6, DARK))
        lbl = f'{ys[i - 1]}k, compacted to {ys[i]}k'
        right = x > x1 - 110
        parts.append(text(x + 4 if right else x, 16, lbl, 13.5, TEXT, 'end' if right else 'middle'))
    if labels:
        for c in (1, 100, 200, 300, 400, 500, 600, 700):
            x = sx(c - 1)
            parts += [line(x, y1, x, y1 + 4, AXIS, 1), text(x, y1 + 19, f'{c:,}', 13.5, MUTE, 'middle')]
        parts.append(text((x0 + x1) / 2, y1 + 39, 'Model call, in order', 13.5, MUTE, 'middle'))
    return svg(pw, ph, parts)


def fig_context():
    d = load('context-per-call.json')
    ys = d['ctx_k']
    total = sum(ys)
    big = round(sum(y for y in ys if y >= 500) * 100 / total)
    figure('01-context-per-call', 'Context sent to the model at each call of one coding session',
           f'Every call re-sends the conversation so far, so the session read the whole shaded area: '
           f'{d["total_M"]:.0f} million tokens in {len(ys)} calls.', context_svg(PW, 330),
           ['Source: the session\'s transcript, October 12, 2026. Context per call: its input, cache-read and cache-write tokens.',
            'The two drops are compactions: the conversation is summarized to free room, then grows again.'],
           key=[(box('#8f8f8f'), f'Calls carrying 500k tokens or more: {big}% of the tokens read'),
                (box('#dcdcdc'), f'Calls carrying under 500k: {100 - big}%')])


def fig_latency():
    d = load('latency-by-context.json')
    bs = d['buckets']
    ph = 340
    x0, x1, y0, y1 = 46, PW - 132, 26, ph - 52
    slot = (x1 - x0) / len(bs)
    cx = lambda i: x0 + (i + .5) * slot                                       # noqa: E731
    sy = lambda v: y1 - v * (y1 - y0) / 18                                    # noqa: E731
    parts = [text(0, 12, 'Seconds to reply', 13.5, MUTE)]
    for v in (0, 5, 10, 15):
        if v:
            parts.append(line(x0, sy(v), x1, sy(v), GRID, 1))
        parts.append(text(x0 - 9, sy(v) + 5, str(v), 13.5, MUTE, 'end'))
    band = [(cx(i), sy(b['p75_s'])) for i, b in enumerate(bs)] + [(cx(i), sy(b['p25_s'])) for i, b in reversed(list(enumerate(bs)))]
    parts.append(polygon(band, PALE))
    allp = [(cx(i), sy(b['median_s'])) for i, b in enumerate(bs)]
    short = [(cx(i), sy(b['short_median_s'])) for i, b in enumerate(bs)]
    parts.append(polyline(short, DARK, 1.6, '5 4'))
    parts.append(polyline(allp, DARK, 2.2))
    parts += [circle(x, y, 3.4, '#fff', DARK, 1.6) for x, y in short]
    parts += [circle(x, y, 3.6, DARK, '#fff', 1.2) for x, y in allp]
    peak = max(range(len(bs)), key=lambda i: bs[i]['median_s'])
    for i, key, dy in ((0, 'median_s', -11), (peak, 'median_s', -11), (0, 'short_median_s', 21), (peak, 'short_median_s', 21)):
        y = sy(bs[i][key]) + dy
        parts.append(text(cx(i), y, f'{bs[i][key]:.2f}', 13.5, INK, 'middle', 700, halo=True))
    for i in range(len(bs) + 1):
        x = x0 + i * slot
        parts += [line(x, y1, x, y1 + 4, AXIS, 1), text(x, y1 + 19, '1M' if i == 10 else (f'{i * 100}k' if i else '0'), 13.5, MUTE, 'middle')]
    parts.append(line(x0, y1, x1, y1, AXIS, 1))
    parts.append(text((x0 + x1) / 2, y1 + 40, 'Tokens of context the call carried', 13.5, MUTE, 'middle'))
    lx = cx(len(bs) - 1) + 14
    parts.append(text(lx, allp[-1][1] - 2, 'All calls', 14, INK, 'start', 700))
    parts.append(text(lx, allp[-1][1] + 15, 'median', 13, MUTE))
    parts.append(text(lx, short[-1][1] + 4, 'Short replies', 14, INK, 'start', 700))
    parts.append(text(lx, short[-1][1] + 21, f'under {d["short_reply_tokens"]} tokens', 13, MUTE))
    calls = sum(b['calls'] for b in bs)
    pct_one = sum(b['one_model_calls'] for b in bs) * 100 / calls
    s0, s1 = bs[0]['short_median_s'], max(b['short_median_s'] for b in bs[6:])
    figure('02-response-time', 'How long the model takes to reply, by the size of the context',
           f'Median seconds from a tool\'s result to the model\'s reply, {calls:,} calls in {d["sessions"]} sessions. Replies also '
           f'grow longer as a session goes on; among short replies alone the median still rises, from {s0:.2f} to about {s1:.0f} seconds.',
           svg(PW, ph, parts),
           [f'Source: transcripts of {d["sessions"]} Claude Code sessions (36 sessions and the 77 sub-agents they started) in '
            f'{words(d["projects"])} projects, September 21 to October 12, 2026. Calls under 0.3 s or over 300 s are left out.',
            f'{pct_one:.0f}% of these calls went to one model, Claude Opus 5.5; its curve alone stays within 0.3 seconds of this one.'],
           key=[(stroke_key(DARK), 'Median, all calls'), (stroke_key(DARK, '5 4', 'hollow'), f'Median, replies under {d["short_reply_tokens"]} tokens'),
                (box(PALE), 'Middle half of all calls (25th to 75th percentile)')])
# @end article.figures.problem


# @map article.figures.composition: what filled the context of 23 agents: a bar per kind of tool result, code lookups dark, the map blue
def fig_composition():
    d = {it['what']: it['percent'] for it in load('where-context-went.json')['items']}
    rows = [('Output of grep, cat and sed', d['grep, sed and cat output'], DARK),
            ('Whole files read', d['whole files read'], DARK),
            ('Build output', d['build output'], LIGHT),
            ("The agents' own edits", d['their own edits'], LIGHT),
            ('Answers from the map, an early version', d['map'], ACC),
            ('Test output', d['tests'], LIGHT),
            ('Screenshots', d['screenshots'], LIGHT)]
    rows.append(('Other', 100 - sum(p for _, p, _ in rows), LIGHT))
    lw, k, rh, bh = 270, 8.6, 33, 19
    parts = []
    for i, (lbl, p, c) in enumerate(rows):
        y = 6 + i * rh
        parts.append(text(lw - 12, y + bh / 2 + 5, esc(lbl), 14.5, TEXT, 'end'))
        parts.append(rect(lw, y, p * k, bh, c))
        parts.append(text(lw + p * k + 7, y + bh / 2 + 5, f'{p}%', 14, INK, 'start', 700))
    h = 6 + len(rows) * rh
    parts.append(line(lw, 0, lw, h - rh + bh + 6, AXIS, 1))
    bx = lw + rows[0][1] * k + 62
    top, bot = 6, 6 + rh + bh
    parts.append(f'<path d="M{bx},{top} h7 V{bot} h-7" fill="none" stroke="{DARK}" stroke-width="1.3"/>')
    parts.append(text(bx + 16, (top + bot) / 2 - 3, 'Looking up code', 14.5, INK, 'start', 700))
    parts.append(text(bx + 16, (top + bot) / 2 + 15, f'the usual way: {rows[0][1] + rows[1][1]}%', 14.5, TEXT))
    figure('03-what-filled-the-context', 'What filled the context while 23 sub-agents built one feature',
           'Share of the 1.18 billion tokens the sub-agents re-read, by the kind of tool result that brought each piece of text '
           'into the context, weighted by how many later calls re-read it.', svg(PW, h, parts),
           ['Source: the 23 sub-agents\' transcripts, October 4, 2026. That day the map was an early version and nothing made '
            'the agents use it.'])
# @end article.figures.composition


# @map article.figures.overview: how the map works at a glance: the code's tags built into a map, the agent asking it, the hook refusing grep
def fig_overview():
    bw, lane = 540, 590
    boxes = [(0, 112, 'The code', ["# @map shop.cart.totals: the totals: each line's amount and…", 'def total(cart): …',
                                   '# @end shop.cart.totals']),
             (172, 284, 'The map', ['map.yaml       the areas, and what each needs from the others',
                                    'map/shop.yaml  shop.cart: what it is for, its parts, files,',
                                    '               imports, the tests that reach it, the docs']),
             (344, 436, 'The agent', ['$ tools/map brief cart coupon', '$ tools/map ask shop.cart.totals total coupon'])]
    parts = [f'<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
             f'<path d="M0,0 L10,5 L0,10 z" fill="{DARK}"/></marker><marker id="ag" viewBox="0 0 10 10" refX="9" refY="5" '
             f'markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{GREY}"/></marker></defs>']
    for y0, y1, title, lines in boxes:
        parts.append(f'<rect x=".5" y="{y0 + .5}" width="{bw - 1}" height="{y1 - y0 - 1}" fill="#fafafa" stroke="#b8b8b8" stroke-width="1"/>')
        parts.append(text(14, y0 + 25, title, 15, INK, 'start', 700))
        parts += [f'<text class="m" x="14" y="{y0 + 52 + k * 19}" font-size="13" fill="{TEXT}">{esc(ln)}</text>' for k, ln in enumerate(lines)]
    for (a, b), lbl, sub in (((112, 172), 'build', 'reads the tags and the code; CI checks the map is current'),
                             ((284, 344), 'brief, ask', 'a round of questions per call, each answered whole')):
        parts.append(f'<line x1="110" y1="{a + 6}" x2="110" y2="{b - 6}" stroke="{DARK}" stroke-width="1.4" marker-end="url(#ah)"/>')
        parts.append(text(126, (a + b) / 2 + 5, f'<tspan font-weight="700" fill="{INK}">{lbl}</tspan>  {sub}', 13.5, TEXT))
    parts.append(f'<path d="M{bw + 6},390 H{lane} V56 H{bw + 8}" fill="none" stroke="{GREY}" stroke-width="1.4" '
                 f'stroke-dasharray="5 4" marker-end="url(#ag)"/>')
    parts.append(rect(lane - 16, 225, 32, 6, INK))
    parts += [text(lane + 16, 383, 'grep, cat and sed', 13.5, TEXT), text(lane + 16, 400, 'on the code', 13.5, TEXT)]
    parts += [text(lane + 26, 218 + k * 17, t, 13.5, INK, 'start', 700 if k == 0 else 400)
              for k, t in enumerate(('The hook refuses it', 'and names the ask', 'that answers instead'))]
    figure('04-how-it-works', 'How the map works',
           'Tags in the code are built into a map. The agent asks the map, a round of questions per call, and gets each answer '
           'whole; a hook stops the old way of reading.', svg(PW, 440, parts),
           ['The tool runs inside the repository: no server and no index to host. The hook works with Claude Code, Codex, Cursor, '
            'GitHub Copilot and Gemini CLI.'])
# @end article.figures.overview


# @map article.figures.method: the method in four parts, each with its real example from the repository's example project
METHOD_CSS = """
.step+.step{margin-top:20px}
.head{font-size:15.5px;line-height:1.46;color:#333}
.head b{color:#111}
pre{margin-top:8px;background:#f7f7f7;border:1px solid #e3e3e3;border-radius:3px;padding:10px 12px;font-size:13px;line-height:1.55;
color:#1d1d1d;white-space:pre;overflow:hidden}
pre .c{color:#6b6b6b}pre b{color:#111;font-weight:700}pre .who{color:#8a8a8a}pre .deny{color:#111;font-weight:700}
pre .ask{color:#2b62a6;font-weight:700}
"""


def fig_method():
    tag = ('<span class="c"># @map <b>shop.cart.totals</b>: the totals: each line\'s amount and discount, the coupon on the rest, …</span>\n'
           'def line_total(code, quantity):\n'
           '    return price(code) * quantity - line_discount(code, quantity)\n\n'
           'def total(cart):\n'
           '    subtotal = sum(line_total(code, q) for code, q in cart.lines.items())\n'
           '    return subtotal - subtotal * coupon_percent(cart.coupon) // 100\n'
           '<span class="c"># @end <b>shop.cart.totals</b></span>')
    built = ('<span class="c"># map/shop.yaml, written by tools/map build: never edited by hand</span>\n'
             '<b>shop.cart</b>: {what: "the cart: its lines, adding and removing articles, and what it holds",\n'
             '  parts: [model, totals], files: ["src/shop/cart.py"],\n'
             '  declares: [Cart, __init__, add, remove, is_empty, line_total, total, summary],\n'
             '  needs: [shop.prices], needed_by: [tests.cart], tests: {tests: 1},\n'
             '  docs: [README.md, docs/CART.md]}')
    ask = ('<span class="c">$</span> tools/map brief cart coupon\n'
           '<b>shop.cart</b>  the cart: its lines, adding and removing articles, and what…  [src/shop/cart.py]\n'
           '  parts: shop.cart.totals src/shop/cart.py:24-38 — the totals: each line\'s amount…\n'
           '  needs (imports): shop.prices; needed by: tests.cart\n'
           '  tests (1): tests/test_cart.py\n'
           '<span class="c">$</span> tools/map ask shop.cart.totals total coupon\n'
           '<b>== shop.cart.totals</b>\n'
           '  src/shop/cart.py:24-38  shop.cart.totals: the totals: each line\'s amount and discount, …\n'
           '<b>== total</b>\n'
           '  function total: src/shop/cart.py:29-32  in shop.cart.totals\n'
           '  named on 19 other lines\n'
           '<b>== coupon</b>\n'
           '  on 21 lines')
    hook = ('<span class="who">agent</span>  $ grep -rn "coupon" src\n'
            '<span class="who">hook </span>  <span class="deny">Refused.</span> This repository\'s code and docs are read and located through its\n'
            '       map, every question of a round in one call. None of this command ran. Run instead:\n'
            '         <span class="ask">tools/map ask coupon --in src</span>')
    steps = [('a. Tag the code.', 'A comment above each block says, in the words a task would use, what the block is for. '
              'A check fails when a file has no tags.', tag),
             ('b. Build the map.', 'The tool reads the tags and the code and writes the map: areas, then components with their '
              'files, what they declare and import, the tests that reach them and the docs that name them. Nobody edits it; '
              'a check fails when it is out of date.', built),
             ('c. Ask in rounds.', '<span class="mono">brief</span> starts a task from its words. <span class="mono">ask</span> then '
              'answers every question of a round in one call, each one whole: a block\'s code, where a name is declared and used, '
              'a file\'s outline, a section of a document.', ask),
             ('d. Refuse the old habit.', 'A hook runs before each of the agent\'s tool calls. It refuses grep, cat and sed on the '
              'code and names the ask that answers the same question. Claude Code, Codex, Cursor, GitHub Copilot and Gemini CLI '
              'all run such hooks.', hook)]
    body = ''.join(f'<div class="step"><div class="head"><b>{t}</b> {d}</div><pre>{ex}</pre></div>' for t, d, ex in steps)
    page('05-method-on-an-example', f'<div class="fig" id="fig"><h1>The four parts on an example</h1><div class="sub">Shown on the example '
                      'project in the repository: a small shop in three areas, shop, web and tests.</div>'
                      f'<div class="plot">{body}</div><div class="notes"><p>Commands as the compiled version installs them '
                      '(tools/map). Long lines are cut where marked …, and the code inside each answer is left out. "Refused." stands for '
                      'the agent\'s notice that the hook denied the call; the message after it is the hook\'s own.</p></div></div>',
         css=METHOD_CSS)
# @end article.figures.method


# @map article.figures.lookups: six lookups, the text grep and the declaring file return against what one ask returns
def fig_lookups():
    qs = sorted(load('grep-vs-ask.json')['questions'], key=lambda q: -q['grep_cat_kb'])
    lw, bh, gap, rh = 150, 13, 3, 44
    x0, x1 = lw, PW - 78
    sx = lambda kb: x0 + kb * (x1 - x0) / 300                                # noqa: E731
    top = 4
    h = top + len(qs) * rh + 40
    parts = []
    for t in (0, 100, 200, 300):
        parts.append(line(sx(t), 0, sx(t), top + len(qs) * rh - 8, GRID if t else AXIS, 1))
        parts.append(text(sx(t), top + len(qs) * rh + 10, f'{t} KB', 13.5, MUTE, 'middle'))
    for i, q in enumerate(qs):
        y = top + i * rh
        parts.append(text(lw - 12, y + bh + 5, esc(q['question'][0].upper() + q['question'][1:]), 14.5, TEXT, 'end'))
        parts.append(rect(x0, y, sx(q['grep_cat_kb']) - x0, bh, GREY))
        parts.append(text(sx(q['grep_cat_kb']) + 7, y + bh - 2, f'{q["grep_cat_kb"]:.1f} KB', 13.5, INK, halo=True))
        parts.append(rect(x0, y + bh + gap, max(sx(q['ask_kb']) - x0, 1.5), bh, ACC))
        parts.append(text(sx(q['ask_kb']) + 7, y + 2 * bh + gap - 2, f'{q["ask_kb"]:.1f} KB', 13.5, ACC, 'start', 700, halo=True))
    parts.append(text((x0 + x1) / 2, top + len(qs) * rh + 30, 'Kilobytes returned to the agent', 13.5, MUTE, 'middle'))
    figure('07-one-lookup', 'Text the agent receives to locate one function',
           'Six lookups in a 403-file codebase. The ask returns the block that declares the function and every line that names '
           'it; searching takes grep and then a read of the file that declares it.', svg(PW, h, parts),
           ['Source: measured October 16, 2026: grep -rn &lt;name&gt; plus the whole declaring file, against one ask.',
            'Agents often read part of a file instead. Replaying 470 such reads through the map, the asks returned 36% more text '
            'than the reads they replaced: the saving comes from fewer calls, not shorter answers.'],
           key=[(box(GREY), 'grep, then the file that declares the function'), (box(ACC), 'One ask to the map')])
# @end article.figures.lookups


# @map article.figures.hook: each session's share of code reads through the map, with the instructions only and with the hook
def fig_hook():
    d = load('sessions.json')
    rows = [r for r in d['rows'] if r['search_read'] >= 20]
    before = sorted(r['via_map'] * 100 / r['search_read'] for r in rows if r['day'] < d['guard_from'])
    after = sorted(r['via_map'] * 100 / r['search_read'] for r in rows if r['day'] >= d['guard_from'])
    med = lambda v: v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2      # noqa: E731
    lw = 214
    x0, x1 = lw, PW - 14
    sx = lambda p: x0 + p * (x1 - x0) / 100                                   # noqa: E731
    base = 196
    parts = []
    for p in range(0, 101, 20):
        parts.append(line(sx(p), 6, sx(p), base, GRID if p else AXIS, 1))
        parts.append(text(sx(p), base + 19, f'{p}%', 13.5, MUTE, 'middle'))
    parts.append(text((x0 + x1) / 2, base + 41, 'Share of the session\'s code reads made through the map', 13.5, MUTE, 'middle'))
    for cy, vals, color, title, note in ((62, before, GREY, 'Instructions only', f'{len(before)} sessions'),
                                         (150, after, ACC, 'Instructions and hook', f'{len(after)} sessions')):
        parts.append(text(0, cy - 2, title, 15, INK, 'start', 700))
        parts.append(text(0, cy + 17, note, 13.5, MUTE))
        placed = []
        for v in vals:
            for dy in (0, -14, 14, -28, 28):
                if not any(abs(sx(v) - sx(pv)) < 13.5 and abs(dy - pdy) < 13.5 for pv, pdy in placed):
                    break
            placed.append((v, dy))
            parts.append(circle(sx(v), cy + dy, 6.3, color, '#fff', 1.2))
        m = med(vals)
        parts.append(line(sx(m), cy - 34, sx(m), cy + 34, INK, 2))
        parts.append(text(sx(m), cy - 40, f'median {num(m)}%', 13.5, INK, 'middle', 700, halo=True))
    figure('08-instructions-and-hook', 'Share of code reads that went through the map, per session',
           'Each dot is a session of one project with 20 or more code reads. In all of them the instructions asked the agent to '
           'use the map; from October 12 a hook also refused grep, cat and sed on the code.', svg(PW, base + 52, parts),
           ['Source: the sessions\' transcripts, each read classified by the tool that made it.',
            'The sessions before and after the hook did different tasks: this is an observation, not a controlled experiment.'])
# @end article.figures.hook


# @map article.figures.estimates: the replayed session and the projection, both as rows of bars with ranges in two panels, tokens and time
def range_panels(rows, panels, lw=256):
    gap, rh, bh, top = 28, 44, 18, 30
    each = (PW - lw - gap * (len(panels) - 1)) / len(panels)
    h = top + rh * len(rows) + 30
    parts = []
    for i, (lbl, _, _) in enumerate(rows):
        parts.append(text(0, top + i * rh + rh / 2 + 5, lbl, 14.5, TEXT))
    for p, (title, vmax, ticks, fmt) in enumerate(panels):
        px0 = lw + p * (each + gap)
        px1 = px0 + each - 72
        sx = lambda v, a=px0, b=px1, m=vmax: a + v * (b - a) / m                # noqa: E731
        parts.append(text(px0, 14, title, 14, INK, 'start', 700))
        for t in ticks:
            parts.append(line(sx(t), top - 6, sx(t), top + rh * len(rows), GRID if t else AXIS, 1))
            parts.append(text(sx(t), top + rh * len(rows) + 18, fmt(t), 13, MUTE, 'middle'))
        for i, (_, color, vals) in enumerate(rows):
            lo, hi = vals[p]
            cy = top + i * rh + rh / 2
            parts.append(rect(sx(0), cy - bh / 2, sx((lo + hi) / 2) - sx(0), bh, color))
            if hi - lo > 1e-9:
                parts += [line(sx(lo), cy, sx(hi), cy, INK, 1.4), line(sx(lo), cy - 6, sx(lo), cy + 6, INK, 1.4),
                          line(sx(hi), cy - 6, sx(hi), cy + 6, INK, 1.4)]
            parts.append(text(sx(hi) + 8, cy + 5, fmt(lo, hi), 14, INK, 'start', 700, halo=True))
    return svg(PW, h, parts)


STEPS = ['Test only what each change reaches', '… and questions asked in rounds', '… and one session per change']


def fig_replay():
    d = load('replay.json')
    b = d['baseline']
    tok, mins = b['tokens_M'], b['model_min'] + b['tool_min']
    rows = [('As the session ran', GREY, [(tok, tok), (mins, mins)])]
    for s, nm in zip(d['steps'], STEPS):
        rows.append((nm, ACC, [tuple(sorted(tok * (1 + x / 100) for x in s['tokens'])),
                               tuple(sorted(mins * (1 + x / 100) for x in s['time']))]))
    fmt = lambda lo, hi=None: num(lo) if hi is None else rng(lo, hi)                          # noqa: E731
    panels = [('Tokens read, millions', 270, (0, 100, 200), fmt), ('Work time, minutes', 250, (0, 100, 200), fmt)]
    figure('09-replayed-session', 'One session replayed with each practice added',
           f'The session of Figure 1, replayed call by call up to its {b["calls"]}nd call; each row adds one practice to the row above. '
           'Where the estimate is a range, the bar ends at its middle and the whisker spans it.', range_panels(rows, panels),
           ['Source: the session\'s transcript. Each call\'s context recomputed with the practice applied, and its time scaled by '
            'the new context. The ranges assume that half, or two thirds, of the reads join a round.',
            f'Work time is the model\'s time plus the tools\': {b["model_min"]} and {b["tool_min"]} minutes as the session ran. '
            'Starting the extra sessions is not counted (about 1% of the tokens). Method: docs/EVIDENCE.md.'])


def fig_projection():
    rates = load('rates.json')['per_1000_lines']
    d = load('replay.json')
    tok = LINES_K * rates['tokens_M'] / 1e6                                   # trillions
    months = LINES_K * rates['work_min'] / 60 / (YEAR_H / 12)
    rows = [('As the sessions ran', GREY, [(tok, tok), (months, months)])]
    for s, nm in zip(d['steps'], STEPS):
        rows.append((nm, ACC, [tuple(sorted(tok * (1 + x / 100) for x in s['tokens'])),
                               tuple(sorted(months * (1 + x / 100) for x in s['time']))]))
    fmt_t = lambda lo, hi=None: num(lo) if hi is None else rng(lo, hi, 1)                    # noqa: E731
    fmt_m = lambda lo, hi=None: num(lo) if hi is None else rng(lo, hi)                       # noqa: E731
    panels = [('Tokens read, trillions', 2.5, (0, 1, 2), fmt_t), ('Work time, months of one agent', 32, (0, 10, 20, 30), fmt_m)]
    figure('10-projection', 'A projection: writing 40 million lines of code with an agent',
           f'The rates measured over 25 sessions of one project, {num(rates["tokens_M"])} million tokens and '
           f'{num(rates["work_min"])} minutes of work per 1,000 lines written, applied to 40 million lines and reduced step by '
           'step as in the replay.', range_panels(rows, panels),
           ['An extrapolation, not a measurement. Lines written include rewrites, so a codebase that keeps 40 million lines would '
            'take more. Work time is one agent working without pause: agents in parallel divide the time, not the tokens.',
            '40 million lines is a round figure of the order of Chromium\'s size, not a count of it.'])
# @end article.figures.estimates


# @map article.figures.languages: the run time of the four implementations: building the map, a brief, the hook per tool call
def fig_languages():
    d = load('languages.json')
    names = {'python': 'Python', 'node': 'Node', 'go': 'Go', 'rust': 'Rust'}
    impls = [(names[k], v) for k, v in d['implementations'].items() if 'skipped' not in v]
    panels = [('build_warm', 'Build the map, parse cached'), ('brief', 'Start a task: brief'), ('guard', 'The hook, per tool call')]
    gap = 26
    each = (PW - gap * 2) / 3
    lw, rh, bh, top = 58, 32, 18, 30
    base = top + rh * len(impls) - 6
    h = base + 30
    vmax = 0.32                                                               # one scale for the three panels, in seconds
    span = each - lw - 64
    parts = []
    for p, (key, title) in enumerate(panels):
        px = p * (each + gap)
        sx = lambda v, a=px + lw: a + v / vmax * span                         # noqa: E731
        parts.append(text(px, 14, title, 14.5, INK, 'start', 700))
        for t in (0, 0.1, 0.2, 0.3):
            parts.append(line(sx(t), top - 4, sx(t), base, GRID if t else AXIS, 1))
            parts.append(text(sx(t), base + 17, f'{t * 1000:.0f}' + (' ms' if t == 0.3 else ''), 12.5, MUTE, 'middle'))
        for i, (nm, v) in enumerate(impls):
            y = top + i * rh
            ms = v[key] * 1000
            parts.append(text(px + lw - 9, y + bh / 2 + 5, nm, 14, TEXT, 'end'))
            parts.append(rect(sx(0), y, max(sx(v[key]) - sx(0), 1.5), bh, GREY))
            parts.append(text(max(sx(v[key]), sx(0) + 1.5) + 7, y + bh / 2 + 5,
                              f'{num(ms)} ms' if ms >= 10 else f'{num(ms, 1)} ms', 14, INK, 'start', 700, halo=True))
    c = d['corpus']
    figure('12-four-implementations', 'Run time of the tool\'s four implementations',
           f'Median of {words(d["repeat"])} runs on a generated codebase of {c["files"]} files and {c["blocks"]:,} tagged blocks, '
           'on a laptop, on one scale for the three tasks. All four write the same map, byte for byte, and give the same answers '
           'in a 46-case conformance suite.', svg(PW, h, parts),
           ['Source: bench/run.py on the codebase bench/corpus.py writes, October 2026. A first build, with nothing cached, takes '
            f'{num(min(v["build_cold"] for _, v in impls) * 1000)} to {num(max(v["build_cold"] for _, v in impls) * 1000)} ms.',
            'The hook runs before every tool call the agent makes, so its time is paid on each one.'])
# @end article.figures.languages


# @map article.figures.related: related tools as a table with rules above and below, each row as the tool's own pages describe it
TABLE_CSS = """
table{width:100%;border-collapse:collapse;font-size:13px;line-height:1.36}
th{font-weight:700;color:#111;text-align:left;padding:7px 8px 6px;border-top:1.6px solid #111;border-bottom:1px solid #111;vertical-align:bottom}
td{padding:7px 8px;border-bottom:1px solid #e6e6e6;vertical-align:top;color:#333}
tr:last-child td{border-bottom:1.6px solid #111}
td:first-child{width:178px}td b{color:#111}td small{display:block;color:#666;font-size:12.5px;margin-top:1px}
sup{font-size:12px;line-height:0}
"""


def fig_related():
    rows = [('Aider repo map', 'files with their key symbols, ranked', 'A parser (tree-sitter)', 'Sent with every request',
             'Partly: to rank the files', 'No', 'No'),
            ('Repomix', 'the repository packed into one file', 'The code itself', 'In the prompt, or an MCP server',
             'Not stated', 'No', 'Token counts of the pack'),
            ('Serena', 'symbol tools over language servers', 'Language servers', 'MCP tool calls', 'Yes', 'No', 'No'),
            ('Cursor', 'search over a local index', 'An index of the code', 'The agent\'s search tools', 'Not stated',
             'No<sup>1</sup>', 'No'),
            ('GitHub Copilot', 'a semantic code search index', 'An index of the code', 'Copilot Chat\'s repository context',
             'Not stated', 'No', 'No'),
            ('CLAUDE.md, AGENTS.md', 'an instructions file', 'People', 'Loaded into every session', 'No', 'No<sup>2</sup>', 'No'),
            ('codemap', 'tree, dependency graph and hubs', 'A parser (ast-grep)', 'Hooks at session start; MCP',
             'Partly: a dependency graph', 'Not stated', 'No'),
            ('agentmap, raymondchins', 'import graph and ranked symbols, TypeScript and JavaScript', 'A compiler (ts-morph)',
             'MCP tools and a command line', 'Yes, in TypeScript and JavaScript', 'Partly<sup>3</sup>', 'A benchmark<sup>4</sup>'),
            ('agentmap, remorses', 'a YAML inventory of the codebase', 'People, in header comments or docstrings',
             'Prepended at session start', 'Not stated', 'Not stated', 'Not stated'),
            ('The map in this article', 'the purpose of every block, with imports, tests and docs',
             'People or agents; CI checks the tags exist', 'Asked on demand, a round of questions per call', 'No: imports only',
             'Yes, a hook for five agent tools', 'Partly: reads measured, tokens estimated by replay')]
    head = ('<tr><th>Tool</th><th>Where its content comes from</th><th>How the agent gets it</th><th>Calls and references '
            'between symbols</th><th>Stops grep, cat and sed on the code</th><th>Measures its effect on tokens</th></tr>')
    body = ''.join(f'<tr><td><b>{a}</b><small>{b}</small></td><td>{c}</td><td>{d}</td><td>{e}</td><td>{f}</td><td>{g}</td></tr>'
                   for a, b, c, d, e, f, g in rows)
    page('11-related-tools', '<div class="fig" id="fig"><h1>How related tools give a coding agent a view of the code</h1>'
         '<div class="sub">Each tool as its own pages describe it, October 2026. Several can be combined: a language-server tool '
         'such as Serena sees calls and references that tags do not.</div>'
         f'<div class="plot"><table>{head}{body}</table></div><div class="notes">'
         '<p>Not stated: the tool\'s pages do not say. <sup>1</sup> Cursor keeps ignored files from the agent, a different aim. '
         '<sup>2</sup> Claude Code\'s documentation calls such files "context, not enforced configuration" and points to a hook '
         'to block an action. <sup>3</sup> Refuses only "high-confidence structural greps", in Cursor and Codex; in Claude Code '
         'its hook never refuses. <sup>4</sup> Seven tasks on one repository, with tokens estimated as characters ÷ 4.</p>'
         '<p>Sources: aider.chat, github.com/yamadashy/repomix, github.com/oraios/serena, cursor.com/docs, docs.github.com, '
         'code.claude.com/docs, agents.md, github.com/JordanCoin/codemap, github.com/raymondchins/agentmap, '
         'github.com/remorses/agentmap; passages quoted in docs/COMPARISON.md.</p></div></div>', css=TABLE_CSS)
# @end article.figures.related


# @map article.figures.scene: the animated transcript for the GIF: the agent tries grep, the hook refuses it, one ask answers by block
def scene():
    out = [('shop.cart.model', 'src/shop/cart.py:1-21', 'the cart: its lines, …', '10'),
           ('shop.cart.totals', 'src/shop/cart.py:24-38', 'the totals: each line…', '24, 30, 32'),
           ('shop.prices.discounts', 'src/shop/prices.py:16-30', 'the discount rules: a…', '16, 18, 28, 29'),
           ('web.cart.styles', 'src/web/cart.css:1-5', 'the cart table and its…', '1, 4'),
           ('web.cart.render', 'src/web/cart.js:1-14', 'the cart drawn on the…', '1, 12'),
           ('web.cart.events', 'src/web/cart.js:16-20', 'what the page does on…', '16, 18'),
           ('web.cart.markup', 'src/web/index.html:9-15', 'the cart\'s table, its…', '9, 14')]
    rows = [f'          <b>{a:<22}</b> {b:<25} <span class="p">{c:<24}</span> {d}' for a, b, c, d in out]
    lines_ = [('task', '<span class="c">Where is the coupon applied?</span>', 0.0),
              ('agent', '$ grep -rn "coupon" src', 0.0),
              ('hook', '<span class="deny">Refused.</span> This repository\'s code and docs are read and located through', 0.0),
              ('', 'its map, every question of a round in one call. None of this command ran.', 0.0),
              ('', 'Run instead: <span class="ask">tools/map ask coupon --in src</span>', 0.0),
              ('agent', '$ tools/map ask coupon --in src', 2.4),
              ('result', '<b>== coupon</b>', 3.2), ('', '  on 16 lines', 3.2)]
    lines_ += [('', r[6:], 3.4 + 0.12 * k) for k, r in enumerate(rows)]
    js = json.dumps([[w, s, t] for w, s, t in lines_])
    script = ('<script>const L=' + js + ';const END=11;\n'
              'window.scene={duration:END,render(t){let n=0,h="";for(const [w,s,a] of L){if(t+1e-6<a)break;n++;'
              'h+=`<div class="ln"><span class="who">${w}</span><span class="tx">${s}</span></div>`;'
              'if(w==="agent"||w==="task")h+="";}document.getElementById("screen").innerHTML=h;return String(n);}};'
              'window.scene.render(0);</script>')
    css = """
.scene{width:860px;background:#fff;padding:22px 24px}
.frame{border:1px solid #d6d6d6;border-radius:6px;background:#fcfcfc;min-height:372px}
.bar{padding:9px 14px;border-bottom:1px solid #e3e3e3;font-size:13px;color:#666;background:#f5f5f5;border-radius:6px 6px 0 0}
#screen{padding:12px 14px 14px;font-family:"SF Mono",Menlo,Consolas,monospace;font-size:13px;line-height:1.62;color:#1d1d1d}
.ln{display:flex;white-space:pre}.who{width:60px;flex:none;color:#8a8a8a}.tx{white-space:pre}
.c{color:#555;font-style:italic}.deny{color:#111;font-weight:700}.ask{color:#2b62a6;font-weight:700}.p{color:#6b6b6b}b{font-weight:700;color:#111}
"""
    page('06-hook-and-ask.scene', '<div class="scene" id="fig"><div class="frame"><div class="bar">An agent session on the example '
         'project, with the hook installed</div><div id="screen"></div></div></div>', width=860, css=css, script=script)
# @end article.figures.scene


# @map article.figures.cards: the preview images: links to the site (Open Graph), the repository on GitHub, and the dev.to cover
def cards():
    chart = context_svg(560, 300, labels=False)
    og = ('<div id="fig" style="width:1200px;height:630px;background:#fff;padding:54px 60px 46px;display:grid;'
          'grid-template-columns:470px 1fr;gap:44px;align-items:center">'
          '<div><div style="font-size:42px;line-height:1.16;font-weight:700;color:#111;letter-spacing:-.015em">A coding agent '
          're-reads its whole conversation on every call</div><div style="font-size:21px;line-height:1.45;color:#4a4a4a;'
          'margin-top:18px">Where the tokens of 113 sessions went, what they cost, and a first test of a code map read in rounds.'
          '</div><div style="font-size:16px;color:#666;margin-top:26px">Measurements, data and code: github.com/mars1571/grepless'
          f'</div></div><div>{chart}<div style="font-size:14px;color:#666;margin-top:6px">Tokens of context sent at each call of '
          'one 716-call session; darker: calls of 500k tokens or more.</div></div></div>')
    page('og-image', og, width=1200)
    gh = ('<div id="fig" style="width:1280px;height:640px;background:#fff;padding:64px 70px;display:grid;'
          'grid-template-columns:520px 1fr;gap:48px;align-items:center">'
          '<div><div style="font-size:64px;font-weight:700;color:#111;letter-spacing:-.02em">grepless</div>'
          '<div style="font-size:26px;line-height:1.4;color:#333;margin-top:14px">A code map and a pre-tool hook, so that AI coding '
          'agents read a codebase in rounds instead of with grep.</div><div style="font-size:19px;color:#666;margin-top:26px">'
          'Claude Code, Codex, Cursor, Copilot, Gemini CLI · Python, Node, Go, Rust · MIT</div></div>'
          f'<div>{context_svg(600, 320, labels=False)}<div style="font-size:15px;color:#666;margin-top:6px">Context sent at each '
          'call of one coding session; darker: calls of 500k tokens or more.</div></div></div>')
    page('social-preview', gh, width=1280)
    dev = ('<div id="fig" style="width:1000px;height:420px;background:#fff;padding:40px 44px;display:grid;'
           'grid-template-columns:400px 1fr;gap:32px;align-items:center">'
           '<div style="font-size:31px;line-height:1.18;font-weight:700;color:#111;letter-spacing:-.01em">Almost every token my '
           'coding agent used was a re-read</div>'
           f'<div>{context_svg(500, 280, labels=False)}</div></div>')
    page('devto-cover', dev, width=1000)
# @end article.figures.cards


# @map article.figures.main: every figure written to article/src/html/
if __name__ == '__main__':
    fig_context()
    fig_latency()
    fig_composition()
    fig_overview()
    fig_method()
    fig_lookups()
    fig_hook()
    fig_replay()
    fig_projection()
    fig_languages()
    fig_related()
    scene()
    cards()
# @end article.figures.main
