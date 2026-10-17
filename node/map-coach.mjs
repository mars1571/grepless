#!/usr/bin/env node
// @map map.coach.remind: once and in the moment, after three reads of the map in a row, the reminder to ask every question of a round in one call
// map-coach: a post-tool hook (Claude Code's PostToolUse, Codex's too) that reminds the agent of the working loop when it
// drifts from it, once each time and never blocking. The Node version of python/map-coach.py.
//   .claude/settings.json → "PostToolUse": [{"matcher": "Bash|Edit|Write", "hooks": [{"type": "command",
//                             "command": "node \"$CLAUDE_PROJECT_DIR/tools/map-coach.mjs\""}]}]
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const DIR = process.env.MAP_COACH_DIR || path.join(os.tmpdir(), 'map-coach');
const READS = 'Three reads of the map in a row (AGENTS.md, "Finding code"): ask in one call every question you can already '
  + 'name, the blocks, names and line ranges these answers point to, and send the calls that do not depend on each other in one message.';
const QUIET = new Set(['head', 'tail', 'cut', 'wc', 'echo', 'grep', 'sort', 'uniq']);

function kind(tool, given) {
  if (tool !== 'Bash') return 'work';
  const cmd = given.command || '';
  const lines = []; let end = null;
  for (const line of cmd.split('\n')) {
    if (end) { if (line.trim() === end) end = null; continue; }
    lines.push(line);
    const m = /<<-?\s*'?(\w+)'?/.exec(line); end = m ? m[1] : null;
  }
  const words = [];
  for (let step of lines.join('\n').split(/&&|\|\||[;\n|]/)) {
    step = step.trim().replace(/^(\w+=\S+\s+)+/, '');
    if (step && !step.startsWith('cd ')) words.push(step.split(/\s+/).slice(0, 2));
  }
  const reads = words.filter(w => ['python3', 'python', 'node'].includes(w[0]) && w[1] && /map\.(py|mjs)$/.test(w[1])).length;
  const quiet = words.filter(w => QUIET.has(w[0])).length;
  return reads && reads + quiet === words.length ? 'map' : 'work';
}
function main() {
  let data; try { data = JSON.parse(fs.readFileSync(0, 'utf8')); } catch { return; }
  if (!data || typeof data !== 'object' || data.agent_id || !data.session_id) return;
  const k = kind(data.tool_name, data.tool_input || {});
  const file = path.join(DIR, String(data.session_id).replace(/\W/g, '').slice(0, 64) + '.json');
  let state; try { state = JSON.parse(fs.readFileSync(file, 'utf8')); } catch { state = { reads: 0 }; }
  state.reads = k === 'map' ? state.reads + 1 : 0;
  fs.mkdirSync(DIR, { recursive: true });
  for (const name of fs.readdirSync(DIR)) { const old = path.join(DIR, name); try { if (Date.now() - fs.statSync(old).mtimeMs > 3 * 86400 * 1000) fs.unlinkSync(old); } catch { /* gone */ } }
  const tmp = `${file}.${process.pid}`; fs.writeFileSync(tmp, JSON.stringify(state)); fs.renameSync(tmp, file);
  if (state.reads === 3) process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: 'PostToolUse', additionalContext: READS } }) + '\n');
}
try { main(); } catch { /* a reminder is never worth a failed call */ }
// @end map.coach.remind
