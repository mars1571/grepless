#!/usr/bin/env node
// @map map.sessions.read: a Claude Code transcript's model calls: the context each re-read, whether it only searched or read, its response time
// map-sessions: how the agents' sessions on this repository went, read from Claude Code's transcripts
// (~/.claude/projects/<this folder's slug>/*.jsonl). The Node version of python/map-sessions.py, same columns.
//   node tools/map-sessions.mjs [--since YYYY-MM-DD] [session-id-prefix …]
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { replacement } from './map-guard.mjs';

const ROOT = process.env.MAP_ROOT || path.dirname(path.dirname(fs.realpathSync(process.argv[1])));
const PROJECTS = path.join(os.homedir(), '.claude', 'projects');
const LOOK = new Set(['grep', 'egrep', 'fgrep', 'rg', 'ag', 'ack', 'cat', 'sed', 'head', 'tail', 'awk', 'nl', 'less', 'more', 'ls', 'find', 'tree', 'wc', 'cut',
  'sort', 'uniq', 'tr', 'xargs', 'column', 'echo', 'printf']);

function looks(tool, given) {
  if (['Read', 'Grep', 'Glob'].includes(tool)) return 'other';
  if (tool !== 'Bash') return null;
  let line = given.command || '';
  if (/map(?:\.py|\.mjs)?\s+(ask|brief|find|history|deps|impact|recipe|where)\b/.test(line)) return 'map';
  line = line.replace(/\d?>&\d|\d?>\s*\/dev\/null/g, ' ');
  if (/\bsed\s+-i|>\s*\S|\bnode\b|\bmake\b|\bnpx\b/.test(line)) return null;
  for (const m of line.matchAll(/\bpython3?\s+(\S*)/g)) if (!m[1].endsWith('map.py')) return null;
  const words = line.split('|').join(' | ').split(';').join(' ; ').split('&&').join(' && ').trim().split(/\s+/).filter(Boolean);
  const firsts = words.filter((w, k) => k === 0 || ['|', ';', '&&', '||'].includes(words[k - 1]));
  return firsts.length && firsts.every(w => LOOK.has(path.basename(w)) || w === 'cd') ? 'other' : null;
}
function questions(line) {
  const out = [];
  for (const m of line.matchAll(/map(?:\.py|\.mjs)?\s+ask\s+/g)) {
    const rest = line.slice(m.index + m[0].length);
    const stop = /\d?>|\||;|&&|\n/.exec(rest); const words = rest.slice(0, stop ? stop.index : rest.length).trim().split(/\s+/).filter(Boolean);
    out.push(words.filter((w, k) => !w.startsWith('--') && (k === 0 || words[k - 1] !== '--in')).length);
  }
  return out;
}
const stamp = s => { const t = Date.parse(s); return Number.isNaN(t) ? null : t / 1000; };
function calls(file) {
  const out = new Map(), asked = [], uses = new Map(), refused = new Set(); let prev = null;
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    let o; try { o = JSON.parse(line); } catch { continue; }
    const m = o.message || {}, t = stamp(o.timestamp || '');
    if (Array.isArray(m.content)) for (const x of m.content) if (x && x.type === 'tool_result' && JSON.stringify(x.content || '').includes('through its map')) refused.add(x.tool_use_id);
    if (o.type !== 'assistant' || !m.id) { prev = t || prev; continue; }
    for (const x of m.content || []) if (x && x.type === 'tool_use') {
      uses.set(x.id, [x.name, x.input || {}, o.cwd || ROOT]);
      const n = x.name === 'Bash' ? questions((x.input || {}).command || '').reduce((a, b) => a + b, 0) : 0; if (n) asked.push(n);
    }
    const u = m.usage || {};
    let c = out.get(m.id); if (!c) { c = { ctx: 0, kinds: [], since: prev, last: t }; out.set(m.id, c); }
    c.last = t || c.last; c.ctx = Math.max(c.ctx, (u.input_tokens || 0) + (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0));
    for (const x of m.content || []) if (x && x.type === 'tool_use') c.kinds.push(looks(x.name, x.input || {}));
    prev = t || prev;
  }
  let outside = 0;
  for (const [k, [tool, given, cwd]] of uses) if (!refused.has(k) && replacement('claude', { tool_name: tool, tool_input: given, cwd })) outside++;
  const rows = [...out.values()].map(c => [c.ctx, !c.kinds.length || c.kinds.includes(null) ? null : c.kinds.includes('map') ? 'map' : 'other',
    c.since && c.last && c.last - c.since > 0 && c.last - c.since < 600 ? c.last - c.since : null]);
  return [rows, asked, outside];
}
const median = xs => { const s = [...xs].sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : null; };
// x to d decimals as Python prints it: a tie (x exactly halfway at the last digit) goes to the even digit, where toFixed
// goes up. A double is such a tie only when x * 2^(d+1) is an odd integer.
function fixed(x, d) {
  const t = x * 2 ** (d + 1);
  if (!Number.isInteger(t) || t % 2 === 0) return x.toFixed(d);
  const n = Math.floor(x * 10 ** d);
  return ((n % 2 === 0 ? n : n + 1) / 10 ** d).toFixed(d);
}
const f1 = x => (x === null ? '-' : fixed(x, 1));
function report(paths) {
  const total = new Array(9).fill(0); const allLo = [], allHi = [];
  process.stdout.write('session'.padEnd(19) + 'calls'.padStart(6) + 'read M'.padStart(8) + 'search/read'.padStart(16) + 'their M'.padStart(8) + 'via map'.padStart(8)
    + 'asks'.padStart(6) + 'q/ask'.padStart(6) + 'outside'.padStart(8) + 'runs 8+'.padStart(8) + 's <300k'.padStart(8) + 's >300k'.padStart(8) + '\n');
  const line = (name, r, lo, hi) => process.stdout.write(name.padEnd(19) + String(r[0]).padStart(6) + fixed(r[1] / 1e6, 1).padStart(8) + String(r[2]).padStart(9)
    + ' (' + (fixed(r[2] / r[0] * 100, 0) + '%').padStart(4) + ')' + fixed(r[3] / 1e6, 1).padStart(8) + String(r[4]).padStart(8) + String(r[5]).padStart(6)
    + fixed(r[5] ? r[6] / r[5] : 0, 1).padStart(6) + String(r[7]).padStart(8) + String(r[8]).padStart(8) + f1(lo).padStart(8) + f1(hi).padStart(8) + '\n');
  for (const p of paths) {
    const [cs, asked, outside] = calls(p);
    if (!cs.length) continue;
    const nav = cs.filter(c => c[1]);
    let runs = 0, run = 0; for (const c of [...cs, [0, null, null]]) { if (c[1]) run++; else { runs += run >= 8 ? 1 : 0; run = 0; } }
    const row = [cs.length, cs.reduce((a, c) => a + c[0], 0), nav.length, nav.reduce((a, c) => a + c[0], 0), nav.filter(c => c[1] === 'map').length, asked.length, asked.reduce((a, b) => a + b, 0), outside, runs];
    row.forEach((v, k) => { total[k] += v; });
    const lo = cs.filter(c => c[2] && c[0] < 300000).map(c => c[2]), hi = cs.filter(c => c[2] && c[0] >= 300000).map(c => c[2]);
    allLo.push(...lo); allHi.push(...hi);
    const first = fs.readFileSync(p, 'utf8').split('\n').find(x => x.includes('"timestamp"'));
    let day = ''; try { day = (JSON.parse(first).timestamp || '').slice(0, 10); } catch { day = ''; }
    line(`${day} ${path.basename(p, '.jsonl').slice(0, 8)}`, row, median(lo), median(hi));
  }
  if (total[0]) line('all', total, median(allLo), median(allHi));
}
function main(args) {
  const si = args.indexOf('--since'); const since = si >= 0 ? args[si + 1] : '';
  const named = args.filter((a, k) => a !== '--since' && (k === 0 || args[k - 1] !== '--since'));
  const slug = ROOT.split('/').join('-').split('.').join('-');
  let folders = []; try { folders = fs.readdirSync(PROJECTS).filter(f => f.startsWith(slug)).map(f => path.join(PROJECTS, f)).filter(f => fs.statSync(f).isDirectory()); } catch { folders = []; }
  let found = folders.flatMap(f => fs.readdirSync(f).filter(x => x.endsWith('.jsonl')).map(x => path.join(f, x))).sort((a, b) => fs.statSync(a).mtimeMs - fs.statSync(b).mtimeMs);
  if (named.length) found = named.flatMap(a => (a.endsWith('.jsonl') ? [a] : found.filter(p => path.basename(p).startsWith(a))));
  if (!found.length) { process.stderr.write(`No transcripts for ${ROOT} under ${PROJECTS} (Claude Code writes them there).\n`); process.exit(1); }
  report([...new Set(found)].filter(p => { if (!since) return true; const first = fs.readFileSync(p, 'utf8').split('\n').find(x => x.includes('"timestamp"')); try { return (JSON.parse(first).timestamp || '') >= since; } catch { return false; } }));
}
main(process.argv.slice(2));
// @end map.sessions.read
