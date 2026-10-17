#!/usr/bin/env node
// @map map.guard.scope: what the map reads (the code and the docs of the repository), how a command's paths resolve, and the agents' hook formats
// map-guard: a pre-tool hook that keeps agents reading the code and the docs through the map. The Node version of
// python/map-guard.py: the same refusals, the same asks, the same five agents (tests/conformance.py checks them).
//   node tools/map-guard.mjs [--agent claude|codex|cursor|copilot|gemini]   stdin in, the decision out
//   node tools/map-guard.mjs install <agent>  |  node tools/map-guard.mjs try '<shell line>'
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

function findRoot() {
  if (process.env.MAP_ROOT) return realpath(process.env.MAP_ROOT);
  const here = path.dirname(fs.realpathSync(process.argv[1]));
  for (const start of [process.cwd(), here]) for (const mark of ['map.json', '.git']) {
    let base = start;
    for (;;) { if (fs.existsSync(path.join(base, mark))) return base; const up = path.dirname(base); if (up === base) break; base = up; }
  }
  return process.cwd();
}
function realpath(p) {
  const full = path.resolve(p);
  try { return fs.realpathSync.native(full); } catch { /* not there: resolve what exists */ }
  let base = full, rest = [];
  while (!fs.existsSync(base)) { rest.unshift(path.basename(base)); const up = path.dirname(base); if (up === base) return full; base = up; }
  try { return path.join(fs.realpathSync.native(base), ...rest); } catch { return full; }
}
const ROOT = findRoot();
let CFG = {};
try { CFG = JSON.parse(fs.readFileSync(path.join(ROOT, 'map.json'), 'utf8')); } catch { CFG = {}; }
const ASK = (CFG.command || 'python3 tools/map.py') + ' ask ';
const SKIPPED = [...((CFG.guard || {}).skip || []), ...(CFG.ignore || [])];
const TEXT = new Set([...('.js .mjs .cjs .jsx .ts .tsx .mts .cts .java .kt .kts .scala .groovy .go .rs .swift .c .h .cc .cpp .cxx .hpp .hh .cs .m .mm .php .dart '
  + '.css .scss .less .proto .zig .d .v .py .pyi .rb .rake .sh .bash .zsh .fish .pl .pm .r .R .yml .yaml .toml .ps1 .ex .exs .nim .jl .cmake .tf .nix .cr '
  + '.coffee .mk .html .htm .xml .vue .svelte .astro .xhtml .sql .lua .hs .elm .ada .vhd .clj .cljs .cljc .edn .el .lisp .scm .rkt .erl .hrl .tex .md '
  + '.markdown .rst .txt .adoc .json .ini .cfg .csv .editorconfig').split(' '), ...Object.keys(CFG.forms || {})]);
const NAMED = new Set(['Makefile', 'GNUmakefile', 'Dockerfile', 'Containerfile', 'Rakefile', 'Gemfile', 'Justfile', 'Vagrantfile', 'CMakeLists.txt', 'Jenkinsfile']);
const SKIP = new Set(['node_modules', 'dist', 'build', 'out', 'target', 'vendor', 'venv', '.venv', '__pycache__', '.git', '.hg', '.svn', '.tox', '.mypy_cache',
  '.pytest_cache', '.cache', 'coverage', '.idea', '.vscode', 'bower_components', '.next', '.nuxt', '.terraform', 'Pods', 'DerivedData', 'map']);
const SEARCH = new Set(['grep', 'egrep', 'fgrep', 'rg', 'ag', 'ack']);
const READ = new Set(['cat', 'sed', 'head', 'tail', 'awk', 'nl', 'less', 'more', 'bat', 'cut', 'strings', 'xxd', 'od', 'perl', 'ruby']);
const LIST = new Set(['ls', 'find', 'tree', 'fd']);
const FILTERS = new Set(['head', 'tail', 'cut', 'grep', 'egrep', 'sort', 'uniq', 'wc', 'sed', 'awk', 'tr', 'column']);
const REASON = "This repository's code and docs are read and located through its map, every question of a round in one call "
  + '(AGENTS.md, "Finding code"); it answers what this would, by block, with the code. None of this command ran: send its other steps again. Run instead:\n  ';
const escapeRe = s => s.replace(/[.*+?^${}()|[\]\\\/-]/g, '\\$&');
const expanduser = p => p.startsWith('~') ? path.join(os.homedir(), p.slice(1)) : p;

function inside(p, base) {
  const full = realpath(path.resolve(base, expanduser(p)));
  const rel = path.relative(ROOT, full);
  return rel.startsWith('..') ? null : (rel === '' ? '.' : rel);
}
let IGNORED = null;
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
function ignored(rel) {
  if (!IGNORED) {
    let lines = []; try { lines = fs.readFileSync(path.join(ROOT, '.gitignore'), 'utf8').split('\n'); } catch { lines = []; }
    IGNORED = [...lines.map(l => l.trim()).filter(l => l && !l.startsWith('#')), ...SKIPPED];
  }
  const parts = rel.split(path.sep);
  if (parts.slice(0, -1).some(x => SKIP.has(x)) || SKIP.has(parts[0])) return true;
  for (const p of IGNORED) {
    if (!p) continue;
    const folder = p.endsWith('/'), q = p.replace(/^\/+|\/+$/g, '');
    if (q.includes('/')) { if (rel === q || rel.startsWith(q + path.sep) || fnmatch(rel, q)) return true; }
    else { const isDir = (() => { try { return fs.statSync(path.join(ROOT, rel)).isDirectory(); } catch { return false; } })(); if ((folder && !isDir ? parts.slice(0, -1) : parts).some(n => fnmatch(n, q))) return true; }
  }
  return false;
}
function isText(rel) {
  const name = path.basename(rel);
  if (NAMED.has(name) || TEXT.has(path.extname(name).toLowerCase())) return true;
  if (!name.includes('.')) { try { const fd = fs.openSync(path.join(ROOT, rel), 'r'); const b = Buffer.alloc(2); const n = fs.readSync(fd, b, 0, 2, 0); fs.closeSync(fd); return n === 2 && b.toString() === '#!'; } catch { return false; } }
  return false;
}
function expand(rel) {
  const k = rel.lastIndexOf('/'); const folder = k >= 0 ? rel.slice(0, k) : '', name = k >= 0 ? rel.slice(k + 1) : rel;
  if (/[*?[]/.test(folder)) return [];
  let names; try { names = fs.readdirSync(folder ? path.join(ROOT, folder) : ROOT).sort((a, b) => (a < b ? -1 : a > b ? 1 : 0)); } catch { return []; }
  return names.filter(n => fnmatch(n, name)).map(n => (folder ? folder + '/' + n : n));
}
function mapped(rel, folderOk = true) {
  if (rel === null || rel === undefined) return false;
  if (/[*?[]/.test(rel)) return expand(rel).slice(0, 50).some(x => mapped(x, folderOk));
  if (rel === '.') return folderOk;
  if (rel === 'map.yaml' || rel.split(path.sep)[0] === 'map') return false;
  const full = path.join(ROOT, rel);
  let st; try { st = fs.statSync(full); } catch { return false; }
  if (st.isDirectory()) return folderOk && !ignored(rel);
  return isText(rel) && !ignored(rel);
}
const SAFE = /^[A-Za-z0-9@%+=:,./_-]+$/;
const quoteWord = w => (!w ? "''" : SAFE.test(w) ? w : "'" + w.split("'").join("'\"'\"'") + "'");
const quote = words => words.map(quoteWord).join(' ');
// @end map.guard.scope

// @map map.guard.commands: a shell line into its commands (heredocs left out, cd followed), and each command's map question
const PUNCT = '();<>|&';
function shellWords(line) {
  const out = []; let word = '', i = 0, quote_ = null, had = false; const n = line.length;
  while (i < n) {
    const c = line[i];
    if (quote_) {
      if (c === quote_) quote_ = null;
      else if (quote_ === '"' && c === '\\' && i + 1 < n && '"\\$`\n'.includes(line[i + 1])) { word += line[i + 1]; i++; }
      else word += c;
    } else if (c === '\'' || c === '"') { quote_ = c; had = true; }
    else if (c === '\\' && i + 1 < n) { word += line[i + 1]; had = true; i++; }
    else if (/\s/.test(c)) { if (had) { out.push(word); word = ''; had = false; } }
    else if (PUNCT.includes(c)) { if (had) { out.push(word); word = ''; had = false; } let j = i; while (j < n && PUNCT.includes(line[j])) j++; out.push(line.slice(i, j)); i = j; continue; }
    else if (c === '#' && !had) break;
    else { word += c; had = true; }
    i++;
  }
  if (had) out.push(word);
  return out;
}
const HEAD_RX = /^<<-?\s*(['"]?)(\w+)\1/;
function heredocs(line) {
  const out = []; let pos = 0;
  for (;;) {
    const i = line.indexOf('<<', pos); if (i < 0) break;
    const m = HEAD_RX.exec(line.slice(i));
    if (!m) { pos = i + 2; continue; }
    const headEnd = line.indexOf('\n', i);
    if (headEnd < 0) { pos = i + 2; continue; }
    const tag = m[2]; let k = headEnd + 1; const bodyStart = k; let end = null;
    while (k <= line.length) {
      const nl = line.indexOf('\n', k); const seg = nl < 0 ? line.slice(k) : line.slice(k, nl);
      if (seg.trim() === tag) { end = nl < 0 ? line.length : nl; const body = k > bodyStart ? line.slice(bodyStart, k - 1) : ''; out.push([i, end, line.slice(line.lastIndexOf('\n', i - 1) + 1, i), tag, body]); break; }
      if (nl < 0) break;
      k = nl + 1;
    }
    pos = end !== null ? end : i + 2;
  }
  return out;
}
function withoutHeredocs(line) {
  for (const [start, end] of heredocs(line).reverse()) {
    const headEnd = line.indexOf('\n', start); const marker = HEAD_RX.exec(line.slice(start))[0];
    line = line.slice(0, start) + line.slice(start + marker.length, headEnd) + line.slice(end);
  }
  return line;
}
function commands(line, cwd) {
  line = withoutHeredocs(line).split('\\\n').join(' ').split('\n').join(' ; ').replace(/\d?>&\d|\d?>\s*\/dev\/null/g, ' ');
  const split = [];
  for (const t of shellWords(line)) { if (/^[|&;()<>]+$/.test(t)) split.push(...(t.match(/\|\||&&|\|&|;;|>>|&>|[|&;()<>]/g) || [])); else split.push(t); }
  const out = []; let words = [], piped = false, base = cwd;
  for (const t of [...split, ';']) {
    if (['|', '||', '&&', ';', '&', '(', ')', '|&', ';;', '\n'].includes(t)) {
      if (words.length) { if (words[0] === 'cd' && words.length > 1) base = path.resolve(base, expanduser(words[1])); else out.push([words, piped, base]); }
      piped = t === '|' || t === '|&'; words = [];
    } else words.push(t);
  }
  return out;
}
function grepQuestion(words, base) {
  const pats = [], paths = [], includes = [], flags = new Set(); let i = 1;
  while (i < words.length) {
    const a = words[i];
    if (a === '-e' || a === '--regexp') { pats.push(i + 1 < words.length ? words[i + 1] : ''); i += 2; continue; }
    if (a.startsWith('--include=')) includes.push(a.slice(10));
    else if (['-A', '-B', '-C', '-m', '--max-count', '-g', '--glob', '-t', '--type', '--include', '--exclude'].includes(a)) { if (['-g', '--glob', '--include'].includes(a)) includes.push(i + 1 < words.length ? words[i + 1] : ''); i += 2; continue; }
    else if (a.startsWith('--')) flags.add(a);
    else if (a.startsWith('-') && a.length > 1) for (const ch of a.slice(1)) flags.add(ch);
    else paths.push(a);
    i++;
  }
  let pats_ = pats, paths_ = paths;
  if (!pats.length && paths.length) { pats_ = [paths[0]]; paths_ = paths.slice(1); }
  if (['c', 'q', 'l', 'L', '--count', '--quiet', '--silent', '--files-with-matches', '--files-without-match'].some(f => flags.has(f))) return null;
  const recursive = ['rg', 'ag', 'ack'].includes(words[0]) || ['r', 'R', '--recursive'].some(f => flags.has(f));
  if (!paths_.length && !recursive) return null;
  const rels = paths_.length ? paths_.map(p => inside(p, base)) : [inside('.', base)];
  if (!rels.some(r => mapped(r))) return null;
  let places = rels.filter(r => r && r !== '.');
  if (includes.length) places = (places.length ? places : ['']).flatMap(p => includes.map(g => path.join(p, '*' + g.replace(/^\*+/, '')))).map(p => p.replace(/^\/+/, ''));
  const pattern = pats_.join('|');
  if (pattern.includes('@map')) { const tag = /@map\s+([\w.-]+)/.exec(pattern); return tag ? [tag[1]] : (places.length ? places : ['.']); }
  if (/^\^#+.*$/.test(pattern) && places.every(p => p.endsWith('.md'))) return places;
  const plain = words[0] === 'grep' && !flags.has('E') && !flags.has('P');
  const alternatives = pats_.flatMap(p => p.split(plain ? /\\\||\|/ : /\|/));
  const names = alternatives.map(a => a.replace(/^\^?\s*(?:(?:export|async|pub|public|private|static)\s+)*(?:function\*?|def|fn|func|class|const|let|var|val)\s+|(?:\\?\(|\\s\*=|\s*=|\\b)$/g, ''));
  if (names.length && names.every(n => /^[#.]?[A-Za-z_$][\w$-]*$/.test(n)) && !flags.has('v') && !flags.has('F')) return [...new Set(names), ...(places.length ? ['--in', places.join(',')] : [])];
  let rx;
  if (flags.has('F')) rx = escapeRe(pattern);
  else if (flags.has('E') || flags.has('P') || ['egrep', 'rg', 'ag', 'ack'].includes(words[0])) rx = pattern;
  else rx = pattern.replace(/\\([|(){}+?])|([|(){}+?])/g, (m, a, b) => a || '\\' + b);
  if (flags.has('w')) rx = `\\b(?:${rx})\\b`;
  if (flags.has('i')) rx = '(?i)' + rx;
  return [rx, ...(places.length ? ['--in', places.join(',')] : [])];
}
function readQuestion(words, base) {
  const tool = words[0], args = words.slice(1);
  if (tool === 'sed' && args.some(a => a.startsWith('-i') || a === '--in-place')) return null;
  if ((tool === 'perl' || tool === 'ruby') && args.some(a => /^-\w*i\S*$/.test(a))) return null;
  let script = null, files;
  if (tool === 'sed') { const rest = args.filter(a => !a.startsWith('-')); script = rest.length ? rest[0] : null; files = rest.slice(1); }
  else if (tool === 'awk') files = args.filter(a => !a.startsWith('-')).slice(1);
  else files = args.filter((a, k) => !a.startsWith('-') && !(k && ['-n', '-c', '-f', '-d'].includes(args[k - 1])));
  let n = 10, fromStart = false;
  args.forEach((a, k) => {
    const m = /^-n(\+?\d+)?$|^-(\d+)$/.exec(a);
    if (a.startsWith('-c')) n = null;
    else if (m) { const v = m[1] || m[2] || (k + 1 < args.length ? args[k + 1] : '10'); const digits = v.replace(/^\+/, ''); n = /^\d+$/.test(digits) ? Number(digits) : 10; fromStart = v.startsWith('+'); }
  });
  const rels = [];
  for (const f of files) { const r = inside(f, base); if (r && /[*?[]/.test(f)) rels.push(...expand(r)); else rels.push(r); }
  if (!files.length || !rels.some(r => mapped(r, false))) return null;
  const out = [];
  for (const rel of rels) {
    if (!mapped(rel, false)) continue;
    const text = fs.readFileSync(path.join(ROOT, rel), 'utf8');
    const count = text === '' ? 0 : text.split('\n').length - (text.endsWith('\n') ? 1 : 0);
    const m = /^(\d+)(?:,(\d+|\$))?p$/.exec(script || '');
    const named = /\/\^?\s*(?:(?:export|async|pub)\s+)*(?:function|def|fn|func|class|const)\s+([A-Za-z_$][\w$]*)/.exec(script || '');
    if (m) out.push(`${rel}:${m[1]}-${m[2] && m[2] !== '$' ? m[2] : (m[2] ? count : m[1])}`);
    else if (named) out.push(named[1], '--in', rel);
    else if (tool === 'head' && n) out.push(`${rel}:1-${Math.min(count, n)}`);
    else if (tool === 'tail' && n) out.push(`${rel}:${fromStart ? n : Math.max(1, count - n + 1)}-${count}`);
    else out.push(rel);
  }
  return out;
}
function listQuestion(words, base) {
  const args = words.slice(1).filter(a => !a.startsWith('-'));
  if (words[0] === 'find') {
    if (words.some(a => ['-newer', '-mtime', '-mmin', '-size', '-exec', '-delete', '-empty', '-perm'].includes(a))) return null;
    let pattern = null; words.forEach((a, k) => { if ((a === '-name' || a === '-iname') && k + 1 < words.length && pattern === null) pattern = words[k + 1]; });
    const roots = words.slice(1).filter(a => !a.startsWith('-') && a !== pattern).slice(0, 1); const root = roots.length ? roots[0] : '.';
    const rel = inside(root, base);
    if (!mapped(rel) || (rel === '.' && !pattern)) return null;
    return [pattern ? path.join(rel === '.' ? '' : rel, '*' + pattern.replace(/^\*+/, '')) : rel];
  }
  const rels = args.map(a => inside(a, base)).filter(r => mapped(r) && r !== '.');
  return rels.length ? rels : null;
}
// @end map.guard.commands

// @map map.guard.commands.scripts: a script that opens a file of the code only to print it: python -c, node -e, a heredoc fed to them, a scratch script run by name
const READ_ARG = /\b(?:open|readFileSync|readFile|read_text|read_bytes|Path)\s*\(\s*(?:['"`]([^'"`\n]+)['"`]|([A-Za-z_$][\w$]*)\s*[,)])/g;
const NAMED_VAR = /\b([A-Za-z_$][\w$]*)\s*=\s*['"`]([^'"`\n]+)['"`]/g;
const WRITES_OTHER = /write_text\(|write_bytes\(|writeFileSync\(|writeFile\(|appendFileSync\(|open\([^)\n]*,\s*['"][wax+]/;
const SHOWS = /\bprint\(|console\.(?:log|dir|table)\(|(?:process|sys)\.stdout\.write\(/;
const INLINE = /\b(?:python3?\s+-c|node\s+(?:-e|--eval|-p|--print))\s+(['"])/g;
const FILE_SCRIPT = /\b(?:python3?|node)\s+(?:--?[\w=-]+\s+)*[^\s|;&-][^\s|;&]*\.(?:py|mjs|cjs|js)\b/;
const DATA = ['.json', '.yaml', '.yml', '.toml'];
const PATH_LITERAL = /['"`]([^'"`\s]+\.(?:js|mjs|cjs|ts|css|html|py|rb|go|rs|java|sh|md|json|yaml|yml|toml|txt))['"`]/g;
const LOOP = /\bfor\s*\(?\s*(?:const\s+|let\s+|var\s+)?(\w+)\s+(?:in|of)\s+[\[(]([^\])]*)[\])]/g;
const LOADED = /\b(\w+)\s*=\s*(?:json\.load|JSON\.parse)\(/g;
const all = (rx, text) => { rx.lastIndex = 0; const out = []; let m; while ((m = rx.exec(text))) { out.push(m); if (!m[0]) rx.lastIndex++; } return out; };
function writes(text) {
  if (WRITES_OTHER.test(text)) return true;
  let pos = 0;
  for (;;) { const i = text.indexOf('.write(', pos); if (i < 0) return false; const before = text.slice(0, i); if (!(before.endsWith('stdout') || before.endsWith('stderr'))) return true; pos = i + 7; }
}
function inlineScripts(line) {
  const out = [];
  for (const m of all(INLINE, line)) { const q = m[1]; let i = m.index + m[0].length; for (;;) { const j = line.indexOf(q, i); if (j < 0) break; if (line[j - 1] !== '\\') { out.push(line.slice(m.index + m[0].length, j)); break; } i = j + 1; } }
  return out;
}
function scripts(line, cwd) {
  const env = Object.fromEntries(all(/(?:^|[;&\s])([A-Za-z_]\w*)=([^\s;&|]+)/g, line).map(m => [m[1], m[2]]));
  const expand_ = p => p.replace(/^['"]+|['"]+$/g, '').replace(/\$\{?(\w+)\}?/g, (m, v) => (v in env ? env[v] : m));
  const out = inlineScripts(line);
  for (const [, , head, , body] of heredocs(line)) {
    if (/\b(?:python3?|node)\b/.test(head) && !FILE_SCRIPT.test(head)) out.push(body);
    else { const to = /\bcat\s*>>?\s*(\S+)/.exec(head); if (to && (expand_(to[1]).includes('$') || inside(expand_(to[1]), cwd) === null)) out.push(body); }
  }
  for (const [words, , base] of commands(line, cwd)) {
    if (['node', 'python', 'python3'].includes(path.basename(words[0])) && words.length > 1 && !words[1].startsWith('-')) {
      const name = expand_(words[1]); const f = path.resolve(base, expanduser(name));
      try { if (inside(name, base) === null && fs.statSync(f).isFile() && fs.statSync(f).size < 300000) out.push(fs.readFileSync(f, 'utf8')); } catch { /* not a file */ }
    }
  }
  return out;
}
function scriptQuestion(line, cwd) {
  const out = [];
  for (const text of scripts(line, cwd)) {
    if (!SHOWS.test(text) || writes(text)) continue;
    const names = Object.fromEntries(all(NAMED_VAR, text).map(m => [m[1], m[2]])); const paths = [];
    for (const m of all(READ_ARG, text)) { const [, literal, v] = m; if (literal || v in names) paths.push(literal || names[v]); else for (const l of all(LOOP, text)) if (l[1] === v) for (const p of all(PATH_LITERAL, l[2])) paths.push(p[1]); }
    const dumped = all(LOADED, text).some(m => new RegExp('(?:json\\.dumps|JSON\\.stringify)\\(\\s*' + escapeRe(m[1]) + '\\b|(?:print|console\\.log)\\(\\s*' + escapeRe(m[1]) + '\\s*\\)').test(text));
    for (const p of paths) { const rel = inside(p, cwd); if (mapped(rel, false) && (!DATA.some(d => rel.endsWith(d)) || dumped)) out.push(rel); }
  }
  const uniq = [...new Set(out)];
  return uniq.length ? uniq : null;
}
// @end map.guard.commands.scripts

// @map map.guard.decide: each agent's input read into one shape, the ask that replaces the call, and the answer in the agent's format
function question(words, base) {
  const tool = path.basename(words[0]);
  if (tool === 'git' && words[1] === 'grep') return grepQuestion(['grep', '-r', ...words.slice(2)], base);
  if (tool === 'xargs' && words.length > 1 && SEARCH.has(path.basename(words[1]))) return grepQuestion([...words.slice(1), '-r', '.'], base);
  if (SEARCH.has(tool)) return grepQuestion([tool, ...words.slice(1)], base);
  if (READ.has(tool)) return readQuestion([tool, ...words.slice(1)], base);
  if (LIST.has(tool)) return listQuestion([tool, ...words.slice(1)], base);
  return null;
}
function shellQuestion(line, cwd) {
  if (line.includes('map.py') || line.includes('map.mjs') || (ASK.startsWith('map ') && (' ' + line.split('\n')[0] + ' ').includes(' map '))) return null;
  let asked = scriptQuestion(line, cwd) || []; const filtered = [], parts = commands(line, cwd);
  parts.forEach(([words, piped, base], k) => {
    if (piped || words.some(w => ['>', '>>', '&>'].includes(w)) || !words.length) return;
    const after = k + 1 < parts.length ? parts[k + 1] : null;
    let q;
    if (words[0] === 'find' && after && after[1] && after[0][0] === 'xargs' && after[0].length > 1 && SEARCH.has(path.basename(after[0][1]))) {
      let pattern = '*'; words.forEach((a, j) => { if ((a === '-name' || a === '-iname') && j + 1 < words.length && pattern === '*') pattern = words[j + 1]; });
      const root = words.slice(1).find(a => !a.startsWith('-')) || '.';
      q = grepQuestion([...after[0].slice(1), '-r', root, '--include=' + pattern], base);
    } else q = question(words, base);
    if (!q) return;
    const pipe = [];
    for (const [w, fed] of parts.slice(k + 1)) { if (!fed || !FILTERS.has(path.basename(w[0]))) break; pipe.push(quote(w)); }
    if (pipe.length) filtered.push(ASK + quote(q) + ' | ' + pipe.join(' | ')); else asked = asked.concat(q);
  });
  const all_ = [...(asked.length ? [ASK + quote(asked)] : []), ...filtered];
  return all_.length ? all_.join('; ') : null;
}
function readQuestionTool(filePath, cwd, offset, limit) {
  const rel = inside(filePath || '', cwd);
  if (!mapped(rel, false) || limit || offset) return null;
  return ASK + quote([rel]);
}
function normalise(agent, data) {
  const roots = data.workspace_roots;
  let cwd = data.cwd || (Array.isArray(roots) && roots.length ? roots[0] : ROOT);
  if (agent === 'cursor') {
    if ('command' in data && !('tool_name' in data)) return ['shell', { command: data.command }, cwd];
    if ('file_path' in data && !('tool_name' in data)) return ['read', { file_path: data.file_path }, cwd];
    const name = String(data.tool_name || '').toLowerCase(), given = data.tool_input || {};
    cwd = given.working_directory || cwd;
    const kind = ['shell', 'bash', 'terminal'].includes(name) ? 'shell' : ['read', 'read_file'].includes(name) ? 'read' : null;
    return [kind, given, cwd];
  }
  if (agent === 'copilot') {
    const name = String(data.toolName || data.tool_name || '').toLowerCase();
    let given = 'toolArgs' in data ? data.toolArgs : data.tool_input;
    if (typeof given === 'string') { try { given = JSON.parse(given); } catch { given = { command: given }; } }
    given = given || {};
    return [{ bash: 'shell', powershell: 'shell', view: 'read', grep: 'grep', glob: 'glob' }[name] || null, given, cwd];
  }
  if (agent === 'gemini') {
    const name = String(data.tool_name || '').toLowerCase(), given = data.tool_input || {};
    const kind = name.includes('shell') ? 'shell' : ['read_file', 'read_many_files'].includes(name) ? 'read' : (name.includes('grep') || name.includes('search_file')) ? 'grep' : name === 'glob' ? 'glob' : name === 'list_directory' ? 'list' : null;
    return [kind, given, cwd];
  }
  const given = data.tool_input || {};
  return [{ Bash: 'shell', Read: 'read', Grep: 'grep', Glob: 'glob' }[data.tool_name] || null, given, cwd];
}
function replacement(agent, data) {
  const [kind, given, cwd] = normalise(agent, data);
  if (!given || typeof given !== 'object' || Array.isArray(given)) return null;
  if (kind === 'shell') return shellQuestion(given.command || given.cmd || '', cwd);
  if (kind === 'read') { const paths = given.paths; const p = given.file_path || given.absolute_path || given.path || (Array.isArray(paths) && paths.length ? paths[0] : ''); return readQuestionTool(p, cwd, given.offset || given.start_line, given.limit || given.end_line); }
  const folder = given.path || given.dir_path || '.';   // Gemini names the folder dir_path
  if (kind === 'grep') {
    if (given.output_mode === 'count') return null;
    const words = ['rg', ...(given['-i'] || given.case_insensitive ? ['-i'] : []), '-e', given.pattern || '', folder, ...(given.glob ? ['--glob', given.glob] : []), ...(given.include ? ['--glob', given.include] : [])];
    const q = grepQuestion(words, cwd); return q ? ASK + quote(q) : null;
  }
  if (kind === 'glob') { const rel = inside(folder, cwd); return mapped(rel) ? ASK + quote([path.join(rel === null || rel === '.' ? '' : rel, given.pattern || '')]) : null; }
  if (kind === 'list') { const rel = inside(folder, cwd); return mapped(rel) && rel !== '.' ? ASK + quote([rel]) : null; }
  return null;
}
function detect(data) {
  if ('cursor_version' in data || ('command' in data && !('tool_name' in data)) || ('file_path' in data && !('tool_name' in data))) return 'cursor';
  if ('toolName' in data || ['bash', 'powershell', 'view', 'grep', 'glob', 'create', 'edit'].includes(String(data.tool_name || ''))) return 'copilot';
  if (data.hook_event_name === 'BeforeTool') return 'gemini';
  return 'claude';
}
function answer(agent, asked) {
  const reason = REASON + asked;
  if (agent === 'cursor') return { permission: 'deny', user_message: 'map-guard: read it through the map (ask). ' + asked, agent_message: reason };
  if (agent === 'copilot') return { permissionDecision: 'deny', permissionDecisionReason: reason };
  if (agent === 'gemini') return { decision: 'deny', reason };
  return { hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'deny', permissionDecisionReason: reason } };
}
const SETTINGS = {
  claude: ['.claude/settings.json', me => ({ hooks: { PreToolUse: [{ matcher: 'Bash|Read|Grep|Glob', hooks: [{ type: 'command', command: `node "$CLAUDE_PROJECT_DIR/${me}"` }] }] } })],
  codex: ['.codex/hooks.json', me => ({ hooks: { PreToolUse: [{ matcher: 'Bash', hooks: [{ type: 'command', command: `node "$(git rev-parse --show-toplevel)/${me}" --agent codex`, statusMessage: 'map-guard' }] }] } })],
  cursor: ['.cursor/hooks.json', me => ({ version: 1, hooks: { beforeShellExecution: [{ command: `node ${me} --agent cursor` }], beforeReadFile: [{ command: `node ${me} --agent cursor` }] } })],
  copilot: ['.github/hooks/map-guard.json', me => ({ version: 1, hooks: { preToolUse: [{ type: 'command', bash: `node ${me} --agent copilot`, cwd: '.', timeoutSec: 10 }] } })],
  gemini: ['.gemini/settings.json', me => ({ hooks: { BeforeTool: [{ matcher: 'run_shell_command|read_file|read_many_files|grep_search|glob|list_directory', hooks: [{ name: 'map-guard', type: 'command', command: `node "$GEMINI_PROJECT_DIR/${me}" --agent gemini`, timeout: 5000 }] }] } })],
};
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
function merge(old, nu) {
  if (old && typeof old === 'object' && !Array.isArray(old) && nu && typeof nu === 'object' && !Array.isArray(nu)) { const out = { ...old }; for (const [k, v] of Object.entries(nu)) out[k] = k in old ? merge(old[k], v) : v; return out; }
  if (Array.isArray(old) && Array.isArray(nu)) return [...old, ...nu.filter(x => !old.some(y => same(x, y)))];
  return nu;
}
function install(agent) {
  if (!(agent in SETTINGS)) { process.stderr.write(`install <agent>: one of ${Object.keys(SETTINGS).join(', ')}\n`); process.exit(1); }
  const me = path.relative(fs.realpathSync(ROOT), fs.realpathSync(process.argv[1])).split(path.sep).join('/');   // links resolved on both sides
  const [rel, make] = SETTINGS[agent]; const full = path.join(ROOT, rel);
  let old = {}; try { old = JSON.parse(fs.readFileSync(full, 'utf8')); } catch { old = {}; }
  fs.mkdirSync(path.dirname(full), { recursive: true });
  fs.writeFileSync(full, JSON.stringify(merge(old, make(me)), null, 2) + '\n');
  process.stdout.write(`${rel}: the map guard installed for ${agent} (${me}).` + (agent === 'codex' ? ' Codex runs project hooks once the .codex folder is trusted.' : '') + '\n');
}
function main(argv) {
  if (argv[0] === 'install' && argv.length === 2) return install(argv[1]);
  if (argv[0] === 'try' && argv.length === 2) { process.stdout.write((shellQuestion(argv[1], process.cwd()) || 'goes ahead') + '\n'); return; }
  const ai = argv.indexOf('--agent'); let agent = ai >= 0 && ai + 1 < argv.length ? argv[ai + 1] : null;
  let asked;
  try {
    const data = JSON.parse(fs.readFileSync(0, 'utf8'));
    if (!data || typeof data !== 'object' || Array.isArray(data)) return;
    agent = agent || detect(data);
    asked = replacement(agent, data);
  } catch { return; }
  if (asked) process.stdout.write(JSON.stringify(answer(agent, asked)) + '\n');
}
export { replacement, shellQuestion };
if (process.argv[1] && fs.realpathSync(process.argv[1]) === fs.realpathSync(new URL(import.meta.url).pathname)) main(process.argv.slice(2));
// @end map.guard.decide
