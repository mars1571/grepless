# Setting up each agent

Two things make the map work with an agent: the **instructions** it reads at the start of every session
(the "Finding code" section of [AGENTS.md](AGENTS.md)) and, where the agent has hooks, the **guard** that
refuses `grep`, `cat` and whole-file reads on the code and names the `ask` that answers the same question
(`map-guard.py`). The instructions are what every agent follows; the guard is what keeps them followed when
the context grows and the agent forgets.

| Agent | Instructions it reads | Guard | Install |
|---|---|---|---|
| Claude Code | `CLAUDE.md` (or `AGENTS.md` when there is no `CLAUDE.md`) | PreToolUse hook on Bash, Read, Grep, Glob | `python3 tools/map-guard.py install claude` |
| OpenAI Codex | `AGENTS.md` | PreToolUse hook on Bash | `python3 tools/map-guard.py install codex` |
| Cursor | `AGENTS.md`, `.cursor/rules/*.mdc` | `beforeShellExecution` and `beforeReadFile` hooks | `python3 tools/map-guard.py install cursor` |
| GitHub Copilot (coding agent, CLI, VS Code) | `AGENTS.md`, `.github/copilot-instructions.md` | `preToolUse` hook (CLI and coding agent) | `python3 tools/map-guard.py install copilot` |
| Gemini CLI | `GEMINI.md`, or `AGENTS.md` through `context.fileName` | `BeforeTool` hook | `python3 tools/map-guard.py install gemini` |
| Any other agent that reads `AGENTS.md` (Jules, Factory, Aider, goose, opencode, Zed, Warp, Devin, Junie, Amp, RooCode, Kilo Code, Windsurf, Augment …) | `AGENTS.md` | none: the instructions alone | paste the section |

Each `install` writes the agent's hook settings next to any it already has (an entry already there is not
added twice) and prints the file it wrote; the Node, Go and Rust guards write the same files with their own
command. What each one writes, and where the formats come from:

## Claude Code

Instructions: `CLAUDE.md` is loaded into every session, and imports other files with `@path`
(`@AGENTS.md` on a line of its own, at most four hops deep). Since version 2.1.277 Claude Code reads `AGENTS.md`
when there is no `CLAUDE.md`. Source: [code.claude.com/docs/en/memory](https://code.claude.com/docs/en/memory).

Guard: a `PreToolUse` hook in `.claude/settings.json` gets `{tool_name, tool_input, cwd, …}` on stdin and
refuses with `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
"permissionDecisionReason": "…"}}` (or exit code 2 with the reason on stderr). Source:
[code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks).

```json
{"hooks": {"PreToolUse": [{"matcher": "Bash|Read|Grep|Glob", "hooks": [
  {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/tools/map-guard.py\""}]}]}}
```

The optional coach (`map-coach.py`) is a `PostToolUse` hook on `Bash|Edit|Write` that reminds the agent, once,
after three reads of the map in a row, to put every question of a round in one call.

## OpenAI Codex

Instructions: "Codex reads AGENTS.md files before doing any work": `~/.codex/AGENTS.md`, then the repository's
root down to the working folder, the closer file overriding; at most 32 KiB by default
(`project_doc_max_bytes`). Source: [learn.chatgpt.com/docs/agent-configuration/agents-md](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

Guard: Codex hooks are enabled by default; a `PreToolUse` hook in `<repo>/.codex/hooks.json` (project hooks run
once the `.codex` folder is trusted) gets `tool_name` (`Bash` for shell commands) and `tool_input.command`, and
refuses with the same `hookSpecificOutput` answer as Claude Code. OpenAI calls hooks "a useful guardrail, not a
complete enforcement boundary". Source: [learn.chatgpt.com/docs/hooks](https://learn.chatgpt.com/docs/hooks).

```json
{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
  {"type": "command", "command": "python3 \"$(git rev-parse --show-toplevel)/tools/map-guard.py\" --agent codex", "statusMessage": "map-guard"}]}]}}
```

## Cursor

Instructions: "Cursor supports AGENTS.md in the project root and subdirectories"; project rules are `.cursor/rules/*.mdc`
files with `description`, `globs` and `alwaysApply`. Source: [cursor.com/docs/context/rules](https://cursor.com/docs/context/rules).

Guard: `.cursor/hooks.json` (version 1). `beforeShellExecution` gets `{command, cwd, sandbox, …}` and answers
`{"permission": "allow" | "deny" | "ask", "user_message", "agent_message"}`; `beforeReadFile` gets
`{file_path, content, attachments}`. A hook that crashes or times out fails open unless `failClosed` is true.
Source: [cursor.com/docs/agent/hooks](https://cursor.com/docs/agent/hooks).

```json
{"version": 1, "hooks": {
  "beforeShellExecution": [{"command": "python3 tools/map-guard.py --agent cursor"}],
  "beforeReadFile": [{"command": "python3 tools/map-guard.py --agent cursor"}]}}
```

## GitHub Copilot

Instructions: `.github/copilot-instructions.md` for the whole repository; `.github/instructions/*.instructions.md`
with `applyTo` globs for parts of it; `AGENTS.md` anywhere in the repository, the nearest one taking precedence
(a root `CLAUDE.md` or `GEMINI.md` serves too). The coding agent, Copilot CLI and VS Code read `AGENTS.md`.
Sources: [add repository instructions](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions),
[custom instructions support](https://docs.github.com/en/copilot/reference/custom-instructions-support).

Guard: `.github/hooks/*.json` (Copilot CLI and the coding agent). `preToolUse` gets `{toolName, toolArgs, cwd, …}`
(`toolArgs` a JSON string holding `command` for `bash`) or the VS Code shape `{tool_name, tool_input}`, and
answers `{"permissionDecision": "deny", "permissionDecisionReason": "…"}`; exit code 2 denies; timeouts fail
open; the coding agent treats "ask" as "deny". Source: [hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference).

```json
{"version": 1, "hooks": {"preToolUse": [
  {"type": "command", "bash": "python3 tools/map-guard.py --agent copilot", "timeoutSec": 10}]}}
```

## Gemini CLI

Instructions: `GEMINI.md`, in the workspace folders and their parents; `context.fileName` in `settings.json` can
name other files, `["AGENTS.md", "GEMINI.md"]` among them. Source:
[geminicli.com/docs/cli/gemini-md](https://geminicli.com/docs/cli/gemini-md/). (The site says Gemini CLI was
replaced by Antigravity CLI on 2026-06-18 for some users; the hook format below is the documented one.)

Guard: `hooks` in `.gemini/settings.json`; `BeforeTool` gets `{tool_name, tool_input, cwd, …}` and answers
`{"decision": "deny", "reason": "…"}` (or exit code 2). Source: [geminicli.com/docs/hooks](https://geminicli.com/docs/hooks/).

```json
{"hooks": {"BeforeTool": [{"matcher": "run_shell_command|read_file|read_many_files|grep_search|glob|list_directory", "hooks": [
  {"name": "map-guard", "type": "command", "command": "python3 \"$GEMINI_PROJECT_DIR/tools/map-guard.py\" --agent gemini", "timeout": 5000}]}]}}
```

## Agents without hooks

Instructions alone did little. In the codebase the map was born in, after the "Finding code" section was written
and before the guard existed, the median session put 10% of its reads through the map (12% of all their reads);
with the guard, 85% (82%) ([docs/EVIDENCE.md](../docs/EVIDENCE.md)). For an agent that cannot run a hook, keep
the section, run `tools/map-sessions.py` if the agent leaves transcripts you can read, and watch how many reads
go through the map.

`AGENTS.md` itself is "a simple, open format for guiding coding agents", plain Markdown with no required
fields, stewarded by the Agentic AI Foundation (Linux Foundation): [agents.md](https://agents.md/).
