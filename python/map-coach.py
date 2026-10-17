#!/usr/bin/env python3
# @map map.coach.remind: once and in the moment, after three reads of the map in a row, the reminder to ask every question of a round in one call
"""map-coach: a post-tool hook that reminds the agent of the working loop when it drifts from it, once each time and
never blocking: after three calls in a row that only read the map, one question or two at a time, it says to put every
question of a round in one call. Its state is a small file per session in the system's temporary folder. Anything it
cannot read goes ahead without a word.

    python3 tools/map-coach.py [--agent claude|codex|cursor|copilot|gemini]   the hook: stdin in, the reminder out

The agents' post-tool hooks, as their docs give them (agents/README.md has the sources and each agent's settings):
  claude   Claude Code: PostToolUse {session_id, tool_name, tool_input}; {"hookSpecificOutput": {"additionalContext"}}
  codex    Codex: PostToolUse with the same fields and answer (.codex/hooks.json)
  cursor   Cursor: postToolUse {conversation_id, tool_name, tool_input}; {"additional_context"}
  copilot  GitHub Copilot: postToolUse {sessionId, toolName, toolArgs}; {"additionalContext"}
  gemini   Gemini CLI: AfterTool {session_id, tool_name, tool_input}; {"hookSpecificOutput": {"additionalContext"}}
Without --agent, the format is told from the fields. Cursor and Copilot CLI also run the hooks of .claude/settings.json,
so one call can reach the coach twice: a call the session counted in the last few seconds is not counted again.
"""
import json
import os
import re
import sys
import tempfile
import time

DIR = os.environ.get('MAP_COACH_DIR') or os.path.join(tempfile.gettempdir(), 'map-coach')
READS = ('Three reads of the map in a row (AGENTS.md, "Finding code"): ask in one call every question you can already '
         'name, the blocks, names and line ranges these answers point to, and send the calls that do not depend on each '
         'other in one message.')
QUIET = ('head', 'tail', 'cut', 'wc', 'echo', 'grep', 'sort', 'uniq')
SHELL = ('Bash', 'bash', 'powershell', 'Shell', 'run_shell_command')     # each agent's shell tool
MAP = re.compile(r'map(?:\.py|\.mjs)$|(?:^|/)map$')                       # tools/map.py, tools/map.mjs, tools/map
AGAIN = 5                                                                 # seconds: the same call twice is one call


def kind(tool, given):
    """'map' for a shell line that only reads the map, else 'work'."""
    if tool not in SHELL:
        return 'work'
    cmd = str(given.get('command') or '')
    lines, end = [], None
    for line in cmd.split('\n'):                         # a heredoc's text is data, not steps
        if end:
            end = None if line.strip() == end else end
            continue
        lines.append(line)
        m = re.search(r"<<-?\s*'?(\w+)'?", line)
        end = m.group(1) if m else None
    words = []
    for step in re.split(r'&&|\|\||[;\n|]', '\n'.join(lines)):
        step = re.sub(r'^(\w+=\S+\s+)+', '', step.strip())
        if step and not step.startswith('cd '):
            words.append(step.split()[:2])
    reads = sum(1 for w in words if (w[0] in ('python3', 'python', 'node') and w[1:2] and MAP.search(w[1])) or MAP.search(w[0]))
    quiet = sum(1 for w in words if w[0] in QUIET)
    return 'map' if reads and reads + quiet == len(words) else 'work'


def detect(data):
    if 'cursor_version' in data or 'conversation_id' in data:
        return 'cursor'
    if 'toolName' in data or 'sessionId' in data:
        return 'copilot'
    if data.get('hook_event_name') == 'AfterTool':
        return 'gemini'
    return 'claude'


def normalise(agent, data):
    """(session, tool, given): the call as one shape, whichever agent sent it."""
    if agent == 'copilot':
        given = data.get('toolArgs') if 'toolArgs' in data else data.get('tool_input')
        if isinstance(given, str):
            try:
                given = json.loads(given)
            except ValueError:
                given = {'command': given}
        return data.get('sessionId') or data.get('session_id'), data.get('toolName') or data.get('tool_name'), given
    session = data.get('conversation_id') if agent == 'cursor' else data.get('session_id')
    return session, data.get('tool_name'), data.get('tool_input')


def answer(agent):
    if agent == 'cursor':
        return {'additional_context': READS}
    if agent == 'copilot':
        return {'additionalContext': READS}
    return {'hookSpecificOutput': {'hookEventName': 'AfterTool' if agent == 'gemini' else 'PostToolUse', 'additionalContext': READS}}


def main(argv):
    agent = argv[argv.index('--agent') + 1] if '--agent' in argv and argv.index('--agent') + 1 < len(argv) else None
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if not isinstance(data, dict) or data.get('agent_id'):           # a subagent's calls are its own business
        return
    agent = agent or detect(data)
    session, tool, given = normalise(agent, data)
    if not session:
        return
    given = given if isinstance(given, dict) else {}
    call = str(given.get('command') or given.get('file_path') or given.get('path') or '')
    path = os.path.join(DIR, re.sub(r'[^A-Za-z0-9_]', '', str(session))[:64] + '.json')
    try:
        with open(path) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    now = time.time()
    if call and state.get('last') == call and 0 <= now - (state.get('at') or 0) < AGAIN:
        return                                                        # the same call, from a second source
    reads = state.get('reads') or 0
    state = {'reads': reads + 1 if kind(tool, given) == 'map' else 0, 'last': call, 'at': now}
    os.makedirs(DIR, exist_ok=True)
    for name in os.listdir(DIR):                                      # sessions older than three days forgotten
        old = os.path.join(DIR, name)
        try:
            if now - os.path.getmtime(old) > 3 * 86400:
                os.remove(old)
        except OSError:
            pass
    tmp = f'{path}.{os.getpid()}'
    with open(tmp, 'w') as f:
        json.dump(state, f)
    os.replace(tmp, path)
    if state['reads'] == 3:
        print(json.dumps(answer(agent)))


try:
    main(sys.argv[1:])
except Exception:                                                     # noqa: BLE001 — a reminder is never worth a failed call
    pass
# @end map.coach.remind
