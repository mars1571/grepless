#!/usr/bin/env node
// @map map.coach.remind: once and in the moment, after three reads of the map in a row, the reminder to ask every question of a round in one call
// map-coach: a post-tool hook that reminds the agent of the working loop when it drifts from it, once each time and never
// blocking. The Node version of python/map-coach.py, for the same five agents and with the same answers.
//   node tools/map-coach.mjs [--agent claude|codex|cursor|copilot|gemini]   the hook: stdin in, the reminder out
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const DIR = process.env.MAP_COACH_DIR || path.join(os.tmpdir(), 'map-coach');
const READS = 'Three reads of the map in a row (AGENTS.md, "Finding code"): ask in one call every question you can already '
  + 'name, the blocks, names and line ranges these answers point to, and send the calls that do not depend on each other in one message.';
const QUIET = new Set(['head', 'tail', 'cut', 'wc', 'echo', 'grep', 'sort', 'uniq']);
const SHELL = new Set(['Bash', 'bash', 'powershell', 'Shell', 'run_shell_command']);
const MAP = /map(?:\.py|\.mjs)$|(?:^|\/)map$/;
const AGAIN = 5;

function kind(tool, given) {
  if (!SHELL.has(tool)) return 'work';
  const cmd = String(given.command || '');
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
  const reads = words.filter(w => (['python3', 'python', 'node'].includes(w[0]) && w[1] && MAP.test(w[1])) || MAP.test(w[0])).length;
  const quiet = words.filter(w => QUIET.has(w[0])).length;
  return reads && reads + quiet === words.length ? 'map' : 'work';
}
function detect(data) {
  if ('cursor_version' in data || 'conversation_id' in data) return 'cursor';
  if ('toolName' in data || 'sessionId' in data) return 'copilot';
  if (data.hook_event_name === 'AfterTool') return 'gemini';
  return 'claude';
}
function normalise(agent, data) {
  if (agent === 'copilot') {
    let given = 'toolArgs' in data ? data.toolArgs : data.tool_input;
    if (typeof given === 'string') { try { given = JSON.parse(given); } catch { given = { command: given }; } }
    return [data.sessionId || data.session_id, data.toolName || data.tool_name, given];
  }
  return [agent === 'cursor' ? data.conversation_id : data.session_id, data.tool_name, data.tool_input];
}
function answer(agent) {
  if (agent === 'cursor') return { additional_context: READS };
  if (agent === 'copilot') return { additionalContext: READS };
  return { hookSpecificOutput: { hookEventName: agent === 'gemini' ? 'AfterTool' : 'PostToolUse', additionalContext: READS } };
}
function main(argv) {
  const i = argv.indexOf('--agent');
  let agent = i >= 0 && i + 1 < argv.length ? argv[i + 1] : null;
  let data; try { data = JSON.parse(fs.readFileSync(0, 'utf8')); } catch { return; }
  if (!data || typeof data !== 'object' || Array.isArray(data) || data.agent_id) return;   // a subagent's calls are its own business
  agent = agent || detect(data);
  let [session, tool, given] = normalise(agent, data);
  if (!session) return;
  given = given && typeof given === 'object' && !Array.isArray(given) ? given : {};
  const call = String(given.command || given.file_path || given.path || '');
  const file = path.join(DIR, String(session).replace(/[^A-Za-z0-9_]/g, '').slice(0, 64) + '.json');
  let state; try { state = JSON.parse(fs.readFileSync(file, 'utf8')) || {}; } catch { state = {}; }
  const now = Date.now() / 1000;
  if (call && state.last === call && now - (state.at || 0) >= 0 && now - (state.at || 0) < AGAIN) return;   // the same call, from a second source
  state = { reads: kind(tool, given) === 'map' ? (state.reads || 0) + 1 : 0, last: call, at: now };
  fs.mkdirSync(DIR, { recursive: true });
  for (const name of fs.readdirSync(DIR)) { const old = path.join(DIR, name); try { if (now * 1000 - fs.statSync(old).mtimeMs > 3 * 86400 * 1000) fs.unlinkSync(old); } catch { /* gone */ } }
  const tmp = `${file}.${process.pid}`; fs.writeFileSync(tmp, JSON.stringify(state)); fs.renameSync(tmp, file);
  if (state.reads === 3) process.stdout.write(JSON.stringify(answer(agent)) + '\n');
}
try { main(process.argv.slice(2)); } catch { /* a reminder is never worth a failed call */ }
// @end map.coach.remind
