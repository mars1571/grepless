// @map map.coach.remind: once and in the moment, after three reads of the map in a row, the reminder to ask every question of a round in one call
//! map-coach: a post-tool hook that reminds the agent of the working loop when it drifts from it, once each time and
//! never blocking. The Rust version of python/map-coach.py, for the same five agents and with the same answers.
//!     map-coach [--agent claude|codex|cursor|copilot|gemini]   the hook: stdin in, the reminder out
use regex::Regex;
use serde_json::{json, Map, Value};
use std::io::Read;

const READS: &str = "Three reads of the map in a row (AGENTS.md, \"Finding code\"): ask in one call every question you can already name, the blocks, names and line ranges these answers point to, and send the calls that do not depend on each other in one message.";
/// Seconds within which the same call is the same call (Cursor and Copilot CLI also run .claude/settings.json).
const AGAIN: f64 = 5.0;

fn text(v: Option<&Value>) -> String { v.and_then(|x| x.as_str()).unwrap_or("").to_string() }

fn kind(tool: &str, given: &Map<String, Value>) -> &'static str {
    if !matches!(tool, "Bash" | "bash" | "powershell" | "Shell" | "run_shell_command") { return "work"; }
    let cmd = text(given.get("command"));
    let tag = Regex::new(r"<<-?\s*'?(\w+)'?").unwrap();
    let mut lines = Vec::new();
    let mut end: Option<String> = None;
    for line in cmd.split('\n') {
        if let Some(e) = &end { if line.trim() == e { end = None; } continue; }
        lines.push(line);
        end = tag.captures(line).map(|m| m[1].to_string());
    }
    let step_split = Regex::new(r"&&|\|\||[;\n|]").unwrap();
    let assigns = Regex::new(r"^(\w+=\S+\s+)+").unwrap();
    let map_script = Regex::new(if cfg!(windows) { r"map(?:\.py|\.mjs|\.exe)$|(?:^|/)map$" } else { r"map(?:\.py|\.mjs)$|(?:^|/)map$" }).unwrap();   // Windows: tools/map.exe too
    let quiet = ["head", "tail", "cut", "wc", "echo", "grep", "sort", "uniq"];
    let mut words: Vec<Vec<String>> = Vec::new();
    for step in step_split.split(&lines.join("\n")) {
        let step = assigns.replace(step.trim(), "").to_string();
        if !step.is_empty() && !step.starts_with("cd ") {
            words.push(step.split_whitespace().take(2).map(String::from).collect());
        }
    }
    let (mut reads, mut quiet_n) = (0, 0);
    for w in &words {
        let runner = matches!(w[0].as_str(), "python3" | "python" | "node") && w.get(1).map(|x| map_script.is_match(x)).unwrap_or(false);
        if runner || map_script.is_match(&w[0]) { reads += 1; } else if quiet.contains(&w[0].as_str()) { quiet_n += 1; }
    }
    if reads > 0 && reads + quiet_n == words.len() { "map" } else { "work" }
}

fn detect(data: &Map<String, Value>) -> &'static str {
    if data.contains_key("cursor_version") || data.contains_key("conversation_id") { return "cursor"; }
    if data.contains_key("toolName") || data.contains_key("sessionId") { return "copilot"; }
    if text(data.get("hook_event_name")) == "AfterTool" { return "gemini"; }
    "claude"
}

/// The call as one shape, whichever agent sent it: its session, its tool and the tool's input.
fn normalise(agent: &str, data: &Map<String, Value>) -> (String, String, Map<String, Value>) {
    let as_map = |v: Option<Value>| match v { Some(Value::Object(m)) => m, _ => Map::new() };
    if agent == "copilot" {
        let mut given = if data.contains_key("toolArgs") { data.get("toolArgs").cloned() } else { data.get("tool_input").cloned() };
        if let Some(Value::String(s)) = &given {
            given = Some(serde_json::from_str::<Value>(s).unwrap_or_else(|_| json!({"command": s})));
        }
        let mut session = text(data.get("sessionId"));
        if session.is_empty() { session = text(data.get("session_id")); }
        let mut tool = text(data.get("toolName"));
        if tool.is_empty() { tool = text(data.get("tool_name")); }
        return (session, tool, as_map(given));
    }
    let session = text(data.get(if agent == "cursor" { "conversation_id" } else { "session_id" }));
    (session, text(data.get("tool_name")), as_map(data.get("tool_input").cloned()))
}

fn answer(agent: &str) -> Value {
    match agent {
        "cursor" => json!({"additional_context": READS}),
        "copilot" => json!({"additionalContext": READS}),
        _ => json!({"hookSpecificOutput": {"hookEventName": if agent == "gemini" { "AfterTool" } else { "PostToolUse" }, "additionalContext": READS}}),
    }
}

fn run() -> Option<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut agent = args.iter().position(|a| a == "--agent").and_then(|i| args.get(i + 1)).cloned().unwrap_or_default();
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input).ok()?;
    let data = match serde_json::from_str::<Value>(&input).ok()? { Value::Object(m) => m, _ => return None };
    if agent.is_empty() { agent = detect(&data).to_string(); }
    let (session, tool, given) = normalise(&agent, &data);
    if session.is_empty() { return None; }
    let mut call = text(given.get("command"));
    if call.is_empty() { call = text(given.get("file_path")); }
    if call.is_empty() { call = text(given.get("path")); }
    let dir = std::env::var("MAP_COACH_DIR").map(std::path::PathBuf::from).unwrap_or_else(|_| std::env::temp_dir().join("map-coach"));
    let name: String = session.chars().filter(|c| c.is_ascii_alphanumeric() || *c == '_').take(64).collect();
    let sub: String = text(data.get("agent_id")).chars().filter(|c| c.is_ascii_alphanumeric() || *c == '_').take(32).collect();   // a subagent counts its own reads
    let name = if sub.is_empty() { name } else { format!("{}-{}", name, sub) };
    let file = dir.join(format!("{}.json", name));
    let state: Value = std::fs::read_to_string(&file).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or(Value::Null);
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0);
    let at = state.get("at").and_then(|v| v.as_f64()).unwrap_or(0.0);
    if !call.is_empty() && text(state.get("last")) == call && now - at >= 0.0 && now - at < AGAIN { return None; }   // the same call, from a second source
    let mut reads = state.get("reads").and_then(|r| r.as_f64()).unwrap_or(0.0) as i64;
    reads = if kind(&tool, &given) == "map" { reads + 1 } else { 0 };
    std::fs::create_dir_all(&dir).ok()?;
    if let Ok(entries) = std::fs::read_dir(&dir) {
        for e in entries.flatten() {
            if let Ok(m) = e.metadata() {
                if m.modified().ok().and_then(|t| t.elapsed().ok()).map(|d| d.as_secs() > 3 * 86400).unwrap_or(false) { let _ = std::fs::remove_file(e.path()); }
            }
        }
    }
    let tmp = dir.join(format!("{}.json.{}", name, std::process::id()));
    std::fs::write(&tmp, json!({"reads": reads, "last": call, "at": now}).to_string()).ok()?;
    std::fs::rename(&tmp, &file).ok()?;
    if reads == 3 { println!("{}", answer(&agent)); }
    Some(())
}

fn main() { let _ = run(); }
// @end map.coach.remind
