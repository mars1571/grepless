// @map map.sessions.read: a Claude Code transcript's model calls: the context each re-read, whether it only searched or read, its response time
//! map-sessions: how the agents' sessions on this repository went, read from Claude Code's transcripts. The Rust
//! version of python/map-sessions.py, the same columns.   map-sessions [--since YYYY-MM-DD] [session-id-prefix …]
use mapcore::guard;
use regex::Regex;
use serde_json::{Map, Value};
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;

fn looks(tool: &str, given: &Value) -> Option<&'static str> {
    if matches!(tool, "Read" | "Grep" | "Glob") { return Some("other"); }
    if tool != "Bash" { return None; }
    let look: HashSet<&str> = "grep egrep fgrep rg ag ack cat sed head tail awk nl less more ls find tree wc cut sort uniq tr xargs column echo printf".split(' ').collect();
    let mut line = given.get("command").and_then(|c| c.as_str()).unwrap_or("").to_string();
    if Regex::new(r"map(?:\.py|\.mjs)?\s+(ask|brief|find|history|deps|impact|recipe|where)\b").unwrap().is_match(&line) { return Some("map"); }
    line = Regex::new(r"\d?>&\d|\d?>\s*/dev/null").unwrap().replace_all(&line, " ").to_string();
    if Regex::new(r"\bsed\s+-i|>\s*\S|\bnode\b|\bmake\b|\bnpx\b").unwrap().is_match(&line) { return None; }
    for m in Regex::new(r"\bpython3?\s+(\S*)").unwrap().captures_iter(&line) { if !m[1].ends_with("map.py") { return None; } }
    let padded = line.replace('|', " | ").replace(';', " ; ").replace("&&", " && ");
    let words: Vec<&str> = padded.split_whitespace().collect();
    let firsts: Vec<&str> = words.iter().enumerate().filter(|(k, _)| *k == 0 || matches!(words[k - 1], "|" | ";" | "&&" | "||")).map(|(_, w)| *w).collect();
    if !firsts.is_empty() && firsts.iter().all(|w| look.contains(w.rsplit('/').next().unwrap_or("")) || *w == "cd") { Some("other") } else { None }
}

fn questions(line: &str) -> Vec<usize> {
    let ask = Regex::new(r"map(?:\.py|\.mjs)?\s+ask\s+").unwrap();
    let stop = Regex::new(r"\d?>&\d|\||;|&&|\n").unwrap();
    ask.find_iter(line).map(|m| {
        let rest = &line[m.end()..];
        let end = stop.find(rest).map(|s| s.start()).unwrap_or(rest.len());
        let words: Vec<&str> = rest[..end].split_whitespace().collect();
        words.iter().enumerate().filter(|(k, w)| !w.starts_with("--") && (*k == 0 || words[k - 1] != "--in")).count()
    }).collect()
}

fn stamp(s: &str) -> Option<f64> {
    // ISO 8601 with a Z or an offset, parsed by hand: seconds since the epoch, fractional seconds kept.
    let re = Regex::new(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})?$").unwrap();
    let m = re.captures(s)?;
    let (y, mo, d): (i64, i64, i64) = (m[1].parse().ok()?, m[2].parse().ok()?, m[3].parse().ok()?);
    let (h, mi, se): (i64, i64, i64) = (m[4].parse().ok()?, m[5].parse().ok()?, m[6].parse().ok()?);
    let frac: f64 = m.get(7).map(|f| format!("0.{}", f.as_str()).parse().unwrap_or(0.0)).unwrap_or(0.0);
    let (y1, m1) = if mo <= 2 { (y - 1, mo + 12) } else { (y, mo) };
    let days = 365 * y1 + y1 / 4 - y1 / 100 + y1 / 400 + (153 * (m1 - 3) + 2) / 5 + d - 1 - 719468;
    let mut secs = (days * 86400 + h * 3600 + mi * 60 + se) as f64 + frac;
    if let Some(off) = m.get(8) {
        let o = off.as_str();
        if o != "Z" { let sign = if o.starts_with('-') { -1.0 } else { 1.0 }; let oh: f64 = o[1..3].parse().unwrap_or(0.0); let om: f64 = o[4..6].parse().unwrap_or(0.0); secs -= sign * (oh * 3600.0 + om * 60.0); }
    }
    Some(secs)
}

struct Call { ctx: u64, kinds: Vec<Option<&'static str>>, since: Option<f64>, last: Option<f64> }

fn calls(path: &PathBuf) -> (Vec<(u64, Option<&'static str>, Option<f64>)>, Vec<usize>, usize) {
    let text = std::fs::read_to_string(path).unwrap_or_default();
    let mut out: Vec<(String, Call)> = Vec::new();
    let mut asked = Vec::new();
    let mut uses: HashMap<String, (String, Map<String, Value>, String)> = HashMap::new();
    let mut refused: HashSet<String> = HashSet::new();
    let mut prev: Option<f64> = None;
    for line in text.lines() {
        let Ok(o) = serde_json::from_str::<Value>(line) else { continue };
        let m = o.get("message").cloned().unwrap_or(Value::Null);
        let t = o.get("timestamp").and_then(|x| x.as_str()).and_then(stamp);
        if let Some(content) = m.get("content").and_then(|c| c.as_array()) {
            for x in content {
                if x.get("type").and_then(|t| t.as_str()) == Some("tool_result") && x.get("content").map(|c| c.to_string()).unwrap_or_default().contains("through its map") {
                    refused.insert(x.get("tool_use_id").and_then(|i| i.as_str()).unwrap_or("").to_string());
                }
            }
        }
        let id = m.get("id").and_then(|i| i.as_str()).unwrap_or("").to_string();
        if o.get("type").and_then(|t| t.as_str()) != Some("assistant") || id.is_empty() { if t.is_some() { prev = t; } continue; }
        let cwd = o.get("cwd").and_then(|c| c.as_str()).unwrap_or(&guard::g().root.to_string_lossy()).to_string();
        if let Some(content) = m.get("content").and_then(|c| c.as_array()) {
            for x in content {
                if x.get("type").and_then(|t| t.as_str()) == Some("tool_use") {
                    let name = x.get("name").and_then(|n| n.as_str()).unwrap_or("").to_string();
                    let input = x.get("input").and_then(|i| i.as_object()).cloned().unwrap_or_default();
                    if name == "Bash" {
                        let n: usize = questions(input.get("command").and_then(|c| c.as_str()).unwrap_or("")).iter().sum();
                        if n > 0 { asked.push(n); }
                    }
                    uses.insert(x.get("id").and_then(|i| i.as_str()).unwrap_or("").to_string(), (name, input, cwd.clone()));
                }
            }
        }
        let u = m.get("usage").cloned().unwrap_or(Value::Null);
        let ctx: u64 = ["input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"].iter().map(|k| u.get(k).and_then(|v| v.as_u64()).unwrap_or(0)).sum();
        let idx = match out.iter().position(|(k, _)| *k == id) { Some(i) => i, None => { out.push((id.clone(), Call { ctx: 0, kinds: vec![], since: prev, last: t })); out.len() - 1 } };
        let c = &mut out[idx].1;
        if t.is_some() { c.last = t; }
        c.ctx = c.ctx.max(ctx);
        if let Some(content) = m.get("content").and_then(|c| c.as_array()) {
            for x in content {
                if x.get("type").and_then(|t| t.as_str()) == Some("tool_use") {
                    c.kinds.push(looks(x.get("name").and_then(|n| n.as_str()).unwrap_or(""), x.get("input").unwrap_or(&Value::Null)));
                }
            }
        }
        if t.is_some() { prev = t; }
    }
    let mut outside = 0;
    for (id, (name, input, cwd)) in &uses {
        if refused.contains(id) { continue; }
        let mut data = Map::new();
        data.insert("tool_name".into(), Value::String(name.clone()));
        data.insert("tool_input".into(), Value::Object(input.clone()));
        data.insert("cwd".into(), Value::String(cwd.clone()));
        if guard::replacement("claude", &data).is_some() { outside += 1; }
    }
    let rows = out.into_iter().map(|(_, c)| {
        let kind = if c.kinds.is_empty() || c.kinds.contains(&None) { None } else if c.kinds.contains(&Some("map")) { Some("map") } else { Some("other") };
        let secs = match (c.since, c.last) { (Some(a), Some(b)) if b - a > 0.0 && b - a < 600.0 => Some(b - a), _ => None };
        (c.ctx, kind, secs)
    }).collect();
    (rows, asked, outside)
}

fn median(xs: &[f64]) -> Option<f64> { if xs.is_empty() { return None; } let mut s = xs.to_vec(); s.sort_by(|a, b| a.partial_cmp(b).unwrap()); Some(s[s.len() / 2]) }
fn f1(x: Option<f64>) -> String { x.map(|v| format!("{:.1}", v)).unwrap_or_else(|| "-".into()) }

fn first_stamp(p: &PathBuf) -> String {
    std::fs::read_to_string(p).unwrap_or_default().lines().find(|l| l.contains("\"timestamp\"")).and_then(|l| serde_json::from_str::<Value>(l).ok())
        .and_then(|v| v.get("timestamp").and_then(|t| t.as_str()).map(String::from)).unwrap_or_default()
}

fn report(paths: &[PathBuf]) {
    println!("{:<19}{:>6}{:>8}{:>16}{:>8}{:>8}{:>6}{:>6}{:>8}{:>8}{:>8}{:>8}", "session", "calls", "read M", "search/read", "their M", "via map", "asks", "q/ask", "outside", "runs 8+", "s <300k", "s >300k");
    let mut total = [0u64; 9];
    let (mut all_lo, mut all_hi) = (Vec::new(), Vec::new());
    let line = |name: &str, r: &[u64; 9], lo: &[f64], hi: &[f64]| {
        let per_ask = if r[5] > 0 { r[6] as f64 / r[5] as f64 } else { 0.0 };
        println!("{:<19}{:>6}{:>8.1}{:>9} ({:>3}%){:>8.1}{:>8}{:>6}{:>6.1}{:>8}{:>8}{:>8}{:>8}", name, r[0], r[1] as f64 / 1e6, r[2], (100.0 * r[2] as f64 / r[0] as f64).round() as u64, r[3] as f64 / 1e6, r[4], r[5], per_ask, r[7], r[8], f1(median(lo)), f1(median(hi)));
    };
    for p in paths {
        let (cs, asked, outside) = calls(p);
        if cs.is_empty() { continue; }
        let mut r = [0u64; 9];
        r[0] = cs.len() as u64;
        let (mut runs, mut run) = (0u64, 0u64);
        let (mut lo, mut hi) = (Vec::new(), Vec::new());
        for (ctx, kind, secs) in &cs {
            r[1] += ctx;
            if kind.is_some() { r[2] += 1; r[3] += ctx; if *kind == Some("map") { r[4] += 1; } run += 1; } else { if run >= 8 { runs += 1; } run = 0; }
            if let Some(s) = secs { if *ctx < 300000 { lo.push(*s); } else { hi.push(*s); } }
        }
        if run >= 8 { runs += 1; }
        r[5] = asked.len() as u64;
        r[6] = asked.iter().sum::<usize>() as u64;
        r[7] = outside as u64;
        r[8] = runs;
        for k in 0..9 { total[k] += r[k]; }
        all_lo.extend(lo.iter());
        all_hi.extend(hi.iter());
        let day: String = first_stamp(p).chars().take(10).collect();
        let stem: String = p.file_stem().map(|s| s.to_string_lossy().chars().take(8).collect()).unwrap_or_default();
        line(&format!("{} {}", day, stem), &r, &lo, &hi);
    }
    if total[0] > 0 { line("all", &total, &all_lo, &all_hi); }
}

fn main() {
    guard::setup();
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut since = String::new();
    let mut named = Vec::new();
    let mut i = 0;
    while i < args.len() {
        if args[i] == "--since" && i + 1 < args.len() { since = args[i + 1].clone(); i += 2; } else { named.push(args[i].clone()); i += 1; }
    }
    let home = std::env::var("HOME").unwrap_or_default();
    let projects = PathBuf::from(home).join(".claude").join("projects");
    let slug = guard::g().root.to_string_lossy().replace('/', "-").replace('.', "-");
    let mut found: Vec<PathBuf> = Vec::new();
    if let Ok(entries) = std::fs::read_dir(&projects) {
        for e in entries.flatten() {
            if e.file_name().to_string_lossy().starts_with(&slug) && e.path().is_dir() {
                for f in std::fs::read_dir(e.path()).into_iter().flatten().flatten() {
                    if f.file_name().to_string_lossy().ends_with(".jsonl") { found.push(f.path()); }
                }
            }
        }
    }
    found.sort_by_key(|p| std::fs::metadata(p).and_then(|m| m.modified()).ok());
    if !named.is_empty() {
        found = named.iter().flat_map(|a| if a.ends_with(".jsonl") { vec![PathBuf::from(a)] } else { found.iter().filter(|p| p.file_name().map(|n| n.to_string_lossy().starts_with(a.as_str())).unwrap_or(false)).cloned().collect() }).collect();
    }
    if found.is_empty() {
        eprintln!("No transcripts for {} under {} (Claude Code writes them there).", guard::g().root.display(), projects.display());
        std::process::exit(1);
    }
    let mut seen = HashSet::new();
    let paths: Vec<PathBuf> = found.into_iter().filter(|p| seen.insert(p.clone())).filter(|p| since.is_empty() || first_stamp(p) >= since).collect();
    report(&paths);
}
// @end map.sessions.read
