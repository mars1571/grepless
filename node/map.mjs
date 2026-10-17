#!/usr/bin/env node
// @map map.core.rules: the configuration, the comment forms of each language, the repository's files, their areas and the limits
// map: a code map that coding agents read instead of grepping and reading whole files. The Node version: the same
// commands and the same answers as python/map.py (tests/conformance.py checks them), Node 18 or later, no packages.
//   node tools/map.mjs build | check | brief <words> | ask <q> … | find <words> | history <id> | deps|impact <id|file>
//                  | tests [paths|--changed] | recipe [name] | plan <plan.md> | gaps [paths] | init | help | version
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';

const VERSION = '1.0.0';
const CONFIG = {
  command: 'python3 tools/map.py', name: '',
  roots: ['src', 'lib', 'app', 'apps', 'packages', 'pkg', 'internal', 'cmd', 'services'],
  areas: {}, holds: {}, describe: [], ignore: [], forms: {}, limits: { untagged: 30, block: 16000 }, tests: [], recipes: {},
  strict: false, guard: { skip: [] },
};
const FORMS = { slash: [['/*', '*/'], ['//', '']], hash: [['#', '']], html: [['<!--', '-->'], ['/*', '*/'], ['//', '']],
  dash: [['--', '']], semicolon: [[';', '']], percent: [['%', '']] };
const EXT = {};
for (const [form, exts] of Object.entries({
  slash: '.js .mjs .cjs .jsx .ts .tsx .mts .cts .java .kt .kts .scala .groovy .go .rs .swift .c .h .cc .cpp .cxx .hpp .hh .cs .m .mm .php .dart .css .scss .less .proto .zig .d .v',
  hash: '.py .pyi .rb .rake .sh .bash .zsh .fish .pl .pm .r .R .yml .yaml .toml .ps1 .ex .exs .nim .jl .cmake .tf .nix .cr .coffee .mk',
  html: '.html .htm .xml .vue .svelte .astro .xhtml', dash: '.sql .lua .hs .elm .ada .vhd',
  semicolon: '.clj .cljs .cljc .edn .el .lisp .scm .rkt', percent: '.erl .hrl .tex' })) {
  for (const e of exts.split(' ')) EXT[e] = form;
}
const NAMED = { Makefile: 'hash', GNUmakefile: 'hash', Dockerfile: 'hash', Containerfile: 'hash', Rakefile: 'hash', Gemfile: 'hash',
  Justfile: 'hash', Vagrantfile: 'hash', 'CMakeLists.txt': 'hash', Jenkinsfile: 'slash' };
const TEXT = new Set([...Object.keys(EXT), '.md', '.markdown', '.rst', '.txt', '.adoc', '.json', '.ini', '.cfg', '.csv', '.editorconfig']);
const DOCS = new Set(['.md', '.markdown', '.rst', '.txt', '.adoc']);
const SKIP = new Set(['node_modules', 'dist', 'build', 'out', 'target', 'vendor', 'venv', '.venv', '__pycache__', '.git', '.hg', '.svn',
  '.tox', '.mypy_cache', '.pytest_cache', '.cache', 'coverage', '.idea', '.vscode', 'bower_components', '.next', '.nuxt', '.terraform',
  'Pods', 'DerivedData', 'map']);
const BINARY = /\.(png|jpe?g|gif|webp|ico|pdf|zip|gz|woff2?|ttf|otf|mp4|mp3|bin|exe|dylib|so)$/i;
const ID = '[a-z][a-z0-9-]*(?:\\.[a-z0-9-]+)+';
const LARGE = 1_000_000;

const OUT = [];
const print = (s = '') => OUT.push(s);
const flush = () => { if (OUT.length) process.stdout.write(OUT.join('\n') + '\n'); OUT.length = 0; };
const die = (msg, code = 1) => { flush(); process.stderr.write(String(msg) + '\n'); process.exit(code); };
const cmpStr = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const cmpKeys = (ka, kb) => { for (let i = 0; i < ka.length; i++) { const c = typeof ka[i] === 'string' ? cmpStr(ka[i], kb[i]) : ka[i] - kb[i]; if (c) return c; } return 0; };
const sortedBy = (xs, key) => xs.map((x, i) => [key(x), i, x]).sort((a, b) => cmpKeys(a[0], b[0]) || a[1] - b[1]).map(t => t[2]);
const sortedStr = xs => [...xs].sort(cmpStr);
const unique = xs => [...new Set(xs)];
const commas = n => { const s = String(n); return s.replace(/\B(?=(\d{3})+(?!\d))/g, ','); };
const padL = (s, n) => String(s).padStart(n);
const padR = (s, n) => String(s).padEnd(n);
const isAlnum = c => /[\p{L}\p{N}]/u.test(c);
const isUpper = c => c !== c.toLowerCase() && c === c.toUpperCase();
const isLower = c => c !== c.toUpperCase() && c === c.toLowerCase();
const isDigit = c => c >= '0' && c <= '9';
const escapeRe = s => s.replace(/[.*+?^${}()|[\]\\\/-]/g, '\\$&');
const lowerWords = text => text.toLowerCase().match(/[a-z0-9]+/g) || [];
const splitWs = s => s.trim() === '' ? [] : s.trim().split(/\s+/);
const suffixOf = p => { const n = p.slice(p.lastIndexOf('/') + 1); const i = n.lastIndexOf('.'); return i <= 0 ? '' : n.slice(i); };
const read = p => fs.readFileSync(path.join(ROOT, p), 'utf8');

function findRoot(argv) {
  const i = argv.indexOf('--root');
  if (i >= 0) { const r = path.resolve(argv[i + 1]); argv.splice(i, 2); return r; }
  if (process.env.MAP_ROOT) return path.resolve(process.env.MAP_ROOT);
  const here = path.dirname(fs.realpathSync(process.argv[1]));
  for (const mark of ['map.json', '.git']) {
    for (const start of [process.cwd(), here]) {
      let base = start;
      for (;;) {
        if (fs.existsSync(path.join(base, mark))) return base;
        const up = path.dirname(base);
        if (up === base) break;
        base = up;
      }
    }
  }
  return process.cwd();
}

const ARGV = process.argv.slice(2);
const ROOT = findRoot(ARGV);
const MAP = path.join(ROOT, 'map.yaml');
const ZONES = path.join(ROOT, 'map');
const CFG = { ...CONFIG };
if (fs.existsSync(path.join(ROOT, 'map.json'))) {
  let given;
  try { given = JSON.parse(fs.readFileSync(path.join(ROOT, 'map.json'), 'utf8')); } catch (e) { die(`map.json: not JSON (${e.message})`); }
  for (const [k, v] of Object.entries(given)) {
    if (!(k in CONFIG)) die(`map.json: unknown setting "${k}" (the settings: ${Object.keys(CONFIG).join(', ')})`);
    CFG[k] = (k === 'limits' || k === 'guard') ? { ...CONFIG[k], ...v } : v;
  }
}
const CMD = CFG.command;
const UNTAGGED = CFG.limits.untagged ?? 30, LARGEST = CFG.limits.block ?? 16000;

const slug = name => { const s = name.toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, ''); return s && /^[a-z]/.test(s) ? s : 'x' + s; };

function jstr(s) {
  let out = '"';
  for (const ch of String(s)) {
    if (ch === '"') out += '\\"'; else if (ch === '\\') out += '\\\\'; else if (ch === '\n') out += '\\n'; else if (ch === '\r') out += '\\r';
    else if (ch === '\t') out += '\\t'; else if (ch === '\b') out += '\\b'; else if (ch === '\f') out += '\\f';
    else if (ch.codePointAt(0) < 0x20) out += '\\u' + ch.codePointAt(0).toString(16).padStart(4, '0'); else out += ch;
  }
  return out + '"';
}
function jdump(v, indent = null, level = 0) {
  if (v === true) return 'true'; if (v === false) return 'false'; if (v === null || v === undefined) return 'null';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(v);
  if (typeof v === 'string') return jstr(v);
  const isObj = !Array.isArray(v);
  const items = isObj ? Object.entries(v) : v.map(x => [null, x]);
  if (!items.length) return isObj ? '{}' : '[]';
  if (indent === null) return (isObj ? '{' : '[') + items.map(([k, x]) => (k !== null ? jstr(k) + ': ' : '') + jdump(x)).join(', ') + (isObj ? '}' : ']');
  const pad = ' '.repeat(indent * level), padIn = ' '.repeat(indent * (level + 1));
  return (isObj ? '{\n' : '[\n') + items.map(([k, x]) => padIn + (k !== null ? jstr(k) + ': ' : '') + jdump(x, indent, level + 1)).join(',\n') + '\n' + pad + (isObj ? '}' : ']');
}
function tokens(text) {
  const out = []; const t = [...text]; const n = t.length; let i = 0;
  while (i < n) {
    const c = t[i];
    if (isUpper(c)) {
      if (i + 1 < n && (isLower(t[i + 1]) || isDigit(t[i + 1]))) {
        let j = i + 1; while (j < n && (isLower(t[j]) || isDigit(t[j]))) j++;
        out.push(t.slice(i, j).join('').toLowerCase()); i = j; continue;
      }
      let j = i; while (j < n && isUpper(t[j])) j++;
      if (j < n && isLower(t[j]) && j - 1 > i) j--;
      out.push(t.slice(i, j).join('').toLowerCase()); i = j;
    } else if (isLower(c) || isDigit(c)) {
      let j = i; while (j < n && (isLower(t[j]) || isDigit(t[j]))) j++;
      out.push(t.slice(i, j).join('')); i = j;
    } else i++;
  }
  return out;
}
const wordsOf = text => new Set(tokens(String(text)));
function bounded(text, word, left = '', right = '') {
  let start = 0;
  for (;;) {
    const i = text.indexOf(word, start);
    if (i < 0) return false;
    const before = i ? text[i - 1] : '', after = i + word.length < text.length ? text[i + word.length] : '';
    if (!(before && (isAlnum(before) || ('_$' + left).includes(before))) && !(after && (isAlnum(after) || ('_$' + right).includes(after)))) return true;
    start = i + 1;
  }
}
const fnmatchCache = new Map();
function fnmatch(name, pattern) {
  let re = fnmatchCache.get(pattern);
  if (!re) {
    let out = '', i = 0;
    while (i < pattern.length) {
      const c = pattern[i++];
      if (c === '*') out += '.*'; else if (c === '?') out += '.';
      else if (c === '[') {
        let j = i; if (j < pattern.length && pattern[j] === '!') j++; if (j < pattern.length && pattern[j] === ']') j++;
        while (j < pattern.length && pattern[j] !== ']') j++;
        if (j >= pattern.length) out += '\\[';
        else { let stuff = pattern.slice(i, j).replace(/\\/g, '\\\\'); i = j + 1; if (stuff[0] === '!') stuff = '^' + stuff.slice(1); else if (stuff[0] === '^') stuff = '\\' + stuff; out += '[' + stuff + ']'; }
      } else out += escapeRe(c);
    }
    re = new RegExp('^(?:' + out + ')$', 's'); fnmatchCache.set(pattern, re);
  }
  return re.test(name);
}
// @end map.core.rules

// @map map.core.files: the repository's files and their comment forms, what .gitignore and map.json leave out, each file's area, the tags' patterns
function forms(p) {
  const name = p.slice(p.lastIndexOf('/') + 1), suffix = suffixOf(name);
  let form = CFG.forms[suffix] !== undefined ? CFG.forms[suffix] : (NAMED[name] || EXT[suffix]);
  if (!form && !suffix && isFile(p)) {
    try { const fd = fs.openSync(path.join(ROOT, p), 'r'); const b = Buffer.alloc(2); const n = fs.readSync(fd, b, 0, 2, 0); fs.closeSync(fd); form = n === 2 && b.toString() === '#!' ? 'hash' : null; } catch { form = null; }
  }
  return form ? FORMS[form] || null : null;
}
const isFile = p => { try { return fs.statSync(path.join(ROOT, p)).isFile(); } catch { return false; } };
const isDir = p => { try { return fs.statSync(path.join(ROOT, p)).isDirectory(); } catch { return false; } };
const exists = p => fs.existsSync(path.join(ROOT, p));
const sizeOf = p => fs.statSync(path.join(ROOT, p)).size;
function ignored(p) {
  const parts = p.split('/');
  if (parts.slice(0, -1).some(x => SKIP.has(x)) || parts[parts.length - 1] === 'map.yaml') return true;
  return CFG.ignore.some(q => p === q.replace(/\/+$/, '') || p.startsWith(q.replace(/\/+$/, '') + '/') || fnmatch(p, q));
}
let _files = null;
function gitIgnored() {
  let lines; try { lines = fs.readFileSync(path.join(ROOT, '.gitignore'), 'utf8').split('\n'); } catch { return []; }
  return lines.map(l => l.trim()).filter(l => l && !l.startsWith('#') && !l.startsWith('!'));
}
function repoFiles() {
  if (_files) return _files;
  let found = [], top = '';
  try { const r = spawnSync('git', ['rev-parse', '--show-toplevel'], { cwd: ROOT, encoding: 'utf8' }); top = (r.stdout || '').trim(); } catch { top = ''; }
  if (top && fs.realpathSync(top) === fs.realpathSync(ROOT)) {
    const r = spawnSync('git', ['ls-files', '--cached', '--others', '--exclude-standard', '-z'], { cwd: ROOT, encoding: 'utf8', maxBuffer: 1 << 28 });
    found = (r.stdout || '').split('\0').filter(p => p && isFile(p) && !fs.lstatSync(path.join(ROOT, p)).isSymbolicLink());
  } else {
    const skip = gitIgnored();
    const leftOut = (rel, dir) => {
      const parts = rel.split('/');
      for (const p of skip) {
        const folder = p.endsWith('/'), q = p.replace(/^\/+|\/+$/g, '');
        if (q.includes('/')) { if (rel === q || rel.startsWith(q + '/') || fnmatch(rel, q)) return true; }
        else if ((dir || !folder ? parts : parts.slice(0, -1)).some(n => fnmatch(n, q))) return true;
      }
      return false;
    };
    const walk = rel => {
      const base = rel === '.' ? ROOT : path.join(ROOT, rel);
      const entries = fs.readdirSync(base, { withFileTypes: true });
      const dirs = sortedStr(entries.filter(e => e.isDirectory()).map(e => e.name)).filter(d => !SKIP.has(d) && !leftOut(rel === '.' ? d : `${rel}/${d}`, true));
      for (const n of sortedStr(entries.filter(e => !e.isDirectory()).map(e => e.name))) {
        const p = rel === '.' ? n : `${rel}/${n}`;
        const st = fs.lstatSync(path.join(ROOT, p));
        if (!st.isSymbolicLink() && st.isFile() && !leftOut(p, false)) found.push(p);
      }
      for (const d of dirs) walk(rel === '.' ? d : `${rel}/${d}`);
    };
    walk('.');
  }
  _files = sortedStr(found.filter(p => !ignored(p)));
  return _files;
}
function described(p) {
  for (const [pattern, kind, about] of CFG.describe) if (fnmatch(p, pattern) || fnmatch(p.slice(p.lastIndexOf('/') + 1), pattern)) return [pattern, kind, about];
  return null;
}
let _code = null;
const files = () => _code || (_code = repoFiles().filter(p => forms(p) && !described(p)));
function areaOf(p) {
  let best = null;
  for (const [prefix, area] of Object.entries(CFG.areas)) {
    const q = prefix.replace(/\/+$/, '');
    if (q === '' || q === '.') { if (!p.includes('/') && best === null) best = ['', area]; }
    else if ((p === q || p.startsWith(q + '/')) && (best === null || q.length > best[0].length)) best = [q, area];
  }
  if (best) return slug(best[1]);
  const parts = p.split('/');
  if (parts.length === 1) return 'root';
  if (CFG.roots.includes(parts[0]) && parts.length > 2) return slug(parts[1]);
  return slug(parts[0].replace(/^\.+/, '') || parts[0]);
}
let _areas = null;
function areas() {
  if (!_areas) _areas = new Set([...files().map(areaOf), ...Object.values(CFG.areas).map(slug), ...Object.keys(CFG.holds)]);
  return _areas;
}
function tagPatterns(form) {
  const tag = form.map(([o, c]) => '^[ \\t]*' + escapeRe(o) + '[ \\t]*@(map|end)[ \\t]+(' + ID + ')(?::[ \\t]*(.*?))?[ \\t]*' + escapeRe(c) + '[ \\t]*$').join('|');
  const looks = form.map(([o]) => '^[ \\t]*' + escapeRe(o) + '[ \\t]*@(?:map|end)\\b').join('|');
  return [new RegExp(tag), new RegExp(looks)];
}
function tagMatch(pattern, line) {
  const m = pattern.exec(line);
  if (!m) return null;
  for (let i = 1; i < m.length; i += 3) if (m[i]) return [m[i], m[i + 1], (m[i + 2] || '').trim()];
  return null;
}
const component = id => id.split('.').slice(0, 2).join('.');
function isTest(p) {
  const name = p.slice(p.lastIndexOf('/') + 1);
  if (CFG.tests.length && CFG.tests.some(g => fnmatch(p, g))) return true;
  const stem = name.includes('.') ? name.slice(0, name.lastIndexOf('.')) : name;
  return p.split('/').slice(0, -1).some(x => ['tests', 'test', 'spec', 'specs', '__tests__'].includes(x)) || /(^|[._-])(test|tests|spec)([._-]|$)/.test(stem + '.');
}
// @end map.core.files

// @map map.core.parse: a file's tags into blocks, the problems found on the way, and every block of the repository
function parse(p, text) {
  const lines = (text !== undefined ? text : read(p)).split('\n');
  if (lines.length && lines[lines.length - 1] === '') lines.pop();
  const blocks = [], open = [], problems = [];
  const form = forms(p);
  if (!form) return [blocks, problems, []];
  const [tag, looks] = tagPatterns(form);
  const known = areas();
  const close = (upto, keep = null) => { while (open.length && (keep === null || !(keep === open[open.length - 1].id || keep.startsWith(open[open.length - 1].id + '.')))) open.pop().last = upto; };
  lines.forEach((line, k) => {
    const n = k + 1;
    const m = tagMatch(tag, line);
    if (!m) {
      if (looks.test(line)) problems.push([n, 'a tag that cannot be read: "@map <id>: <purpose>" or "@end <id>", alone on its line']);
      else if (line.startsWith('#!') && n > 1) problems.push([n, 'the #! line must stay the first line: put the tag below it']);
      return;
    }
    const [kind, id, purpose] = m;
    if (kind === 'map') {
      if (!known.has(id.split('.')[0])) problems.push([n, `${id}: its first word is not an area (${sortedStr(known).join(', ')}); the file's area is ${areaOf(p)}`]);
      if (splitWs(purpose).length < 3) problems.push([n, `${id} needs a purpose of three words or more`]);
      if (blocks.some(b => b.id === id)) problems.push([n, `${id} appears twice in this file`]);
      close(n - 1, id);
      const b = { id, purpose, first: n, last: null, path: p };
      blocks.push(b); open.push(b);
    } else if (!open.some(b => b.id === id)) problems.push([n, `@end ${id} closes no open block`]);
    else { while (open.length) { const b = open.pop(); b.last = n; if (b.id === id) break; } }
  });
  close(lines.length);
  const depth = new Array(lines.length + 1).fill(0);
  for (const b of blocks) for (let i = b.first; i <= b.last; i++) depth[i]++;
  for (const b of blocks) {
    const mine = blocks.filter(o => o.first <= b.first && o.last >= b.last).length;
    let own = 0; for (let i = b.first; i <= b.last; i++) if (depth[i] === mine) own += lines[i - 1].length + 1;
    b.own = own; b.lines = b.last - b.first + 1;
  }
  const outside = []; for (let i = 1; i <= lines.length; i++) if (!depth[i] && lines[i - 1].trim()) outside.push(i);
  return [blocks, problems, outside];
}
let _cache = null;
const CACHE = path.join(os.tmpdir(), 'code-map', 'node-' + crypto.createHash('sha1').update(ROOT).digest('hex').slice(0, 12) + '.json');
function facts(p) {
  if (!_cache) {
    try { _cache = JSON.parse(fs.readFileSync(CACHE, 'utf8')); if (_cache.version !== VERSION) _cache = {}; } catch { _cache = {}; }
    _cache.version = VERSION; _cache.files = _cache.files || {}; _cache.dirty = false;
  }
  const st = fs.statSync(path.join(ROOT, p), { bigint: true });
  const key = `${st.mtimeNs}:${st.size}:${areaOf(p)}`;
  const kept = _cache.files[p];
  if (kept && kept.key === key) return kept;
  const text = read(p);
  const [blocks, problems, outside] = parse(p, text);
  const f = { key, blocks, problems, outside, decls: declarationsIn(p, text), imports: importsIn(p, text) };
  _cache.files[p] = f; _cache.dirty = true;
  return f;
}
function saveCache() {
  if (!_cache || !_cache.dirty) return;
  try {
    fs.mkdirSync(path.dirname(CACHE), { recursive: true });
    const keep = new Set(repoFiles());
    const data = { version: VERSION, files: Object.fromEntries(Object.entries(_cache.files).filter(([p]) => keep.has(p))) };
    const tmp = `${CACHE}.${process.pid}.tmp`; fs.writeFileSync(tmp, JSON.stringify(data)); fs.renameSync(tmp, CACHE);
  } catch { /* no cache: the next run reads everything again */ }
}
function everything() {
  const all = [], problems = [], untagged = [];
  for (const p of files()) {
    const f = facts(p);
    all.push(...f.blocks.map(b => ({ ...b })));
    problems.push(...f.problems.map(([n, x]) => [p, n, x]));
    if (!f.blocks.length) untagged.push(p);
    else if (f.outside.length > UNTAGGED) problems.push([p, f.outside[0], `${f.outside.length} lines outside blocks (at most ${UNTAGGED}); the first is this one`]);
    for (const b of f.blocks) if (b.own > LARGEST) problems.push([p, b.first, `${b.id} holds ${commas(b.own)} characters of its own (at most ${commas(LARGEST)}): split it with blocks inside it`]);
  }
  return [all, problems, untagged];
}
// @end map.core.parse

// @map map.code.declarations: what each file declares (functions, classes, methods, values, headings), by the shape of each language, with each one's lines
const KEYWORDS = new Set(['if', 'for', 'while', 'switch', 'catch', 'return', 'else', 'do', 'new', 'function', 'sizeof', 'typeof', 'throw', 'case', 'super',
  'this', 'await', 'yield', 'delete', 'void', 'in', 'of', 'try', 'finally', 'with', 'elif', 'until', 'unless', 'when', 'match', 'loop', 'defer', 'go',
  'select', 'foreach', 'lock', 'using', 'fixed', 'typedef', 'struct', 'union', 'enum']);
const LANG = { '.js': 'js', '.mjs': 'js', '.cjs': 'js', '.jsx': 'js', '.ts': 'js', '.tsx': 'js', '.mts': 'js', '.cts': 'js', '.dart': 'js', '.go': 'go', '.rs': 'rust',
  '.java': 'jvm', '.kt': 'jvm', '.kts': 'jvm', '.scala': 'jvm', '.groovy': 'jvm', '.cs': 'jvm', '.swift': 'swift', '.rb': 'ruby', '.rake': 'ruby', '.php': 'php',
  '.c': 'c', '.h': 'c', '.cc': 'c', '.cpp': 'c', '.cxx': 'c', '.hpp': 'c', '.hh': 'c', '.m': 'c', '.mm': 'c', '.sh': 'sh', '.bash': 'sh', '.zsh': 'sh',
  '.ex': 'elixir', '.exs': 'elixir', '.lua': 'lua', '.sql': 'sql', '.pl': 'perl', '.pm': 'perl', '.py': 'py', '.pyi': 'py' };
const BRACES = new Set(['js', 'go', 'rust', 'jvm', 'swift', 'php', 'c', 'sh', 'perl']);
const DECL = {
  py: [['^\\s*(?:async\\s+)?def\\s+([A-Za-z_]\\w*)', 'function'], ['^\\s*class\\s+([A-Za-z_]\\w*)', 'class'], ['^([A-Za-z_]\\w*)\\s*(?::[^=]+?)?=', 'value']],
  js: [['^\\s*(?:export\\s+)?(?:default\\s+)?(?:async\\s+)?function\\s*\\*?\\s*([A-Za-z_$][\\w$]*)', 'function'],
    ['^\\s*(?:export\\s+)?(?:default\\s+)?(?:abstract\\s+)?class\\s+([A-Za-z_$][\\w$]*)', 'class'],
    ['^\\s*(?:export\\s+)?(?:const|let|var)\\s+([A-Za-z_$][\\w$]*)\\s*(?::[^=]+?)?=\\s*(?:async\\s*)?(?:\\([^)]*\\)\\s*(?::\\s*[^=]+?)?=>|function\\b|[A-Za-z_$][\\w$]*\\s*=>|class\\b)', 'function'],
    ['^\\s*(?:export\\s+)?(?:const|let|var)\\s+([A-Za-z_$][\\w$]*)\\s*(?::[^=]+?)?=\\s*(?:\\{|\\[|new\\s+\\w+|[\'"`\\d-]|require\\(|await\\b)', 'value'],
    ['^\\s*(?:export\\s+)?(?:interface|type|enum|namespace)\\s+([A-Za-z_$][\\w$]*)', 'type'],
    ['^\\s{2,}(?:(?:public|private|protected|static|async|readonly|override|get|set|abstract)\\s+)*\\*?([A-Za-z_$][\\w$]*)\\s*(?:<[^>]*>)?\\s*\\([^)]*\\)\\s*(?::\\s*[^{;]+)?\\s*\\{\\s*$', 'method']],
  go: [['^func\\s+(?:\\([^)]*\\)\\s*)?([A-Za-z_]\\w*)', 'function'], ['^type\\s+([A-Za-z_]\\w*)\\s+(?:struct|interface)', 'type'], ['^(?:var|const)\\s+([A-Za-z_]\\w*)\\s', 'value']],
  rust: [['^\\s*(?:pub(?:\\([^)]*\\))?\\s+)?(?:async\\s+)?(?:const\\s+)?(?:unsafe\\s+)?fn\\s+([A-Za-z_]\\w*)', 'function'],
    ['^\\s*(?:pub(?:\\([^)]*\\))?\\s+)?(?:struct|enum|trait|type|mod|union)\\s+([A-Za-z_]\\w*)', 'type'],
    ['^\\s*impl(?:<[^>]*>)?\\s+(?:[\\w:<>]+\\s+for\\s+)?([A-Za-z_]\\w*)', 'impl'],
    ['^\\s*(?:pub(?:\\([^)]*\\))?\\s+)?(?:static|const)\\s+([A-Za-z_]\\w*)\\s*:', 'value']],
  jvm: [['^\\s*(?:(?:public|private|protected|internal|static|final|abstract|sealed|open|data|inner|override|synchronized|native|default|case|partial)\\s+)*(?:class|interface|enum|record|object|trait|struct)\\s+([A-Za-z_]\\w*)', 'class'],
    ['^\\s*(?:(?:public|private|protected|internal|static|final|abstract|override|synchronized|native|default|open|suspend|inline|operator|virtual|async|partial|unsafe|extern|new)\\s+)+(?:fun\\s+|def\\s+)?(?:[\\w<>\\[\\],.?]+\\s+)?([A-Za-z_]\\w*)\\s*(?:<[^>]*>)?\\s*\\(', 'method'],
    ['^\\s+(?:fun|def)\\s+(?:<[^>]*>\\s*)?(?:[\\w.]+\\.)?([A-Za-z_]\\w*)\\s*\\(', 'method']],
  swift: [['^\\s*(?:(?:public|private|internal|fileprivate|open|static|final|override|mutating|class|convenience|required)\\s+)*(?:func|class|struct|enum|protocol|extension|actor)\\s+([A-Za-z_]\\w*)', 'function']],
  ruby: [['^\\s*def\\s+(?:self\\.)?([A-Za-z_]\\w*[?!=]?)', 'method'], ['^\\s*(?:class|module)\\s+([A-Z][\\w:]*)', 'class']],
  php: [['^\\s*(?:(?:public|private|protected|static|abstract|final)\\s+)*function\\s+&?([A-Za-z_]\\w*)', 'function'], ['^\\s*(?:abstract\\s+|final\\s+|readonly\\s+)*(?:class|interface|trait|enum)\\s+([A-Za-z_]\\w*)', 'class']],
  c: [['^[A-Za-z_][\\w\\s\\*&:<>,]*?[\\s\\*&]([A-Za-z_]\\w*)\\s*\\([^;{]*\\)\\s*(?:const\\s*)?(?:\\{|$)', 'function'], ['^\\s*(?:typedef\\s+)?(?:struct|union|enum|class)\\s+([A-Za-z_]\\w*)\\s*(?:\\{|$)', 'type'], ['^#define\\s+([A-Za-z_]\\w*)', 'value']],
  sh: [['^\\s*(?:function\\s+)?([A-Za-z_][\\w-]*)\\s*\\(\\s*\\)\\s*\\{?', 'function'], ['^\\s*function\\s+([A-Za-z_][\\w-]*)', 'function']],
  elixir: [['^\\s*defp?\\s+([a-z_]\\w*[?!]?)', 'function'], ['^\\s*defmodule\\s+([\\w.]+)', 'class']],
  lua: [['^\\s*(?:local\\s+)?function\\s+([\\w.:]+)', 'function']],
  sql: [['^\\s*create\\s+(?:or\\s+replace\\s+)?(?:temp(?:orary)?\\s+)?(?:table|view|function|procedure|index|trigger|type)\\s+(?:if\\s+not\\s+exists\\s+)?([\\w."]+)', 'sql']],
  perl: [['^\\s*sub\\s+([A-Za-z_]\\w*)', 'function']],
};
const DECL_RX = {}; for (const [lang, rules] of Object.entries(DECL)) DECL_RX[lang] = rules.map(([rx, kind]) => [new RegExp(rx, lang === 'sql' ? 'i' : ''), kind]);
const PROTOTYPE = /\)\s*[;=]/;
function braceEnd(lines, i, most = 1500) {
  let depth = 0, quote = null, seen = false;
  for (let k = i - 1; k < Math.min(lines.length, i - 1 + most); k++) {
    const s = lines[k]; let j = 0;
    while (j < s.length) {
      const c = s[j];
      if (quote) { if (c === '\\') j++; else if (c === quote) quote = null; }
      else if (c === '\'' || c === '"' || c === '`') quote = c;
      else if (s.startsWith('//', j)) break;
      else if (c === '{') { depth++; seen = true; }
      else if (c === '}') { depth--; if (seen && depth === 0) return k + 1; }
      j++;
    }
    if (quote === '"' || quote === '\'') quote = null;
    if (!seen && k > i && s.trim() && !/^\s*(\{|\/\/|\/\*|\*|#)/.test(s)) return i;
  }
  return !seen ? i : Math.min(lines.length, i - 1 + most);
}
function indentEnd(lines, i, indent) {
  let last = i;
  for (let k = i; k < lines.length; k++) {
    const s = lines[k]; if (!s.trim()) continue;
    const ind = s.length - s.trimStart().length;
    if (ind <= indent && k > i - 1) { if (/^\s*(?:end|\}|\))\b/.test(s)) return k + 1; break; }
    last = k + 1;
  }
  return last;
}
function declarationsIn(p, text) {
  const lines = text.split('\n'), suffix = suffixOf(p).toLowerCase();
  if (DOCS.has(suffix)) {
    const out = []; let fence = false;
    lines.forEach((line, k) => {
      if (line.startsWith('```')) fence = !fence;
      else if (!fence) { const m = /^(#{1,6})\s+(.*)/.exec(line); if (m) out.push({ name: m[2].trim(), kind: 'heading', first: k + 1, last: k + 1, what: line.trim().slice(0, 120) }); }
    });
    return out;
  }
  const lang = LANG[suffix];
  if (!lang || !DECL_RX[lang]) return [];
  const out = [];
  lines.forEach((line, k) => {
    const i = k + 1;
    const lead = line.trimStart();
    if (!line.trim() || (/^(\/\/|#|\*|\/\*|--|"|')/.test(lead) && !(lang === 'c' && line.startsWith('#define')))) return;
    for (const [rx, kind] of DECL_RX[lang]) {
      const m = rx.exec(line);
      if (!m || KEYWORDS.has(m[1])) continue;
      const end = m.index + m[0].length;
      if (lang === 'py' && kind === 'value' && end < line.length && line[end] === '=') continue;
      if (lang === 'jvm' && kind === 'method' && PROTOTYPE.test(line.slice(end - 1))) continue;
      if (lang === 'c' && kind === 'function' && (/^\s/.test(line) || KEYWORDS.has(splitWs(line)[0]))) continue;
      let first = i, last;
      if (BRACES.has(lang) && kind !== 'value') last = braceEnd(lines, i);
      else if (kind === 'value') last = /[{[(]$/.test(line.trimEnd()) ? braceEnd(lines, i) : i;
      else last = indentEnd(lines, i, line.length - line.trimStart().length);
      if (lang === 'py' && (kind === 'function' || kind === 'class')) while (first > 1 && lines[first - 2].trimStart().startsWith('@')) first--;
      out.push({ name: m[1], kind, first, last: Math.max(i, last), what: line.trim().slice(0, 120) });
      break;
    }
  });
  return out;
}
// @end map.code.declarations

// @map map.code.imports: what each file imports, by language, resolved to the repository's own files
const IMPORT = {
  py: ['^\\s*from\\s+([\\w.]+)\\s+import\\b', '^\\s*import\\s+([\\w.]+(?:\\s*,\\s*[\\w.]+)*)'],
  js: ['\\bfrom\\s+[\'"]([^\'"]+)[\'"]', '\\brequire\\(\\s*[\'"]([^\'"]+)[\'"]\\s*\\)', '\\bimport\\(\\s*[\'"]([^\'"]+)[\'"]\\s*\\)', '^\\s*import\\s+[\'"]([^\'"]+)[\'"]'],
  go: ['^\\s*import\\s+(?:\\w+\\s+)?"([^"]+)"', '^\\s+(?:\\w+\\s+)?"([\\w./-]+)"\\s*$'],
  rust: ['^\\s*(?:pub\\s+)?use\\s+((?:crate|super|self)::[\\w:]+)', '^\\s*(?:pub\\s+)?mod\\s+(\\w+)\\s*;'],
  jvm: ['^\\s*import\\s+(?:static\\s+)?([\\w.]+)', '^\\s*using\\s+([\\w.]+)\\s*;'],
  ruby: ['\\brequire_relative\\s+[\'"]([^\'"]+)[\'"]', '\\brequire\\s+[\'"]([^\'"]+)[\'"]'],
  php: ['\\b(?:require|include)(?:_once)?\\s*\\(?\\s*(?:__DIR__\\s*\\.\\s*)?[\'"]([^\'"]+)[\'"]', '^\\s*use\\s+([\\w\\\\]+)'],
  c: ['^\\s*#\\s*include\\s+"([^"]+)"'], sh: ['^\\s*(?:source|\\.)\\s+([^\\s;|&]+)'],
  css: ['@import\\s+(?:url\\()?[\'"]([^\'"]+)[\'"]', '@use\\s+[\'"]([^\'"]+)[\'"]'],
  html: ['<script[^>]+src=["\']([^"\']+)["\']', '<link[^>]+href=["\']([^"\']+\\.css)["\']'],
};
const IMPORT_RX = {}; for (const [lang, rules] of Object.entries(IMPORT)) IMPORT_RX[lang] = rules.map(rx => new RegExp(rx, 'g'));
const IMPORT_LANG = { ...LANG, '.css': 'css', '.scss': 'css', '.less': 'css', '.html': 'html', '.htm': 'html', '.vue': 'js', '.svelte': 'js', '.astro': 'js' };
function importsIn(p, text) {
  const lang = IMPORT_LANG[suffixOf(p).toLowerCase()];
  if (!lang || !IMPORT_RX[lang]) return [];
  const out = []; let inBlock = false;
  text.split('\n').forEach((line, k) => {
    if (lang === 'go') {
      if (/^\s*import\s*\(/.test(line)) { inBlock = true; return; }
      if (inBlock && line.trim() === ')') { inBlock = false; return; }
      if (!inBlock && !/^\s*import\b/.test(line)) return;
    }
    for (const rx of IMPORT_RX[lang]) { rx.lastIndex = 0; let m; while ((m = rx.exec(line))) { for (const one of m[1].split(/\s*,\s*/)) out.push([k + 1, one.trim()]); if (!m[0]) rx.lastIndex++; } }
  });
  return out;
}
function normpath(p) {
  const out = [];
  for (const seg of p.split('/')) { if (seg === '' || seg === '.') continue; if (seg === '..') { if (out.length && out[out.length - 1] !== '..') out.pop(); else out.push(seg); } else out.push(seg); }
  return out.join('/') || '.';
}
class Resolver {
  constructor(paths) {
    this.paths = new Set(paths); this.bySuffix = new Map();
    for (const p of paths) { const parts = p.split('/'); for (let k = 1; k <= Math.min(parts.length, 4); k++) { const key = parts.slice(-k).join('/'); if (!this.bySuffix.has(key)) this.bySuffix.set(key, []); this.bySuffix.get(key).push(p); } }
    this.gomod = '';
    if (isFile('go.mod')) { const m = /^module\s+(\S+)/m.exec(read('go.mod')); this.gomod = m ? m[1] : ''; }
  }
  file(p) { const q = normpath(p); return this.paths.has(q) ? q : null; }
  * candidates(base, exts) { for (const e of exts) yield base + e; for (const e of exts) { yield base + '/index' + e; yield base + '/__init__' + e; yield base + '/mod' + e; } }
  resolve(p, what) {
    const folder = p.includes('/') ? p.slice(0, p.lastIndexOf('/')) : '.';
    const lang = IMPORT_LANG[suffixOf(p).toLowerCase()];
    const exts = { js: ['.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.mts', '.cts', '.vue', '.svelte'], py: ['.py'], ruby: ['.rb'], rust: ['.rs'], css: ['.css', '.scss', '.less'],
      go: ['.go'], jvm: ['.java', '.kt', '.scala', '.cs'], php: ['.php'], c: ['.h', '.hpp', '.c', '.cc', '.cpp'], sh: ['', '.sh'], html: [''] }[lang] || [''];
    const found = new Set();
    if (what.startsWith('./') || what.startsWith('../') || what.startsWith('/') || (['c', 'css', 'html', 'sh', 'php', 'ruby'].includes(lang) && what.includes('/'))
      || (lang === 'js' && !what.startsWith('.') && what.includes('/') && ['src', 'lib', 'app'].includes(what.split('/')[0]))) {
      const base = what.startsWith('/') ? what.replace(/^\/+/, '') : folder + '/' + what;
      for (const c of [base, ...this.candidates(base, exts)]) { const f = this.file(c); if (f) { found.add(f); break; } }
    } else if (lang === 'py') {
      const dots = what.length - what.replace(/^\.+/, '').length, name = what.replace(/^\.+/, '');
      let bases;
      if (dots) { let up = folder; for (let k = 0; k < dots - 1; k++) up = up.includes('/') ? up.slice(0, up.lastIndexOf('/')) : '.'; bases = [up]; }
      else bases = ['.', folder, ...CFG.roots.filter(r => isDir(r))];
      const rel = name.replace(/\./g, '/');
      for (const b of bases) { for (const c of this.candidates(rel ? b + '/' + rel : b, ['.py'])) { const f = this.file(c); if (f) { found.add(f); break; } } if (found.size) break; }
      if (!found.size && rel) for (const c of [...(this.bySuffix.get(rel + '.py') || []), ...(this.bySuffix.get(rel + '/__init__.py') || [])]) found.add(c);
    } else if (lang === 'go' && this.gomod && what.startsWith(this.gomod)) {
      const rel = what.slice(this.gomod.length).replace(/^\/+|\/+$/g, '');
      for (const q of this.paths) if (q.endsWith('.go') && (q.includes('/') ? q.slice(0, q.lastIndexOf('/')) : '.') === (rel || '.')) found.add(q);
    } else if (lang === 'rust') {
      const parts = what.replace('crate::', '').replace('self::', '').replace('super::', '').split('::').filter(x => x && x !== 'crate');
      for (let k = parts.length; k > 0; k--) { for (const r of ['src', folder]) for (const c of this.candidates(r + '/' + parts.slice(0, k).join('/'), ['.rs'])) { const f = this.file(c); if (f) found.add(f); } if (found.size) break; }
    } else if (lang === 'jvm') {
      const parts = what.split('.');
      for (let k = parts.length; k > 1; k--) { for (const e of exts) for (const c of this.bySuffix.get(parts.slice(0, k).slice(-4).join('/') + e) || []) if (c.endsWith(parts.slice(0, k).join('/') + e)) found.add(c); if (found.size) break; }
    } else if (lang === 'php' && what.includes('\\')) {
      const parts = what.replace(/^\\+|\\+$/g, '').split('\\');
      for (const c of [...(this.bySuffix.get(parts.slice(-2).join('/') + '.php') || []), ...(this.bySuffix.get(parts[parts.length - 1] + '.php') || [])]) found.add(c);
    } else if (lang === 'ruby') {
      for (const c of this.candidates('lib/' + what, ['.rb'])) { const f = this.file(c); if (f) found.add(f); }
    }
    return found;
  }
}
class Graph {
  constructor(blocks) {
    this.blocks = blocks; this.byFile = new Map();
    for (const b of blocks) { if (!this.byFile.has(b.path)) this.byFile.set(b.path, []); this.byFile.get(b.path).push(b); }
    this.purpose = new Map();
    for (const b of sortedBy(blocks, b => [b.path])) if (!this.purpose.has(b.id)) this.purpose.set(b.id, b.purpose);
    this.main = new Map();
    for (const [p, bs] of this.byFile) { const n = new Map(); for (const b of bs) { const c = component(b.id); n.set(c, (n.get(c) || 0) + b.lines); } this.main.set(p, mostCommon(n)[0][0]); }
    const paths = repoFiles().filter(p => TEXT.has(suffixOf(p).toLowerCase()) || forms(p));
    const r = new Resolver(paths);
    this.fileEdges = new Map(); this.edges = new Map();
    for (const p of files()) {
      for (const [line, what] of facts(p).imports) {
        for (const target of sortedStr(r.resolve(p, what))) {
          if (target === p) continue;
          if (!this.fileEdges.has(p)) this.fileEdges.set(p, new Set());
          this.fileEdges.get(p).add(target);
          const src = this.at(p, line) || this.main.get(p), dst = this.main.get(target);
          if (src && dst && component(src) !== dst) { const k = component(src) + '\u0000' + dst; this.edges.set(k, (this.edges.get(k) || 0) + 1); }
        }
      }
    }
    this.importers = new Map();
    for (const [p, ts] of this.fileEdges) for (const t of ts) { if (!this.importers.has(t)) this.importers.set(t, new Set()); this.importers.get(t).add(p); }
  }
  at(p, line) {
    const inside = (this.byFile.get(p) || []).filter(b => b.first <= line && line <= b.last);
    if (!inside.length) return null;
    let best = inside[0]; for (const b of inside) if (b.first > best.first || (b.first === best.first && b.last < best.last)) best = b;
    return best.id;
  }
  edgePairs() { return [...this.edges.keys()].map(k => k.split('\u0000')); }
}
function mostCommon(counter) { return sortedBy([...counter.entries()], ([, v]) => [-v]); }
// @end map.code.imports

// @map map.core.write: map.yaml, the central map of the areas, and map/<area>.yaml, each area's components; build and check
function header(name, blocks, perFile) {
  const mine = blocks.filter(b => component(b.id) === name);
  if (!mine.length) return null;
  const first = sortedBy(mine, b => [b.path, b.first])[0];
  return perFile.get(first.path) === mine.filter(b => b.path === first.path).length ? first.purpose : null;
}
const ID_LIKE = /[a-z][a-z0-9-]*\.[a-z0-9-]+/g;
function idsIn(text) {
  const out = new Set(); let m; ID_LIKE.lastIndex = 0;
  while ((m = ID_LIKE.exec(text))) {
    const before = m.index ? text[m.index - 1] : '', after = m.index + m[0].length < text.length ? text[m.index + m[0].length] : '';
    if (!(before && (isAlnum(before) || '_.'.includes(before))) && !(after && (isAlnum(after) || '_-'.includes(after)))) out.add(m[0]);
  }
  return out;
}
function docsNaming(comps) {
  const paths = repoFiles().filter(p => DOCS.has(suffixOf(p).toLowerCase()) && sizeOf(p) < LARGE);
  const names = new Map();
  for (const c of comps.values()) for (const f of c.files) { const n = f.slice(f.lastIndexOf('/') + 1); names.set(n, (names.get(n) || 0) + 1); }
  const allFiles = new Set(); for (const c of comps.values()) for (const f of c.files) allFiles.add(f);
  const found = new Map();
  for (const p of paths) {
    const text = read(p);
    const said = new Set([...idsIn(text)].filter(x => comps.has(x)));
    const hit = new Set([...allFiles].filter(f => text.includes(f) || (names.get(f.slice(f.lastIndexOf('/') + 1)) === 1 && text.includes('`' + f.slice(f.lastIndexOf('/') + 1) + '`'))));
    for (const [name, c] of comps) if ([...c.files].some(f => hit.has(f))) said.add(name);
    found.set(p, said);
  }
  return found;
}
const testFiles = () => repoFiles().filter(p => isTest(p) && (forms(p) || TEXT.has(suffixOf(p).toLowerCase())));
function testsReaching(g, comps) {
  const out = new Map(); for (const name of comps.keys()) out.set(name, new Map());
  const filesOf = new Map();
  for (const [name, c] of comps) for (const f of c.files) { if (!filesOf.has(f)) filesOf.set(f, new Set()); filesOf.get(f).add(name); }
  for (const t of testFiles()) {
    for (const target of sortedStr(g.fileEdges.get(t) || [])) for (const name of sortedStr(filesOf.get(target) || [])) out.get(name).set(t, 'imports ' + target);
    let text; try { text = read(t); } catch { continue; }
    for (const [name, c] of comps) {
      if (out.get(name).has(t)) continue;
      if ([...c.files].some(f => f !== t && text.includes(f)) || (text.includes(name) && bounded(text, name, '.', '-'))) out.get(name).set(t, 'names it');
    }
  }
  return out;
}
function components(blocks, g) {
  const purpose = new Map();
  for (const b of sortedBy(blocks, b => [b.path])) if (!purpose.has(b.id)) purpose.set(b.id, b.purpose);
  const comps = new Map();
  for (const b of blocks) {
    const name = component(b.id);
    if (!comps.has(name)) comps.set(name, { files: new Set(), parts: new Set(), needs: new Set(), by: new Set(), docs: new Set(), declares: [], blocks: 0, lines: 0, tests: new Map(), what: '' });
    const c = comps.get(name); c.files.add(b.path); c.blocks++; c.lines += b.lines;
    if (b.id.split('.').length > 2) c.parts.add(b.id.split('.')[2]);
  }
  const perFile = new Map(); for (const b of blocks) perFile.set(b.path, (perFile.get(b.path) || 0) + 1);
  const firstOf = new Map(); for (const b of sortedBy(blocks, b => [b.path, b.first])) if (!firstOf.has(component(b.id))) firstOf.set(component(b.id), b.purpose);
  for (const [name, c] of comps) c.what = purpose.get(name) || header(name, blocks, perFile) || purpose.get(name + '.api') || firstOf.get(name) || '';
  for (const [s, d] of g.edgePairs()) if (comps.has(s) && comps.has(d)) { comps.get(s).needs.add(d); comps.get(d).by.add(s); }
  for (const p of files()) for (const d of facts(p).decls) if (['function', 'class', 'method'].includes(d.kind)) { const b = g.at(p, d.first); if (b) comps.get(component(b)).declares.push(d.name); }
  for (const [name, found] of testsReaching(g, comps)) comps.get(name).tests = found;
  for (const [doc, named] of docsNaming(comps)) for (const c of named) comps.get(c).docs.add(doc);
  return comps;
}
function areasOf(comps) {
  const out = new Map();
  for (const name of sortedStr(comps.keys())) { const a = name.split('.')[0]; if (!out.has(a)) out.set(a, []); out.get(a).push(name); }
  return out;
}
function central(comps, untagged) {
  const name = CFG.name || path.basename(ROOT);
  const out = [`# The map of ${name}: the areas, what each needs from the others (read from imports), and where each one's map is.`,
    `# Generated by \`${CMD} build\`; never edit it. \`${CMD} check\` fails when it is out of date.`,
    "# An area's components, what each needs and what needs it: map/<area>.yaml.",
    `# Reading and finding: \`${CMD} brief <words>\`, then \`${CMD} ask <questions>\` (AGENTS.md, "Finding code").`,
    'version: 1', '', 'areas:', '  # needs: how many of its components import a component of that area; needed_by: the other way'];
  const count = (area, mine, key) => {
    const n = new Map();
    for (const c of mine) for (const o of comps.get(c)[key]) { const a = o.split('.')[0]; if (a !== area) n.set(a, (n.get(a) || 0) + 1); }
    return '{' + sortedBy([...n.entries()], ([k, v]) => [-v, k]).map(([k, v]) => `${k}: ${v}`).join(', ') + '}';
  };
  for (const [area, mine] of areasOf(comps)) {
    const nf = new Set(mine.flatMap(c => [...comps.get(c).files])).size, holds = CFG.holds[area];
    out.push(`  ${area}: {` + (holds ? `holds: ${jstr(holds)}, ` : '') + `components: ${mine.length}, files: ${nf}, blocks: ${mine.reduce((s, c) => s + comps.get(c).blocks, 0)}, map: map/${area}.yaml, needs: ${count(area, mine, 'needs')}, needed_by: ${count(area, mine, 'by')}}`);
  }
  if (untagged.length) {
    out.push('', 'untagged:', `  # code files that carry no tag yet, by folder (${CMD} gaps lists them)`);
    const groups = new Map(); for (const p of untagged) { const k = p.includes('/') ? p.slice(0, p.lastIndexOf('/')) + '/' : '.'; groups.set(k, (groups.get(k) || 0) + 1); }
    for (const [folder, n] of sortedBy([...groups.entries()], ([k]) => [k])) out.push(`  ${jstr(folder)}: ${n}`);
  }
  out.push('', 'other:', '  # files without code to read, by folder; each kind described in map.json (describe)');
  const groups = new Map();
  for (const p of sortedStr(new Set([...repoFiles(), 'map.yaml', ...[...areasOf(comps).keys()].map(a => `map/${a}.yaml`)]))) {
    if (!forms(p) || described(p)) { const k = p.includes('/') ? p.split('/')[0] + '/' : '.'; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(p); }
  }
  for (const [folder, paths] of sortedBy([...groups.entries()], ([k]) => [k])) {
    const names = paths.map(p => folder !== '.' ? p.slice(p.indexOf('/') + 1) : p);
    const kinds = new Map();
    for (const p of paths) { const d = described(p); const k = d ? d[1] : (suffixOf(p).replace(/^\./, '') || 'file'); kinds.set(k, (kinds.get(k) || 0) + 1); }
    if (names.length <= 8 || folder === '.') out.push(`  ${jstr(folder)}: [${names.map(jstr).join(', ')}]`);
    else out.push(`  ${jstr(folder)}: {files: ${paths.length}, ` + sortedBy([...kinds.entries()], ([k]) => [k]).map(([k, v]) => `${k}: ${v}`).join(', ') + '}');
  }
  return out.join('\n') + '\n';
}
function zone(area, comps) {
  const li = xs => '[' + sortedStr(xs).join(', ') + ']';
  const holds = CFG.holds[area];
  const out = [`# The ${area} area of the code map` + (holds ? `: ${holds}.` : '.'),
    `# One line per component: what it is, its parts (${CMD} ask <component>.<part>), its files, what it`,
    '# declares, the components it needs (imports) and those that need it, the tests that reach it (by folder)', '# and the docs that name it.',
    `# Generated by \`${CMD} build\`; never edit it. All the areas: map.yaml.`, '', `${area}:`];
  for (const name of areasOf(comps).get(area)) {
    const c = comps.get(name);
    const parts = []; if (c.what) parts.push(`what: ${jstr(c.what)}`); if (c.parts.size) parts.push(`parts: ${li(c.parts)}`);
    parts.push(`files: [${sortedStr(c.files).map(jstr).join(', ')}]`);
    if (c.declares.length) { const seen = unique(c.declares); parts.push(`declares: [${seen.slice(0, 8).join(', ')}` + (seen.length > 8 ? `, … ${seen.length - 8} more]` : ']')); }
    if (c.needs.size) parts.push(`needs: ${li(c.needs)}`); if (c.by.size) parts.push(`needed_by: ${li(c.by)}`);
    if (c.tests.size) { const folders = new Map(); for (const t of c.tests.keys()) { const k = t.includes('/') ? t.split('/')[0] : '.'; folders.set(k, (folders.get(k) || 0) + 1); } parts.push('tests: {' + sortedBy([...folders.entries()], ([k]) => [k]).map(([k, v]) => `${k}: ${v}`).join(', ') + '}'); }
    if (c.docs.size) parts.push(`docs: ${li(c.docs)}`);
    out.push(`  ${name}: {${parts.join(', ')}}`);
  }
  return out.join('\n') + '\n';
}
function written(blocks, comps, untagged) {
  const texts = new Map([[MAP, central(comps, untagged)]]);
  for (const area of areasOf(comps).keys()) texts.set(path.join(ZONES, `${area}.yaml`), zone(area, comps));
  return texts;
}
function build() {
  const [blocks, problems, untagged] = everything();
  const comps = components(blocks, new Graph(blocks));
  const texts = written(blocks, comps, untagged);
  fs.mkdirSync(ZONES, { recursive: true });
  for (const [p, text] of texts) if (!fs.existsSync(p) || fs.readFileSync(p, 'utf8') !== text) fs.writeFileSync(p, text);
  for (const old of fs.readdirSync(ZONES).filter(f => f.endsWith('.yaml'))) if (!texts.has(path.join(ZONES, old))) fs.unlinkSync(path.join(ZONES, old));
  saveCache();
  print(`${blocks.length} blocks in ${new Set(blocks.map(b => b.path)).size} files, ${comps.size} components, ${areasOf(comps).size} areas; ${untagged.length} files without tags; ${problems.length} problems`);
  return problems;
}
function problemsOf() {
  const [blocks, found0, untagged] = everything();
  const found = [...found0];
  if (CFG.strict) for (const p of untagged) found.push([p, 0, 'no blocks: tag this file']);
  const comps = components(blocks, new Graph(blocks));
  for (const [p, text] of written(blocks, comps, untagged)) if (!fs.existsSync(p) || fs.readFileSync(p, 'utf8') !== text) found.push([path.relative(ROOT, p), 0, `out of date: run ${CMD} build`]);
  if (isDir('map')) for (const old of sortedStr(fs.readdirSync(ZONES).filter(f => f.endsWith('.yaml')))) if (!areasOf(comps).has(old.slice(0, -5))) found.push([`map/${old}`, 0, `no such area: run ${CMD} build`]);
  found.push(...recipeProblems(blocks));
  saveCache();
  return [found, blocks.length, untagged.length];
}
// @end map.core.write

// @map map.query.find: find by words or by an identifier, where, gaps, history from git, deps and impact from imports, tests
const identifier = w => /[a-z][A-Z]|[A-Za-z0-9]-[A-Za-z0-9]|_|^[#.][A-Za-z]|^--/.test(w);
const SHOWN = 15;
function find(words0) {
  const [blocks] = everything();
  const raw = words0.flatMap(splitWs);
  const words = raw.filter(x => !identifier(x) || raw.length === 1).map(x => x.toLowerCase());
  let said = false;
  if (raw.length === 1 || raw.some(identifier)) {
    const repo = new Repo(blocks);
    for (const w of raw) if (raw.length === 1 || identifier(w)) for (const d of declarations(repo, w.replace(/^[#.]+/, '')).slice(0, 5)) { print(`${w}: ${d[3]}, declared in ${repo.where(d[0], d[1]) || d[0]}  ${d[0]}:${d[1]}-${d[2]}`); said = true; }
  }
  const has = (text, w) => lowerWords(text).some(h => h.startsWith(w));
  const hit = b => words.every(w => has(b.id + ' ' + b.purpose + ' ' + b.path, w));
  let hits = sortedBy(blocks.filter(b => words.length && hit(b)), b => [-words.filter(w => has(b.id, w)).length, isTest(b.path) ? 1 : 0, -words.filter(w => has(b.purpose, w)).length, b.path, b.first]);
  if (said && raw.length === 1) hits = hits.filter(b => has(b.id, words[0]));
  for (const b of hits.slice(0, SHOWN)) {
    const purpose = b.purpose.length <= 120 ? b.purpose : b.purpose.slice(0, b.purpose.lastIndexOf(' ', 118)) + '…';
    print(`${padR(b.id, 44)} ${b.path}:${b.first}-${b.last} (${b.lines} lines)  ${purpose}`);
  }
  if (hits.length > SHOWN) print(`… ${hits.length - SHOWN} more: add a word to narrow them`);
  if (!hits.length && !said) print(`No block matches. Try fewer words, or the code's text: ${CMD} ask '<text>'`);
}
const matching = (id, blocks) => blocks.filter(b => b.id === id || b.id.startsWith(id + '.'));
function where(id) {
  const hits = matching(id, everything()[0]);
  for (const b of hits) print(`${padR(b.id, 44)} ${b.path}:${b.first}-${b.last} (${b.lines} lines)`);
  if (!hits.length) die(`No block ${id}. Search with: ${CMD} find <words>`);
}
function gaps(paths) {
  const every = files();
  const chosen = paths.length ? every.filter(f => paths.some(p => f === p || f.startsWith(p.replace(/\/+$/, '') + '/'))) : every;
  let untagged = 0, printed = false;
  for (const p of chosen) {
    const f = facts(p);
    const big = f.blocks.filter(b => b.own > LARGEST);
    const elsewhere = sortedStr(new Set(f.blocks.map(b => b.id.split('.')[0]))).filter(a => a !== areaOf(p));
    if (!f.blocks.length) {
      untagged++; printed = true;
      const decls = f.decls.filter(d => ['function', 'class', 'method'].includes(d.kind)).map(d => d.name);
      print(`${p}: no tags (${f.outside.length} lines; area ${areaOf(p)}` + (decls.length ? `; declares ${decls.slice(0, 6).join(', ')}` + (decls.length > 6 ? ' …' : '') : '') + ')');
    } else if (f.outside.length > UNTAGGED || big.length || f.problems.length || elsewhere.length) {
      printed = true;
      print(`${p}: ${f.blocks.length} blocks, ${f.outside.length} lines outside` + (f.outside.length ? ` (from line ${f.outside[0]})` : ''));
      if (elsewhere.length) print(`  note: blocks of ${elsewhere.join(', ')} live in this file`);
      for (const b of big) print(`  split ${b.id} (lines ${b.first}-${b.last}, ${commas(b.own)} characters of its own)`);
      for (const [n, x] of f.problems) print(`  line ${n}: ${x}`);
    }
  }
  saveCache();
  if (untagged) print(`${untagged} of ${chosen.length} files carry no tag: docs/TAGGING.md says how to tag them with an agent`);
  else if (!printed) print(`All ${chosen.length} code files are tagged, no block to split, no problem.`);
}
function git(...args) { try { return spawnSync('git', args, { cwd: ROOT, encoding: 'utf8', maxBuffer: 1 << 26 }).stdout || ''; } catch { return ''; } }
function history(what) {
  const [blocks] = everything();
  let hits = blocks.filter(b => b.id === what); if (!hits.length) hits = matching(what, blocks).slice(0, 3);
  if (!hits.length && isFile(what)) hits = [{ id: what, path: what, first: null }];
  if (!hits.length) die(`No block or file ${what}. Search with: ${CMD} find <words>`);
  for (const b of hits) {
    const out = b.first === null ? git('log', '-n', '12', '--format=%h %ad %s', '--date=short', '--', b.path)
      : git('log', '-s', '-n', '12', '--format=%h %ad %s', '--date=short', `-L${b.first},${b.last}:${b.path}`);
    const lines = out.split('\n').filter(l => l.trim());
    print(`${b.id}  ${b.path}` + (b.first ? `:${b.first}-${b.last}` : '') + `: ${lines.length} commits` + (lines.length ? ', latest first' : ' (not in git, or no history yet)'));
    for (const l of lines) print('  ' + l);
  }
}
function deps(what) {
  const [blocks] = everything(); const g = new Graph(blocks);
  let paths = new Set(matching(what, blocks).map(b => b.path));
  if (!paths.size && (g.fileEdges.has(what) || isFile(what))) paths = new Set([what]);
  if (!paths.size) die(`No block or file ${what}.`);
  for (const p of sortedStr(paths)) {
    const ts = sortedStr(g.fileEdges.get(p) || []);
    print(`${p} imports ${ts.length} files of the repository` + (ts.length ? ':' : ''));
    for (const t of ts) print(`  ${t}  ${g.main.get(t) || ''}`);
  }
}
function reaching(g, paths, names = new Set()) {
  const ps = new Set(paths);
  const direct = new Set(); for (const p of paths) for (const s of g.importers.get(p) || []) if (!ps.has(s)) direct.add(s);
  const second = new Set(); for (const p of direct) for (const s of g.importers.get(p) || []) if (!ps.has(s) && !direct.has(s)) second.add(s);
  const found = new Map();
  for (const t of testFiles()) {
    if (ps.has(t)) found.set(t, 'the test itself');
    else if (direct.has(t)) found.set(t, 'imports ' + sortedStr([...g.fileEdges.get(t)].filter(x => ps.has(x))).slice(0, 2).join(', '));
    else if (second.has(t)) found.set(t, 'imports what imports it');
  }
  const shortNames = new Set([...paths.map(p => p.slice(p.lastIndexOf('/') + 1)).filter(n => n.length > 6), ...names]);
  for (const t of testFiles()) {
    if (found.has(t)) continue;
    let text; try { text = read(t); } catch { continue; }
    if (paths.some(p => text.includes(p)) || [...shortNames].some(n => bounded(text, n, '.', '-'))) found.set(t, 'names it');
  }
  return found;
}
function impact(what) {
  const [blocks] = everything(); const g = new Graph(blocks);
  let mine = new Set(matching(what, blocks).map(b => b.path));
  if (!mine.size && isFile(what)) mine = new Set([what]);
  if (!mine.size) die(`No block or file ${what}.`);
  const direct = new Set(); for (const p of mine) for (const s of g.importers.get(p) || []) if (!mine.has(s)) direct.add(s);
  const second = new Set(); for (const p of direct) for (const s of g.importers.get(p) || []) if (!mine.has(s) && !direct.has(s)) second.add(s);
  print(`${direct.size} files import ${what} directly` + (direct.size ? ':' : '.'));
  for (const p of sortedStr(direct)) print(`  ${p}  ${g.main.get(p) || ''}`);
  if (second.size) print(`${second.size} more import those: ` + sortedStr(second).slice(0, 12).join(', ') + (second.size > 12 ? ' …' : ''));
  const tests = sortedStr(reaching(g, sortedStr(mine), new Set(matching(what, blocks).map(b => component(b.id)))).keys());
  print(`Tests that reach it (${tests.length}): ` + (tests.length ? tests.join(' ') : 'none import or name it; run the suite'));
}
function changed() {
  return git('status', '--porcelain=v1', '-z', '--untracked-files=all').split('\0').filter(e => e.length > 3).map(e => e.slice(3).split('\0')[0]);
}
function tests(args) {
  const paths = (args.length === 1 && args[0] === '--changed') || !args.length ? changed() : args;
  if (!paths.length) { print('Nothing changed: no test to run.'); return; }
  const [blocks] = everything(); const g = new Graph(blocks);
  const chosen = new Map();
  for (const p of sortedStr(paths)) {
    const ids = new Set((g.byFile.get(p) || []).map(b => component(b.id)));
    const found = reaching(g, [p], ids);
    for (const [t, why] of found) if (!chosen.has(t)) chosen.set(t, why);
    print(`  ${p}: ${found.size} test file${found.size !== 1 ? 's' : ''}`);
  }
  if (chosen.size) { print('Run: ' + sortedStr(chosen.keys()).join(' ')); for (const t of sortedStr(chosen.keys())) print(`  ${t}  (${chosen.get(t)})`); }
  else print('No test file imports or names these files.');
}
// @end map.query.find

// @map map.ask.repo: what ask reads (the tagged code and the repository's text), and the block or section holding a line
const MANY = 120, SMALL = 150, LONG = 80, CUT = 240, FEW = 12;
class Repo {
  constructor(blocks) {
    this.blocks = blocks !== undefined ? blocks : everything()[0];
    this.files = repoFiles().filter(p => (TEXT.has(suffixOf(p).toLowerCase()) || forms(p)) && !BINARY.test(p));
    this.known = new Set(this.files);
    this.byFile = new Map(); for (const b of this.blocks) { if (!this.byFile.has(b.path)) this.byFile.set(b.path, []); this.byFile.get(b.path).push(b); }
    this._text = new Map(); this._sections = new Map(); this._decls = null;
  }
  lines(p) {
    if (!this._text.has(p)) { const lines = read(p).split('\n'); if (lines.length > 1 && lines[lines.length - 1] === '') lines.pop(); this._text.set(p, lines); }
    return this._text.get(p);
  }
  holder(p, n) {
    const inside = (this.byFile.get(p) || []).filter(b => b.first <= n && n <= b.last);
    if (!inside.length) return null;
    let best = inside[0]; for (const b of inside) if (b.first > best.first || (b.first === best.first && b.last < best.last)) best = b;
    return best;
  }
  sections(p) {
    if (!this._sections.has(p)) {
      const heads = []; let fence = false;
      this.lines(p).forEach((line, k) => { if (line.startsWith('```')) fence = !fence; else if (!fence) { const m = /^(#{1,6})\s+(.*)/.exec(line); if (m) heads.push([k + 1, m[1].length, m[2].trim()]); } });
      const out = heads.map(([i, level, title], k) => { const nxt = heads.slice(k + 1).find(([, lv]) => lv <= level); return [i, nxt ? nxt[0] - 1 : this.lines(p).length, level, title]; });
      this._sections.set(p, out);
    }
    return this._sections.get(p);
  }
  section(p, n) { const inside = this.sections(p).filter(s => s[0] <= n && n <= s[1]); if (!inside.length) return null; return inside.reduce((a, s) => (s[0] > a[0] ? s : a)); }
  decls() {
    if (!this._decls) {
      this._decls = new Map();
      for (const p of files()) for (const d of facts(p).decls) if (d.kind !== 'heading') { if (!this._decls.has(d.name)) this._decls.set(d.name, []); this._decls.get(d.name).push([p, d.first, d.last, `${d.kind} ${d.name}`, d.what]); }
    }
    return this._decls;
  }
  where(p, a, b = null) {
    if (DOCS.has(suffixOf(p).toLowerCase())) { const s = this.section(p, a); return s ? `${'#'.repeat(s[2])} ${s[3]}` : ''; }
    const ids = []; for (let n = a; n <= (b || a); n++) { const h = this.holder(p, n); if (h && !ids.includes(h.id)) ids.push(h.id); }
    return ids.slice(0, 4).join(', ') + (ids.length > 4 ? ` (+${ids.length - 4})` : '');
  }
}
function relative(q) {
  let p = q.startsWith(ROOT + '/') ? q.slice(ROOT.length + 1) : q;
  if (p.startsWith('./')) p = p.slice(2);
  p = p.replace(/\/+$/, '') || '.';
  return exists(p) && !p.startsWith('..') ? p : null;
}
const within = (p, places) => !places.length || places.some(q => p === q || p.startsWith(q.replace(/\/+$/, '') + '/') || fnmatch(p, q));
const short = (text, most = 110) => text.length <= most ? text : text.slice(0, text.lastIndexOf(' ', most - 2)) + '…';
const put = (lines, a, b) => { for (let i = a; i <= b; i++) print(`${i}\t${lines[i - 1]}`); };
function declarations(repo, word) {
  const out = [...(repo.decls().get(word) || [])];
  if (!out.length && /^[A-Za-z_$][\w$]*$/.test(word)) {
    const rx = new RegExp('(?:\\b(?:const|let|var|val|final|static|export)\\s+|^\\s*)' + escapeRe(word) + '\\s*[:=]');
    for (const p of files()) {
      if (!repo.lines(p).join('\n').includes(word)) continue;
      repo.lines(p).forEach((line, k) => {
        if (out.length >= 6 || /^\s*(#|\/\/|\*)/.test(line)) return;
        const m = rx.exec(line);
        if (m && !(m.index + m[0].length < line.length && '=>'.includes(line[m.index + m[0].length]))) out.push([p, k + 1, k + 1, `value ${word}`, line.trim().slice(0, 120)]);
      });
    }
  }
  return out;
}
// @end map.ask.repo

// @map map.ask.answer: each kind of question answered whole, and the command reading a call's questions
function search(repo, rx, places, skip = []) {
  const hits = [], whole = new RegExp(rx.source, rx.flags.includes('m') ? rx.flags : rx.flags + 'm');
  for (const p of repo.files) {
    if (!within(p, places) || sizeOf(p) > LARGE) continue;
    const lines = repo.lines(p);
    if (!whole.test(lines.join('\n'))) continue;
    lines.forEach((line, k) => { if (rx.test(line) && !skip.some(([sp, a, b]) => sp === p && a <= k + 1 && k + 1 <= b)) hits.push([p, k + 1, line]); });
  }
  return hits;
}
function searchWord(repo, word, places, skip = [], hyphen = false) {
  const hits = [], edge = hyphen ? '-' : '';
  for (const p of repo.files) {
    if (!within(p, places) || sizeOf(p) > LARGE) continue;
    const lines = repo.lines(p);
    if (!lines.join('\n').includes(word)) continue;
    lines.forEach((line, k) => { if (line.includes(word) && bounded(line, word, edge, edge) && !skip.some(([sp, a, b]) => sp === p && a <= k + 1 && k + 1 <= b)) hits.push([p, k + 1, line]); });
  }
  return hits;
}
function showHits(repo, hits, every, numbers = false) {
  const places = new Map();
  for (const [p, i, line] of hits) {
    const b = repo.holder(p, i); let key, label;
    if (b) { key = `${p}\u0000${b.id}\u0000${b.first}`; label = `${b.id}  ${p}:${b.first}-${b.last}  ${short(b.purpose)}`; }
    else { const s = DOCS.has(suffixOf(p).toLowerCase()) ? repo.section(p, i) : null; if (s) { key = `${p}\u0000${s[0]}`; label = `${p}:${s[0]}-${s[1]}  ${'#'.repeat(s[2])} ${s[3]}`; } else { key = p; label = p; } }
    if (!places.has(key)) places.set(key, [label, []]);
    places.get(key)[1].push([i, line]);
  }
  if (hits.length > MANY && !every) {
    print(`  ${hits.length} lines in ${places.size} places; the places (their lines: --all, or --in <file, folder or glob>)`);
    for (const [label, found] of [...places.values()].slice(0, 60)) print(`    ${label}  (${found.length} lines)`);
    if (places.size > 60) print(`    … ${places.size - 60} more places`);
    return;
  }
  for (const [label, found] of places.values()) {
    if (numbers) { print(`    ${label}: ${found.map(([i]) => i).join(', ')}`); continue; }
    print(`  ${label}`);
    for (const [i, line] of found) print(`${i}\t${line.length <= CUT ? line : line.slice(0, CUT) + ` …(+${line.length - CUT})`}`);
  }
}
function answerLines(repo, p, a, b) {
  const lines = repo.lines(p); let label;
  if (b === null) {
    const h = repo.holder(p, a), s = DOCS.has(suffixOf(p).toLowerCase()) ? repo.section(p, a) : null;
    if (h) { a = h.first; b = h.last; label = `${h.id}: ${h.purpose}`; } else if (s) { a = s[0]; b = s[1]; label = `${'#'.repeat(s[2])} ${s[3]}`; } else { b = a + 15; a = Math.max(1, a - 15); label = ''; }
  } else label = repo.where(p, a, b);
  a = Math.max(1, a); b = Math.min(lines.length, b);
  print(`  ${p}:${a}-${b}` + (label ? `  ${label}` : ''));
  put(lines, a, b);
}
function answerFile(repo, p) {
  const lines = repo.lines(p), suffix = suffixOf(p).toLowerCase();
  if (sizeOf(p) > LARGE) print(`  ${p}: ${lines.length} lines, ${commas(sizeOf(p))} bytes: data, not printed (ask ${p}:<first>-<last>)`);
  else if (lines.length <= SMALL) { print(`  ${p}: ${lines.length} lines, whole`); put(lines, 1, lines.length); }
  else if (DOCS.has(suffix) && repo.sections(p).length) {
    print(`  ${p}: ${lines.length} lines; its sections (one: ask ${p}#<words of its heading>)`);
    for (const [first, last, level, title] of repo.sections(p)) print(`${padL(first, 6)}-${padR(last, 6)}${'  '.repeat(level - 1)}${'#'.repeat(level)} ${title}`);
  } else if (suffix === '.json') {
    let data = null; try { data = JSON.parse(lines.join('\n')); } catch { data = null; }
    if (data && typeof data === 'object') {
      print(`  ${p}: ${lines.length} lines; its keys (one: ask ${p}#<key>)`);
      const items = Array.isArray(data) ? data.map((v, i) => [i, v]) : Object.entries(data);
      for (const [k, v] of items) {
        const sub = v && typeof v === 'object' && !Array.isArray(v) ? ` {${Object.keys(v).slice(0, 8).join(', ')}${Object.keys(v).length > 8 ? ', …' : ''}}` : '';
        print(`    ${k}: ${pyType(v)}, ${commas(jdump(v).length)} characters${sub}`);
      }
    } else { print(`  ${p}: ${lines.length} lines; the first ${SMALL} (more: ask ${p}:<first>-<last>)`); put(lines, 1, SMALL); }
  } else if (repo.byFile.has(p)) {
    const named = new Map();
    if (forms(p)) for (const d of facts(p).decls) if (['function', 'class', 'method'].includes(d.kind)) { const h = repo.holder(p, d.first); if (h) { if (!named.has(h.id)) named.set(h.id, []); named.get(h.id).push(d.name); } }
    print(`  ${p}: ${lines.length} lines; its blocks (one: ask <id>, or ${p}:<first>-<last>)`);
    const outer = [];
    for (const b of sortedBy(repo.byFile.get(p), b => [b.first, -b.last])) {
      while (outer.length && outer[outer.length - 1] < b.first) outer.pop();
      const ns = named.get(b.id) || [];
      print(`${padL(b.first, 6)}-${padR(b.last, 6)}${'  '.repeat(outer.length)}${b.id}  ${short(b.purpose)}` + (ns.length ? `  [${ns.slice(0, 8).join(', ')}${ns.length > 8 ? ' …' : ''}]` : ''));
      outer.push(b.last);
    }
  } else if (forms(p) && facts(p).decls.some(d => d.kind !== 'heading')) {
    const decls = facts(p).decls;
    print(`  ${p}: ${lines.length} lines, no tags yet; what it declares (one: ask <name>, or ${p}:<first>-<last>)`);
    for (const d of decls.slice(0, 80)) print(`${padL(d.first, 6)}-${padR(d.last, 6)}${d.kind} ${d.name}  ${short(d.what, 90)}`);
    if (decls.length > 80) print(`    … ${decls.length - 80} more`);
  } else { print(`  ${p}: ${lines.length} lines; the first ${SMALL} (more: ask ${p}:<first>-<last>)`); put(lines, 1, SMALL); }
}
const pyType = v => v === null ? 'NoneType' : Array.isArray(v) ? 'list' : typeof v === 'object' ? 'dict' : typeof v === 'string' ? 'str' : typeof v === 'boolean' ? 'bool' : Number.isInteger(v) ? 'int' : 'float';
function answerFiles(repo, paths, about) {
  print(`  ${about}: ${paths.length} files`);
  for (const p of paths) {
    const bs = repo.byFile.get(p) || []; const first = bs.length ? bs.reduce((a, b) => (b.first < a.first ? b : a)) : null;
    const heads = DOCS.has(suffixOf(p).toLowerCase()) ? repo.sections(p) : [];
    const what = first ? short(first.purpose, 90) : (heads.length ? heads[0][3] : '');
    print(`    ${p}  (${repo.lines(p).length} lines)  ${what}`);
  }
}
function answerFolder(repo, p) {
  const base = p === '.' ? '' : p.replace(/\/+$/, '') + '/';
  const under = repo.files.filter(x => x.startsWith(base));
  const here = under.filter(x => !x.slice(base.length).includes('/'));
  const folders = new Map(); for (const x of under) if (x.slice(base.length).includes('/')) { const f = x.slice(base.length).split('/')[0]; folders.set(f, (folders.get(f) || 0) + 1); }
  answerFiles(repo, here, p);
  for (const [f, n] of sortedBy([...folders.entries()], ([k]) => [k])) print(`    ${base}${f}/  (${n} files)`);
}
function answerPart(repo, p, words) {
  const ws = lowerWords(words);
  const has = text => ws.every(w => lowerWords(text).some(t => t.startsWith(w)));
  if (p.endsWith('.json')) {
    try {
      let data = JSON.parse(repo.lines(p).join('\n'));
      for (const k of words.split('.')) { if (Array.isArray(data)) { const i = Number(k); if (!Number.isInteger(i) || i < 0 || i >= data.length) return false; data = data[i]; } else if (data && typeof data === 'object' && k in data) data = data[k]; else return false; }
      print(`  ${p}#${words}`); print(jdump(data, 1)); return true;
    } catch { return false; }
  }
  if (DOCS.has(suffixOf(p).toLowerCase())) {
    const found = repo.sections(p).filter(s => has(s[3]));
    for (const [first, last, level, title] of found) { print(`  ${p}:${first}-${last}  ${'#'.repeat(level)} ${title}`); put(repo.lines(p), first, last); }
    return found.length > 0;
  }
  const found = (repo.byFile.get(p) || []).filter(b => has(b.id + ' ' + b.purpose));
  for (const b of found) { print(`  ${p}:${b.first}-${b.last}  ${b.id}: ${b.purpose}`); put(repo.lines(p), b.first, b.last); }
  return found.length > 0;
}
function answerBlock(repo, q) {
  const exact = repo.blocks.filter(b => b.id === q), inside = repo.blocks.filter(b => b.id.startsWith(q + '.'));
  if (exact.length) {
    for (const b of exact) {
      const nested = repo.byFile.get(b.path).filter(x => x !== b && b.first <= x.first && x.last <= b.last);
      print(`  ${b.path}:${b.first}-${b.last}  ${b.id}: ${b.purpose}`);
      if (b.last - b.first + 1 > SMALL && nested.length) {
        print(`  ${b.last - b.first + 1} lines; the blocks inside it (one: ask <id>, or ${b.path}:<first>-<last>)`);
        for (const x of nested) print(`${padL(x.first, 6)}-${padR(x.last, 6)}${x.id}  ${short(x.purpose)}`);
      } else put(repo.lines(b.path), b.first, b.last);
    }
  } else if (inside.length <= 60) {
    print(`  ${inside.length} blocks under ${q} (one: ask <id>)`);
    for (const b of inside) print(`    ${padR(b.id, 44)} ${b.path}:${b.first}-${b.last}  ${short(b.purpose)}`);
  } else {
    const parts = new Map();
    for (const b of inside) { const k = b.id.split('.').slice(0, q.split('.').length + 1).join('.'); if (!parts.has(k)) parts.set(k, []); parts.get(k).push(b); }
    print(`  ${inside.length} blocks under ${q}, in ${parts.size} parts (one: ask <id>)`);
    for (const [part, bs] of parts) print(`    ${padR(part, 40)} ${padL(bs.length, 3)} blocks  ${sortedStr(new Set(bs.map(b => b.path))).join(', ').slice(0, 80)}  ${short(bs[0].purpose, 70)}`);
  }
}
function answerName(repo, q, places, every) {
  const word = q.startsWith('--') ? q : q.replace(/^[#.]+/, '');
  const decls = /^[A-Za-z_$][\w$]*$/.test(word) ? declarations(repo, word) : [];
  if (decls.length > 3) print(`  declared in ${decls.length} places (the code of one: ask <file>:<first>-<last>)`);
  for (const [p, first, last, what] of decls) {
    print(`  ${what}: ${p}:${first}-${last}  in ${repo.where(p, first) || p}`);
    if (decls.length <= 3 && last - first < LONG) put(repo.lines(p), first, last);
    else if (decls.length <= 3) { put(repo.lines(p), first, first + 11); print(`  … ${last - first - 11} more lines: ask ${p}:${first + 12}-${last}`); }
  }
  const hyphen = word.includes('-') || q.startsWith('--') || !isAlnum(word[0] || '');
  const hits = searchWord(repo, word, places, decls.map(([p, a, b]) => [p, a, b]), hyphen);
  if (hits.length) { print(decls.length ? `  named on ${hits.length} other lines` : `  on ${hits.length} lines`); showHits(repo, hits, every, hits.length > FEW && !every); }
  return decls.length > 0 || hits.length > 0;
}
const DECLARED = /^\^?\s*(?:(?:export|async|static|pub|public|private)\s+)*(?:function\*?|def|fn|func|class|const|let|var|val)\s+([A-Za-z_$][\w$]*)\b.*$|^(?:global\.|window\.|\.)?([A-Za-z_$][\w$]*)\s*(?:\\?\(|=)\s*$/;
function namesIn(q) {
  const out = [];
  for (const alt of q.split(/\\\||\|/)) { const m = DECLARED.exec(alt.trim()); if (!m) return []; out.push(m[1] || m[2]); }
  return unique(out);
}
const unescapedPipe = q => [...q].some((c, i) => c === '|' && (i === 0 || q[i - 1] !== '\\'));
function answerText(repo, q, places, every) {
  if (q.includes('\\|') && !unescapedPipe(q)) q = q.split('\\|').join('|');
  let rx; try { rx = new RegExp(q); } catch { rx = new RegExp(escapeRe(q)); }
  const hits = search(repo, rx, places);
  if (hits.length) { showHits(repo, hits, every); return true; }
  if (q.trim().includes(' ')) { print('  no line holds it; the blocks whose id, purpose or file have these words:'); find(splitWs(q)); return true; }
  return false;
}
function ask(args) {
  const every = args.includes('--all');
  const questions = []; let waiting = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--in' && i + 1 < args.length) { const places = args[i + 1].split(',').filter(x => x).map(x => relative(x) || x.replace(/^[./]+/, '')); for (const q of waiting) questions.push([q, places]); waiting = []; i++; continue; }
    if (args[i] !== '--all') waiting.push(args[i]);
  }
  for (const q of waiting) questions.push([q, []]);
  if (!questions.length) die(USAGE);
  const repo = new Repo();
  const ids = new Set(repo.blocks.map(b => b.id));
  for (const [q, places] of questions) {
    print(`== ${q}`);
    const m = /^(.+?):(\d+)(?:-(\d+))?$/.exec(q);
    let p = m ? relative(m[1]) : null;
    if (p && isFile(p)) { answerLines(repo, p, Number(m[2]), m[3] ? Number(m[3]) : null); continue; }
    const hash = q.indexOf('#'); const head = hash >= 0 ? q.slice(0, hash) : q, part = hash >= 0 ? q.slice(hash + 1) : '';
    p = part && head ? relative(head) : null;
    if (p && isFile(p)) { if (!answerPart(repo, p, part)) { print(`  nothing in ${p} is called "${part}"; its outline:`); answerFile(repo, p); } continue; }
    p = relative(q);
    if (p && isFile(p)) answerFile(repo, p);
    else if (p && isDir(p)) answerFolder(repo, p);
    else if (/[*?]/.test(q) && q.includes('/') && !/[\\|()+^$]/.test(q)) answerFiles(repo, repo.files.filter(x => fnmatch(x, q.replace(/^[./]+/, ''))), q);
    else if (namesIn(q).length) { const ns = namesIn(q); for (const name of ns) { print(ns.length > 1 ? `  ${name}:` : `  the name ${name}`); if (!answerName(repo, name, places, every)) print('  nothing in the code or the docs holds it'); } }
    else if (ids.has(q) || [...ids].some(x => x.startsWith(q + '.'))) answerBlock(repo, q);
    else if ((identifier(q) || /^[A-Za-z_$][\w$]*$/.test(q)) && answerName(repo, q, places, every)) { /* answered */ }
    else if (!answerText(repo, q, places, every)) print('  nothing in the code or the docs holds it');
  }
  saveCache();
}
// @end map.ask.answer

// @map map.brief.print: where a task starts: the components its words name, ranked, each with its parts, declarations, relations, tests, docs and commits
const STOP = new Set('a an and are as at be by can do does for from has have how i in into is it its me my new of on or our should so that the their them then there these this to us was we what when where which who why will with add change changes make fix use using want need needs'.split(' '));
const wordsIn = args => lowerWords(args.join(' ')).filter(w => !STOP.has(w) && w.length > 1);
function ranked(blocks, g, words) {
  const names = new Map();
  for (const p of files()) for (const d of facts(p).decls) if (d.kind !== 'heading') { const b = g.at(p, d.first); if (b) { if (!names.has(b)) names.set(b, new Set()); for (const w of wordsOf(d.name)) names.get(b).add(w); } }
  const seen = new Map();
  for (const b of blocks) seen.set(b.id + '\u0000' + b.path, [b, { id: wordsOf(b.id), purpose: new Set(lowerWords(b.purpose)), other: new Set([...lowerWords(b.path), ...(names.get(b.id) || [])]) }]);
  const has = (pool, w) => [...pool].some(h => h.startsWith(w) || (w.length > 3 && w.endsWith('s') && h.startsWith(w.slice(0, -1))));
  const df = new Map(); for (const w of words) df.set(w, [...seen.values()].filter(([, p]) => has(new Set([...p.id, ...p.purpose, ...p.other]), w)).length);
  const out = [];
  for (const [b, p] of seen.values()) {
    let s = 0;
    for (const w of words) { const weight = has(p.id, w) ? 3 : has(p.purpose, w) ? 2 : has(p.other, w) ? 1 : 0; s += weight * Math.log(1 + seen.size / (1 + df.get(w))); }
    if (s) out.push([round9(s - (isTest(b.path) ? 0.5 : 0)), b]);
  }
  return sortedBy(out, ([s, b]) => [-s, b.path, b.first]);
}
const round9 = x => Math.round(x * 1e9) / 1e9;
function brief(args) {
  const words = wordsIn(args);
  if (!words.length) die('Say the task in a few words, as the code names things: brief cart totals discount');
  const [blocks, , untagged] = everything(); const g = new Graph(blocks); const comps = components(blocks, g);
  const hits = ranked(blocks, g, words);
  const per = new Map();
  for (const [s, b] of hits) if (!isTest(b.path)) { const c = component(b.id); if (!per.has(c)) per.set(c, []); per.get(c).push([s, b]); }
  const score = new Map(); for (const [c, xs] of per) score.set(c, round9(sortedBy(xs, ([s]) => [-s]).slice(0, 3).reduce((t, [s], i) => t + s * [1, 0.5, 0.25][i], 0)));
  const order = sortedBy([...score.keys()], c => [-score.get(c)]);
  if (!order.length) die(`No block matches those words. Try others, or ${CMD} find <word>.`);
  const near = order.filter(c => score.get(c) >= 0.25 * score.get(order[0])).slice(0, 10);
  const chosen = near.slice(0, 3), also = near.slice(3);
  print(`brief ${words.join(' ')}: ${near.length} of ${order.length} components that match, best first. ask <id or name> reads a block.`);
  for (const c of chosen) {
    const info = comps.get(c), fs_ = sortedStr(info.files);
    print(`\n${c}  ${short(info.what || '', 100)}  [${fs_.slice(0, 4).join(', ')}${fs_.length > 4 ? ' …' : ''}]`);
    const best = new Map();
    for (const [, b] of sortedBy(per.get(c), ([s]) => [-s])) { if (!best.has(b.id)) best.set(b.id, [b, 0]); best.get(b.id)[1]++; }
    [...best.values()].slice(0, chosen.indexOf(c) < 2 ? 5 : 3).forEach(([b, n], i) => print(`  ${i ? '      ' : 'parts:'} ${b.id} ${b.path}:${b.first}-${b.last}${n > 1 ? ` (+${n - 1} files)` : ''} — ${short(b.purpose, 70)}`));
    const decl = unique(info.declares);
    if (decl.length) { const about = decl.filter(d => [...wordsOf(d)].some(h => words.some(w => h.startsWith(w)))); const shown = [...about, ...decl.filter(d => !about.includes(d))].slice(0, 8); print(`  declares (${decl.length}): ${shown.join(', ')}` + (decl.length > 8 ? ' …' : '')); }
    const near_ = sortedStr(info.needs).slice(0, 5).join(', ') + (info.needs.size > 5 ? ' …' : ''), by = sortedStr(info.by).slice(0, 5).join(', ') + (info.by.size > 5 ? ' …' : '');
    if (near_ || by) print(`  needs (imports): ${near_ || '—'}; needed by: ${by || '—'}`);
    const ts = sortedStr(info.tests.keys());
    print(`  tests (${ts.length}): ` + (ts.length ? ts.slice(0, 6).join(' ') + (ts.length > 6 ? ' …' : '') : 'none import or name it'));
    if (info.docs.size) print(`  docs: ${sortedStr(info.docs).slice(0, 5).join(', ')}`);
    for (const ln of git('log', '-n', '2', '--format=%ad %h %s', '--date=short', '--', ...fs_).split('\n').filter(x => x.trim())) print(`  changed ${short(ln, 110)}`);
  }
  if (also.length) print('\nalso:');
  for (const c of also) { const b = sortedBy(per.get(c), ([s]) => [-s])[0][1]; print(`${c}  ${b.id} ${b.path}:${b.first}-${b.last} — ${short(b.purpose, 70)}; ${comps.get(c).tests.size} tests`); }
  const checks = hits.filter(([, b]) => isTest(b.path)).slice(0, 3);
  if (checks.length) print('tests that say it: ' + checks.map(([, b]) => `${b.id} ${b.path}:${b.first}-${b.last}`).join('; '));
  for (const [name, about] of recipesMatching(words)) print(`recipe ${name}: ${about} (${CMD} recipe ${name})`);
  if (untagged.length) print(`${untagged.length} files carry no tag yet (${CMD} gaps): ask <file> gives their declarations`);
  const first = unique(hits.filter(([, b]) => !isTest(b.path)).map(([, b]) => b.id)).slice(0, 4);
  if (first.length) print(`Next, one call for the whole first round (add every other question to it): ${CMD} ask ` + first.join(' '));
  print(`End each change with: ${CMD} check`);
  saveCache();
}
// @end map.brief.print

// @map map.recipes.steps: recipes from map.json, the steps of a change across layers, each checked against a block that still exists; plans whose parts can run at once
function recipe(name) {
  const rs = CFG.recipes;
  if (!name || !(name in rs)) {
    if (name) print(`No recipe ${name}.`);
    for (const [key, r] of Object.entries(rs)) print(`${padR(key, 15)} ${r.about || ''}`);
    if (!Object.keys(rs).length) print('No recipes in map.json yet (docs/CONFIG.md says how to write one).');
    return;
  }
  const r = rs[name], at = new Map();
  for (const b of sortedBy(everything()[0], b => [b.path])) if (!at.has(b.id)) at.set(b.id, `${b.path}:${b.first}-${b.last}`);
  print(`${name}: ${r.about || ''}.` + (r.checked ? ` Checked against ${r.checked}.` : ''));
  (r.steps || []).forEach(([target, what], i) => print(`${i + 1}. ${target}  ${at.get(target) || ''}`.trimEnd() + `\n   ${what}`));
  if (r.note) print(`Note: ${r.note}`);
}
function recipesMatching(words) {
  const out = [];
  for (const [key, r] of Object.entries(CFG.recipes)) { const mine = new Set([...splitWs(String(r.words || '')), ...key.split('-')]); if (words.filter(w => mine.has(w)).length >= 2) out.push([key, r.about || '']); }
  return out;
}
function recipeProblems(blocks) {
  const ids = new Set(blocks.map(b => b.id)), out = [];
  for (const [key, r] of Object.entries(CFG.recipes)) for (const [target] of r.steps || []) {
    if (target.includes('/') || target.endsWith('.md') || target.endsWith('.txt')) { if (!exists(target)) out.push(['map.json', 0, `recipe ${key} names ${target}, which is not in the repository`]); }
    else if (!ids.has(target)) out.push(['map.json', 0, `recipe ${key} names the block ${target}, which no file tags: find where it went (${CMD} find …)`]);
  }
  return out;
}
const SHARED = ['map/', 'map.yaml', 'CHANGELOG', 'changes/', 'docs/plans/'];
function plan(p) {
  const text = fs.readFileSync(p, 'utf8');
  const parts = []; let current = null;
  for (const line of text.split('\n')) {
    let m = /^## Part (\d+)\b[:.\s-]*(.*)/.exec(line);
    if (m) { current = [Number(m[1]), m[2].trim(), new Set()]; parts.push(current); }
    else if (line.startsWith('## ')) current = null;
    else if (current && (m = /^\s*-\s*Files:(.*)/.exec(line))) for (const w of m[1].split(/[\s,]+/)) { const x = w.replace(/^[`*,;:()[\]]+|[`*,;:()[\]]+$/g, '').replace(/\.+$/, ''); if (x && (x.includes('/') || isFile(x))) current[2].add(x); }
  }
  if (!parts.length) die(`${p}: no "## Part <n>: …" sections with a "- Files:" line each`);
  const g = new Graph(everything()[0]);
  print(`${p}: ${parts.length} parts`);
  const apart = [];
  parts.forEach((a, i) => {
    for (const b of parts.slice(i + 1)) {
      const common = sortedStr([...a[2]].filter(f => b[2].has(f) && !SHARED.some(s => f.startsWith(s))));
      let why = common.length ? 'both change ' + common.join(', ') : null;
      if (!why) for (const [x, y] of [[a, b], [b, a]]) { for (const f of sortedStr(x[2])) if ([...(g.fileEdges.get(f) || [])].some(t => y[2].has(t))) { why = `part ${x[0]} imports what part ${y[0]} changes (${f})`; break; } if (why) break; }
      print(`  ${a[0]} and ${b[0]}: ` + (why ? `one after the other: ${why}` : 'at once'));
      if (!why) apart.push([a[0], b[0]]);
    }
  });
  if (apart.length) print('At once: ' + apart.map(([a, b]) => `${a} with ${b}`).join(', ') + ' (each agent in a worktree of its own: git worktree add ../<name>-<part> -b <branch>)');
  else print('No two parts can run at once: one agent after another, in order.');
}
// @end map.recipes.steps

// @map map.cli.init: init: the areas detected, map.json written, the section for AGENTS.md printed; and the command line
const AGENTS_SECTION = `## Finding code

Every block of code carries a tag naming it (\`@map <area>.<topic>.<part>: what it does\`), and the map is read
from the tags and the code: \`map.yaml\` (the areas and what each needs from the others) and \`map/<area>.yaml\`
(each area's components). The map, not grep, is how this repository is read. Every call of an agent re-reads the
whole conversation, so questions go in rounds: every question of a round in one call, each answered whole.

1. **Start with \`{cmd} brief <the task's words>\`**, as the code names things: the components
   the words name, their blocks and lines, what they declare, need and are needed by, their tests, docs and
   latest commits; then the first round of questions, as one call.
2. **Then one \`ask\` for each round of questions.** Write down every question the brief leaves open and ask them
   together; a later round asks only what the answers opened:
   \`{cmd} ask <question> [<question> …] [--in <paths>] [--all]\` reads and locates everything:
   a block id (its code), an identifier (what it is, the code declaring it, every line naming it), a file (whole,
   or its outline), a folder, \`src/x.js:120-180\`, \`docs/X.md#heading\`, \`data.json#key\`, \`'src/**/*.css'\`, or any
   text (every line holding it, by block or section). \`--in\` narrows the questions before it.
   Beside \`ask\`: \`find <words>\`, \`history <id>\` (its commits), \`deps\` and \`impact <id or file>\` (imports, and
   the tests to run), \`recipe [name]\` (the steps of a change across layers).
3. **Do not read or search the code and the docs with \`grep\`, \`rg\`, \`sed\`, \`cat\`, \`head\`, \`tail\`, \`ls\`, \`find\`,
   with a script that only prints them, or with a file-reading tool on whole files**: \`ask\` answers the same
   question, by block, with the code. Counting, computing over data, editing and other files go ahead; so does a
   range of lines before an edit.
4. **Tag what you add or move** (\`docs/TAGGING.md\`): a tag on the line above each block, in the file's comment form,
   \`@end <id>\` when other code follows it; keep purposes true. **End each change with \`{cmd} check\`**, which also
   checks that the map is current (\`{cmd} build\` writes it again).
`;
function init(args) {
  const counts = new Map(); for (const p of files()) { const a = areaOf(p); counts.set(a, (counts.get(a) || 0) + 1); }
  const untagged = files().filter(p => !facts(p).blocks.length);
  print(`Root: ${ROOT} (--root <path> or MAP_ROOT names another)`);
  if (!isFile('map.json') || args.includes('--force')) {
    const cfg = { command: CMD, holds: Object.fromEntries(mostCommon(counts).map(([a]) => [a, ''])) };
    if (files().some(p => areaOf(p) === 'root')) cfg.areas = { '.': 'root' };
    fs.writeFileSync(path.join(ROOT, 'map.json'), jdump(cfg, 2) + '\n');
    print(`map.json written: ${counts.size} areas detected, each with an empty "holds" to fill in (one line: what the area holds).`);
  } else print('map.json is there already (--force writes it again).');
  print('Areas (code files each): ' + mostCommon(counts).map(([a, n]) => `${a} ${n}`).join(', '));
  print(`${files().length} code files, ${files().length - untagged.length} tagged, ${untagged.length} without tags yet.`);
  print('');
  print(`Next: 1. tag the code (docs/TAGGING.md; ${CMD} gaps lists what is left), 2. ${CMD} build, 3. paste this in AGENTS.md`);
  print('(CLAUDE.md imports it with a line "@AGENTS.md"), 4. install the guard: python3 tools/map-guard.py install <agent>.');
  print('');
  print(AGENTS_SECTION.split('{cmd}').join(CMD));
  saveCache();
}
const USAGE = `The code map: a map of the areas (map.yaml) and of each area's components (map/<area>.yaml), read from the tags
in the code; what agents ask it instead of grepping. Start a task with brief, read with ask, end each change with check.

    {cmd} build            write map.yaml (the areas) and map/<area>.yaml (each area's components)
    {cmd} check            the rules, and that the map matches the code (for CI); exit 1 when not
    {cmd} brief <words>    where a task starts: the components the words name, their blocks and lines, what
                                they declare, need and are needed by, their tests, docs and latest commits, then
                                the first round of questions to ask, in one call
    {cmd} ask <question> [<question> …] [--in <paths>] [--all]
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
tool exists in Python, Node, Go and Rust, with the same answers (tests/conformance.py).`.split('{cmd}').join(CMD);
function main() {
  const [command, ...rest] = ARGV.length ? ARGV : ['check'];
  const queries = { deps, impact, history, where };
  if (command === 'find' && rest.length) find(rest);
  else if (command in queries && rest.length === 1) queries[command](rest[0]);
  else if (command === 'ask' && rest.length) ask(rest);
  else if (command === 'brief' && rest.length) brief(rest);
  else if (command === 'tests') tests(rest);
  else if (command === 'recipe' && rest.length <= 1) recipe(rest[0]);
  else if (command === 'plan' && rest.length === 1) plan(rest[0]);
  else if (command === 'gaps') gaps(rest);
  else if (command === 'init') init(rest);
  else if (command === 'build') { const found = build(); for (const [p, n, x] of found) print(n ? `${p}:${n}: ${x}` : `${p}: ${x}`); flush(); process.exit(found.length ? 1 : 0); }
  else if (command === 'check') { const [found, nBlocks, nUntagged] = problemsOf(); for (const [p, n, x] of found) print(n ? `${p}:${n}: ${x}` : `${p}: ${x}`); print(`${nBlocks} blocks, ${found.length} problems` + (nUntagged ? `, ${nUntagged} files without tags (${CMD} gaps)` : '')); flush(); process.exit(found.length ? 1 : 0); }
  else if (['help', '-h', '--help'].includes(command)) print(USAGE);
  else if (['version', '--version'].includes(command)) print(VERSION);
  else die(USAGE);
  flush();
}
main();
// @end map.cli.init
