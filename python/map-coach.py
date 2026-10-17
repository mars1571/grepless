#!/usr/bin/env python3
# @map map.coach.remind: once and in the moment, after three reads of the map in a row, the reminder to ask every question of a round in one call
"""map-coach: a post-tool hook (Claude Code's PostToolUse, Codex's too) that reminds the agent of the working loop when
it drifts from it, once each time and never blocking: after three calls in a row that only read the map, one question
or two at a time, it says to put every question of a round in one call. Its state is a small file per session in the
system's temporary folder. Anything it cannot read goes ahead without a word.

    .claude/settings.json → "PostToolUse": [{"matcher": "Bash|Edit|Write", "hooks": [{"type": "command",
                              "command": "python3 \\"$CLAUDE_PROJECT_DIR/tools/map-coach.py\\""}]}]
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


def kind(tool, given):
    """'map' for a call that only reads the map, else 'work'."""
    if tool != 'Bash':
        return 'work'
    cmd = given.get('command', '')
    lines, end = [], None
    for line in cmd.splitlines():                        # a heredoc's text is data, not steps
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
    reads = sum(1 for w in words if w[0] in ('python3', 'python') and w[1:2] and w[1].endswith('map.py'))
    quiet = sum(1 for w in words if w[0] in QUIET)
    return 'map' if reads and reads + quiet == len(words) else 'work'


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if not isinstance(data, dict) or data.get('agent_id') or not data.get('session_id'):
        return
    k = kind(data.get('tool_name'), data.get('tool_input') or {})
    path = os.path.join(DIR, re.sub(r'\W', '', str(data['session_id']))[:64] + '.json')
    try:
        with open(path) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {'reads': 0}
    state['reads'] = state['reads'] + 1 if k == 'map' else 0
    os.makedirs(DIR, exist_ok=True)
    for name in os.listdir(DIR):                          # sessions older than three days forgotten
        old = os.path.join(DIR, name)
        try:
            if time.time() - os.path.getmtime(old) > 3 * 86400:
                os.remove(old)
        except OSError:
            pass
    tmp = f'{path}.{os.getpid()}'
    with open(tmp, 'w') as f:
        json.dump(state, f)
    os.replace(tmp, path)
    if state['reads'] == 3:
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': READS}}))


try:
    main()
except Exception:                                         # noqa: BLE001 — a reminder is never worth a failed call
    pass
# @end map.coach.remind
