#!/usr/bin/env python3
# @map bench.run: the four implementations timed on the synthetic corpus, command by command, their maps compared byte for byte, the result as JSON and a table
"""The benchmark: python3 bench/run.py [--corpus <folder>] [--files 400] [--repeat 3] [--out article/data/languages.json]

Each implementation that is built runs the same commands on the same synthetic corpus (bench/corpus.py), each the
median of --repeat runs: build with a cold cache, build warm, check, brief, ask with one question and with eight,
find, impact, and the guard once per tool call. The maps the four write are compared byte for byte."""
import json
import os
import pathlib
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
IMPLS = {
    'python': (['python3', str(REPO / 'python' / 'map.py')], ['python3', str(REPO / 'python' / 'map-guard.py')]),
    'node': (['node', str(REPO / 'node' / 'map.mjs')], ['node', str(REPO / 'node' / 'map-guard.mjs')]),
    'go': ([str(REPO / 'go' / 'bin' / 'map')], [str(REPO / 'go' / 'bin' / 'map-guard')]),
    'rust': ([str(REPO / 'rust' / 'target' / 'release' / 'map')], [str(REPO / 'rust' / 'target' / 'release' / 'map-guard')]),
}


def available(cmd):
    exe = cmd[0]
    if os.path.isabs(exe):
        return os.path.exists(exe) and (len(cmd) == 1 or os.path.exists(cmd[1]))
    return shutil.which(exe) is not None and all(os.path.exists(c) for c in cmd[1:])


def timed(cmd, cwd, stdin=None, repeat=3):
    runs = []
    for _ in range(repeat):
        t = time.perf_counter()
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, input=stdin, text=True)
        runs.append((time.perf_counter() - t, r.returncode, len(r.stdout)))
    return round(statistics.median(x[0] for x in runs), 4), runs[0][1], runs[0][2]


def main(argv):
    opt = lambda k, d: argv[argv.index(k) + 1] if k in argv else d  # noqa: E731
    repeat = int(opt('--repeat', 3))
    out = pathlib.Path(opt('--out', REPO / 'article' / 'data' / 'languages.json'))
    files = int(opt('--files', 400))
    corpus = opt('--corpus', None)
    tmp = None
    if corpus is None:
        tmp = tempfile.mkdtemp(prefix='map-bench-')
        corpus = os.path.join(tmp, 'corpus')
        subprocess.run([sys.executable, str(HERE / 'corpus.py'), corpus, '--files', str(files)], check=True, capture_output=True)
    corpus = os.path.abspath(corpus)
    py_file = sorted(p for p in pathlib.Path(corpus, 'src', 'shop').glob('*.py'))[0].relative_to(corpus).as_posix()
    cache = pathlib.Path(tempfile.gettempdir()) / 'code-map'
    guard_in = json.dumps({'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': 'grep -rn cart src'}, 'cwd': corpus})
    results = {'corpus': {'files': files, 'path': 'bench/corpus.py --files %d' % files}, 'repeat': repeat, 'implementations': {}}
    reference = None
    for name, (tool, guard) in IMPLS.items():
        if not available(tool):
            results['implementations'][name] = {'skipped': 'not built'}
            print(f'{name}: not built, skipped')
            continue
        shutil.rmtree(cache, ignore_errors=True)
        for p in [pathlib.Path(corpus, 'map.yaml')] + list(pathlib.Path(corpus, 'map').glob('*.yaml')):
            p.unlink(missing_ok=True)
        r = {}
        r['build_cold'] = timed(tool + ['build'], corpus, repeat=1)[0]
        r['build_warm'] = timed(tool + ['build'], corpus, repeat=repeat)[0]
        written = {p.relative_to(corpus).as_posix(): p.read_text() for p in [pathlib.Path(corpus, 'map.yaml')] + sorted(pathlib.Path(corpus, 'map').glob('*.yaml'))}
        if reference is None:
            reference = written
            r['map_matches_python'] = True
        else:
            r['map_matches_python'] = written == reference
        r['check'] = timed(tool + ['check'], corpus, repeat=repeat)[0]
        r['brief'] = timed(tool + ['brief', 'cart', 'price', 'coupon'], corpus, repeat=repeat)[0]
        r['ask_1'] = timed(tool + ['ask', 'run_cart'], corpus, repeat=repeat)[0]
        r['ask_8'] = timed(tool + ['ask', 'run_cart', 'LIMIT_CART', 'src/shop', py_file, 'docs/SHOP.md', 'shop.cart', 'README.md', 'coupon'], corpus, repeat=repeat)[0]
        r['find'] = timed(tool + ['find', 'cart'], corpus, repeat=repeat)[0]
        r['impact'] = timed(tool + ['impact', py_file], corpus, repeat=repeat)[0]
        if available(guard):
            r['guard'] = timed(guard, corpus, stdin=guard_in, repeat=max(repeat, 10))[0]
        results['implementations'][name] = r
        print(f'{name:<7} ' + '  '.join(f'{k} {v:.3f}s' if isinstance(v, float) else f'{k} {v}' for k, v in r.items()))
    blocks = subprocess.run(['python3', str(REPO / 'python' / 'map.py'), 'build'], cwd=corpus, capture_output=True, text=True).stdout.split(' blocks')[0]
    results['corpus']['blocks'] = int(blocks) if blocks.strip().isdigit() else None
    results['source'] = 'bench/run.py on a laptop, the median of %d runs per command; the corpus is bench/corpus.py --files %d' % (repeat, files)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=1) + '\n')
    print(f'written {out}')
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main(sys.argv[1:])
# @end bench.run
