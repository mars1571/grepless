# Setting up each agent

Three things make the map work with an agent: the **instructions** it reads at the start of every session
(the "Finding code" section of [AGENTS.md](AGENTS.md)); where the agent has hooks, the **guard** that refuses
`grep`, `cat` and whole-file reads on the code and names the `ask` that answers the same question
(`map-guard.py`); and, optionally, the **coach** that reminds the agent, once, after three reads of the map in a
row, to put every question of a round in one call (`map-coach.py`). The instructions are what every agent follows;
the guard is what keeps them followed when the context grows and the agent forgets.

| Agent | Instructions it reads | Guard | Coach | Install the guard |
|---|---|---|---|---|
| Claude Code | `CLAUDE.md` (or `AGENTS.md` when there is no `CLAUDE.md`) | `PreToolUse` on Bash, Read, Grep, Glob | `PostToolUse` on Bash, Edit, Write | `python3 tools/map-guard.py install claude` |
| OpenAI Codex | `AGENTS.md` | `PreToolUse` on Bash | `PostToolUse` on Bash, apply_patch | `python3 tools/map-guard.py install codex` |
| Cursor | `AGENTS.md`, `.cursor/rules/*.mdc` | `beforeShellExecution`, `beforeReadFile` | `postToolUse` on Shell, Write | `python3 tools/map-guard.py install cursor` |
| GitHub Copilot (CLI, cloud agent, VS Code) | `AGENTS.md`, `.github/copilot-instructions.md` | `preToolUse` (CLI and cloud agent) | `postToolUse` | `python3 tools/map-guard.py install copilot` |
| Gemini CLI | `GEMINI.md`, or `AGENTS.md` through `context.fileName` | `BeforeTool` | `AfterTool` | `python3 tools/map-guard.py install gemini` |
| Any other agent that reads `AGENTS.md` (Jules, Factory, Aider, goose, opencode, Zed, Warp, Devin, Junie, Amp, RooCode, Kilo Code, Windsurf, Augment …) | `AGENTS.md` | none: the instructions alone | none | paste the section |

Each `install` writes the agent's hook settings next to any it already has (an entry already there is not
added twice) and prints the file it wrote; the Node, Go and Rust guards write the same files with their own
command. The coach goes in by hand, beside the guard, as below: this repository's own settings
(`.claude/settings.json`, `.codex/hooks.json`, `.cursor/hooks.json`, `.github/hooks/`, `.gemini/settings.json`)
carry both for all five agents, with `python/` where an adopting repository has `tools/`. What each agent reads,
and where the formats come from (the vendors' pages, read 2026-10-17):

## Claude Code

Instructions: `CLAUDE.md` is loaded into every session, and imports other files with `@path`
(`@AGENTS.md` on a line of its own, at most four hops deep). Since version 2.1.277 Claude Code reads `AGENTS.md`
when there is no `CLAUDE.md`. Source: [code.claude.com/docs/en/memory](https://code.claude.com/docs/en/memory).

Guard: a `PreToolUse` hook in `.claude/settings.json` gets `{tool_name, tool_input, cwd, …}` on stdin and
refuses with `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
"permissionDecisionReason": "…"}}` (or exit code 2 with the reason on stderr). A shell line made only of reads the
map answers, beside steps that only read (`git status`, `which`, `--version`, `echo`, counts, filters), is instead run in
its place: `"permissionDecision": "allow"` with `"updatedInput"` (the whole input, its `command` replaced: "updatedInput
replaces the entire input object") and `"additionalContext"` saying so. A line that also has a step that is not a read
is never allowed (an allow skips Claude Code's permission prompt): it is denied with the whole line to send again in the
reason, after `Run instead:`, each read as its ask and every other step as written; the other agents get that line too. Hooks of the
settings files also run inside subagents, whose input carries `agent_id` and `agent_type` (the guard reads `agent_id` as the marker: `guard.subagents` in `map.json` makes it deny, with the ask, the read lines it would run in the main session). The `PowerShell` tool is matched too (`Bash|PowerShell|Read|Grep|Glob`) and its reads are answered the same way. Coach: a `PostToolUse` hook answers
`{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "…"}}`, a "string added to Claude's
context alongside the tool result"; it counts each subagent's reads apart. Claude Code watches its settings files and applies an edit to the hooks in the
running session; when one has not appeared after a few seconds, restarting the session reloads them. Sources:
[hooks](https://code.claude.com/docs/en/hooks), [settings](https://code.claude.com/docs/en/settings).

```json
{"hooks": {
  "PreToolUse": [{"matcher": "Bash|PowerShell|Read|Grep|Glob", "hooks": [
    {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/tools/map-guard.py\""}]}],
  "PostToolUse": [{"matcher": "Bash|Edit|Write", "hooks": [
    {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/tools/map-coach.py\""}]}]}}
```

## OpenAI Codex

Instructions: "Codex reads AGENTS.md files before doing any work": `~/.codex/AGENTS.md`, then the repository's
root down to the working folder, the closer file overriding; at most 32 KiB by default
(`project_doc_max_bytes`). Source: [learn.chatgpt.com/docs/agent-configuration/agents-md](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

Guard: Codex hooks are enabled by default. A `PreToolUse` hook in `<repo>/.codex/hooks.json` gets `tool_name`
(`Bash` for shell commands) and `tool_input.command`, and refuses with the same `hookSpecificOutput` answer as
Claude Code. Project hooks run once the project's `.codex` folder is trusted, and each hook once it is reviewed:
"Codex records trust against the hook's current hash, so new or changed hooks are marked for review and skipped
until trusted" (`/hooks` reviews them). A hook runs in the session's working folder, so its command finds the script
from the git root. Coach: a `PostToolUse` hook's `additionalContext` "is added as extra developer context"; file
edits reach it as `apply_patch`. OpenAI calls hooks "a useful guardrail, not a complete enforcement boundary".
Source: [learn.chatgpt.com/docs/hooks](https://learn.chatgpt.com/docs/hooks).

```json
{"hooks": {
  "PreToolUse": [{"matcher": "Bash", "hooks": [
    {"type": "command", "command": "python3 \"$(git rev-parse --show-toplevel)/tools/map-guard.py\" --agent codex", "statusMessage": "map-guard"}]}],
  "PostToolUse": [{"matcher": "Bash|apply_patch", "hooks": [
    {"type": "command", "command": "python3 \"$(git rev-parse --show-toplevel)/tools/map-coach.py\" --agent codex", "statusMessage": "map-coach"}]}]}}
```

## Cursor

Instructions: "Cursor supports AGENTS.md in the project root and subdirectories"; project rules are `.cursor/rules/*.mdc`
files with `description`, `globs` and `alwaysApply`. Source: [cursor.com/docs/rules](https://cursor.com/docs/rules).

Guard: `.cursor/hooks.json` (version 1), whose hooks run from the project root in a trusted workspace, which is why
their commands are relative. `beforeShellExecution` gets `{command, cwd, sandbox, …}` and answers
`{"permission": "allow" | "deny" | "ask", "user_message", "agent_message"}`; `beforeReadFile` gets
`{file_path, content, attachments}` and answers `{"permission", "user_message"}`. A hook that crashes or times out
fails open unless `failClosed` is true. Coach: `postToolUse` gets `{conversation_id, tool_name, tool_input, …}` and
its `additional_context` is "extra context injected into the conversation after the tool result". Cursor also runs
the hooks of `.claude/settings.json` (Settings → Agents → Third-Party Imports, on by default): in a repository with
both, the guard answers twice the same way and the coach counts each call once. Sources:
[cursor.com/docs/hooks](https://cursor.com/docs/hooks),
[third-party hooks](https://cursor.com/docs/reference/third-party-hooks).

```json
{"version": 1, "hooks": {
  "beforeShellExecution": [{"command": "python3 tools/map-guard.py --agent cursor"}],
  "beforeReadFile": [{"command": "python3 tools/map-guard.py --agent cursor"}],
  "postToolUse": [{"command": "python3 tools/map-coach.py --agent cursor", "matcher": "Shell|Write"}]}}
```

## GitHub Copilot

Instructions: `.github/copilot-instructions.md` for the whole repository; `.github/instructions/*.instructions.md`
with `applyTo` globs for parts of it; `AGENTS.md` anywhere in the repository, the nearest one taking precedence
(a root `CLAUDE.md` or `GEMINI.md` serves too). The cloud agent, Copilot CLI and VS Code read `AGENTS.md`.
Sources: [add repository instructions](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions),
[custom instructions support](https://docs.github.com/en/copilot/reference/custom-instructions-support).

Guard: `.github/hooks/*.json`, run by Copilot CLI and the cloud agent (for the cloud agent, from the default
branch). `preToolUse` gets `{sessionId, cwd, toolName, toolArgs, …}` (`toolArgs` a JSON string holding `command` for
`bash`) and answers `{"permissionDecision": "deny", "permissionDecisionReason": "…"}`; exit code 2 denies, and so
does any other non-zero exit; timeouts fail open; the cloud agent treats "ask" as "deny". `install` sets the hook's
`cwd` to `.`, the repository's root, so that the relative command is found wherever the CLI was started. Coach:
`postToolUse` answers `{"additionalContext": "…"}`, appended to the tool's result for the model. Copilot CLI also
runs the hooks of `.claude/settings.json`; VS Code runs these files through the CLI's hooks in a Copilot-harness
session, while its Local harness, in preview, sends payloads of its own that the guard does not read yet. Sources:
[hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference),
[VS Code hooks](https://code.visualstudio.com/docs/agent-customization/hooks).

```json
{"version": 1, "hooks": {
  "preToolUse": [{"type": "command", "bash": "python3 tools/map-guard.py --agent copilot", "cwd": ".", "timeoutSec": 10}],
  "postToolUse": [{"type": "command", "bash": "python3 tools/map-coach.py --agent copilot", "cwd": ".", "matcher": "bash|powershell|edit|create", "timeoutSec": 10}]}}
```

## Gemini CLI

Instructions: `GEMINI.md`, in the workspace folders and their parents; `context.fileName` in `settings.json` can
name other files, `["AGENTS.md", "GEMINI.md"]` among them. Source:
[geminicli.com/docs/cli/gemini-md](https://geminicli.com/docs/cli/gemini-md/). (The site says Gemini CLI was
replaced by Antigravity CLI on 2026-06-18 for unpaid-tier and Google One users; the hook format below is the
documented one.)

Guard: `hooks` in `.gemini/settings.json`; `BeforeTool` gets `{tool_name, tool_input, cwd, …}` and answers
`{"decision": "deny", "reason": "…"}` (or exit code 2). The matcher is a regular expression over the tool names
(`run_shell_command`, `read_file`, `read_many_files`, `grep_search`, `glob`, `list_directory`); `read_file` reads a
range with `start_line` and `end_line`, which the guard lets through. `$GEMINI_PROJECT_DIR` in a command is the
project's root. Project hooks are fingerprinted: a new or changed one is "a new, untrusted hook" that Gemini CLI
warns about before it runs, and in a folder that is not trusted the project's settings are not loaded. Coach:
`AfterTool` answers `{"hookSpecificOutput": {"additionalContext": "…"}}`, appended to the tool's result. Source:
[geminicli.com/docs/hooks](https://geminicli.com/docs/hooks/).

```json
{"hooks": {
  "BeforeTool": [{"matcher": "run_shell_command|read_file|read_many_files|grep_search|glob|list_directory", "hooks": [
    {"name": "map-guard", "type": "command", "command": "python3 \"$GEMINI_PROJECT_DIR/tools/map-guard.py\" --agent gemini", "timeout": 5000}]}],
  "AfterTool": [{"matcher": "run_shell_command|replace|write_file", "hooks": [
    {"name": "map-coach", "type": "command", "command": "python3 \"$GEMINI_PROJECT_DIR/tools/map-coach.py\" --agent gemini", "timeout": 5000}]}]}}
```

## Agents without hooks

Instructions alone did little. In the project where the map was built, after the "Finding code" section was written
and before the guard existed, the median session put 10% of its reads through the map (12% of all their reads);
with the guard, 85% (82%) ([docs/EVIDENCE.md](../docs/EVIDENCE.md)). For an agent that cannot run a hook, keep
the section, run `tools/map-sessions.py` if the agent leaves transcripts you can read, and watch how many reads
go through the map.

`AGENTS.md` itself is "a simple, open format for guiding coding agents", plain Markdown with no required
fields, stewarded by the Agentic AI Foundation (Linux Foundation): [agents.md](https://agents.md/).
