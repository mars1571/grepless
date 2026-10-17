// @map map.coach.remind: once and in the moment, after three reads of the map in a row, the reminder to ask every question of a round in one call
//! map-coach: a post-tool hook (Claude Code's PostToolUse, Codex's too) that reminds the agent of the working loop
//! when it drifts from it, once each time and never blocking. The Rust version of python/map-coach.py.
use regex::Regex;
use serde_json::{json, Value};
use std::io::Read;

const READS: &str = "Three reads of the map in a row (AGENTS.md, \"Finding code\"): ask in one call every question you can already name, the blocks, names and line ranges these answers point to, and send the calls that do not depend on each other in one message.";

fn kind(tool: &str, given: &Value) -> &'static str {
    if tool != "Bash" { return "work"; }
    let cmd = given.get("command").and_then(|c| c.as_str()).unwrap_or("");
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
    let map_script = Regex::new(r"map(?:\.py|\.mjs)$|(?:^|/)map$").unwrap();
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
        if matches!(w[0].as_str(), "python3" | "python" | "node") && w.get(1).map(|x| map_script.is_match(x)).unwrap_or(false) { reads += 1; }
        else if map_script.is_match(&w[0]) { reads += 1; }
        else if quiet.contains(&w[0].as_str()) { quiet_n += 1; }
    }
    if reads > 0 && reads + quiet_n == words.len() { "map" } else { "work" }
}

fn run() -> Option<()> {
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input).ok()?;
    let data: Value = serde_json::from_str(&input).ok()?;
    if data.get("agent_id").is_some() { return None; }
    let sid = data.get("session_id")?.as_str()?.to_string();
    let k = kind(data.get("tool_name").and_then(|t| t.as_str()).unwrap_or(""), data.get("tool_input").unwrap_or(&Value::Null));
    let dir = std::env::var("MAP_COACH_DIR").map(std::path::PathBuf::from).unwrap_or_else(|_| std::env::temp_dir().join("map-coach"));
    let name: String = sid.chars().filter(|c| c.is_alphanumeric() || *c == '_').take(64).collect();
    let file = dir.join(format!("{}.json", name));
    let mut reads: i64 = std::fs::read_to_string(&file).ok().and_then(|t| serde_json::from_str::<Value>(&t).ok()).and_then(|v| v.get("reads").and_then(|r| r.as_i64())).unwrap_or(0);
    reads = if k == "map" { reads + 1 } else { 0 };
    std::fs::create_dir_all(&dir).ok()?;
    if let Ok(entries) = std::fs::read_dir(&dir) {
        for e in entries.flatten() {
            if let Ok(m) = e.metadata() {
                if m.modified().ok().and_then(|t| t.elapsed().ok()).map(|d| d.as_secs() > 3 * 86400).unwrap_or(false) { let _ = std::fs::remove_file(e.path()); }
            }
        }
    }
    let tmp = dir.join(format!("{}.json.{}", name, std::process::id()));
    std::fs::write(&tmp, json!({"reads": reads}).to_string()).ok()?;
    std::fs::rename(&tmp, &file).ok()?;
    if reads == 3 {
        println!("{}", json!({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": READS}}));
    }
    Some(())
}

fn main() { let _ = run(); }
// @end map.coach.remind
