// @map map.recipes.steps: recipes from map.json, the steps of a change across layers, each checked against a block that still exists; plans whose parts can run at once
use crate::config::*;
use crate::imports::Graph;
use crate::parse::{everything, Block, Problem};
use regex::Regex;
use serde_json::Value;
use std::collections::{HashMap, HashSet};

fn steps(r: &Value) -> Vec<(String, String)> {
    r.get("steps").and_then(|s| s.as_array()).map(|a| a.iter().map(|e| {
        let parts: Vec<String> = e.as_array().map(|p| p.iter().map(|x| x.as_str().unwrap_or("").to_string()).collect()).unwrap_or_default();
        (parts.first().cloned().unwrap_or_default(), parts.get(1).cloned().unwrap_or_default())
    }).collect()).unwrap_or_default()
}

fn s(v: &Value, k: &str) -> String { v.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string() }

pub fn recipe(name: &str) {
    let rs = &cfg().recipes;
    let r = rs.get(name);
    if name.is_empty() || r.is_none() {
        if !name.is_empty() {
            print(&format!("No recipe {}.", name));
        }
        for (key, v) in rs {
            print(&format!("{} {}", pad_r(key, 15), s(v, "about")));
        }
        if rs.is_empty() {
            print("No recipes in map.json yet (docs/CONFIG.md says how to write one).");
        }
        return;
    }
    let r = r.unwrap();
    let (blocks, _, _) = everything();
    let mut sorted_blocks: Vec<&Block> = blocks.iter().collect();
    sorted_blocks.sort_by(|a, b| a.path.cmp(&b.path));
    let mut at: HashMap<String, String> = HashMap::new();
    for b in sorted_blocks {
        at.entry(b.id.clone()).or_insert_with(|| format!("{}:{}-{}", b.path, b.first, b.last));
    }
    let mut head = format!("{}: {}.", name, s(r, "about"));
    let checked = s(r, "checked");
    if !checked.is_empty() { head.push_str(&format!(" Checked against {}.", checked)); }
    print(&head);
    for (i, (target, what)) in steps(r).iter().enumerate() {
        print(&format!("{}\n   {}", format!("{}. {}  {}", i + 1, target, at.get(target).cloned().unwrap_or_default()).trim_end(), what));
    }
    let note = s(r, "note");
    if !note.is_empty() { print(&format!("Note: {}", note)); }
}

pub fn recipes_matching(words: &[String]) -> Vec<(String, String)> {
    let mut out = Vec::new();
    for (key, r) in &cfg().recipes {
        let mut mine: HashSet<String> = r.get("words").map(|w| match w { Value::String(x) => x.clone(), other => other.to_string() }).unwrap_or_default().split_whitespace().map(String::from).collect();
        mine.extend(key.split('-').map(String::from));
        if words.iter().filter(|w| mine.contains(*w)).count() >= 2 {
            out.push((key.clone(), s(r, "about")));
        }
    }
    out
}

pub fn recipe_problems(blocks: &[Block]) -> Vec<Problem> {
    let ids: HashSet<&String> = blocks.iter().map(|b| &b.id).collect();
    let mut out = Vec::new();
    for (key, r) in &cfg().recipes {
        for (target, _) in steps(r) {
            if target.contains('/') || target.ends_with(".md") || target.ends_with(".txt") {
                if !exists(&target) {
                    out.push(Problem { path: "map.json".into(), line: 0, text: format!("recipe {} names {}, which is not in the repository", key, target) });
                }
            } else if !ids.contains(&target) {
                out.push(Problem { path: "map.json".into(), line: 0, text: format!("recipe {} names the block {}, which no file tags: find where it went ({} find …)", key, target, cmd()) });
            }
        }
    }
    out
}

const SHARED: [&str; 5] = ["map/", "map.yaml", "CHANGELOG", "changes/", "docs/plans/"];

pub fn plan(path: &str) {
    let text = std::fs::read_to_string(path).unwrap_or_else(|e| die(&format!("{}: {}", path, e)));
    let part_rx = Regex::new(r"^## Part (\d+)\b[:.\s-]*(.*)").unwrap();
    let files_rx = Regex::new(r"^\s*-\s*Files:(.*)").unwrap();
    let split = Regex::new(r"[\s,]+").unwrap();
    let mut parts: Vec<(usize, String, HashSet<String>)> = Vec::new();
    let mut current: Option<usize> = None;
    for line in text.split('\n') {
        if let Some(m) = part_rx.captures(line) {
            parts.push((m[1].parse().unwrap_or(0), m[2].trim().to_string(), HashSet::new()));
            current = Some(parts.len() - 1);
        } else if line.starts_with("## ") {
            current = None;
        } else if let (Some(ci), Some(m)) = (current, files_rx.captures(line)) {
            for w in split.split(&m[1]) {
                let x = w.trim_matches(|c: char| "`*,;:()[]".contains(c)).trim_end_matches('.');
                if !x.is_empty() && (x.contains('/') || is_file(x)) {
                    parts[ci].2.insert(x.to_string());
                }
            }
        }
    }
    if parts.is_empty() {
        die(&format!("{}: no \"## Part <n>: …\" sections with a \"- Files:\" line each", path));
    }
    let (blocks, _, _) = everything();
    let g = Graph::new(&blocks);
    print(&format!("{}: {} parts", path, parts.len()));
    let mut apart: Vec<(usize, usize)> = Vec::new();
    for i in 0..parts.len() {
        for j in i + 1..parts.len() {
            let (a, b) = (&parts[i], &parts[j]);
            let mut common: Vec<&String> = a.2.iter().filter(|f| b.2.contains(*f) && !SHARED.iter().any(|s| f.starts_with(s))).collect();
            common.sort();
            let mut why = if common.is_empty() { String::new() } else { format!("both change {}", common.iter().map(|s| s.as_str()).collect::<Vec<_>>().join(", ")) };
            if why.is_empty() {
                'outer: for (x, y) in [(a, b), (b, a)] {
                    for f in sorted(&x.2) {
                        if g.file_edges.get(&f).map(|ts| ts.iter().any(|t| y.2.contains(t))).unwrap_or(false) {
                            why = format!("part {} imports what part {} changes ({})", x.0, y.0, f);
                            break 'outer;
                        }
                    }
                }
            }
            if why.is_empty() {
                print(&format!("  {} and {}: at once", a.0, b.0));
                apart.push((a.0, b.0));
            } else {
                print(&format!("  {} and {}: one after the other: {}", a.0, b.0, why));
            }
        }
    }
    if apart.is_empty() {
        print("No two parts can run at once: one agent after another, in order.");
    } else {
        print(&format!("At once: {} (each agent in a worktree of its own: git worktree add ../<name>-<part> -b <branch>)", apart.iter().map(|(a, b)| format!("{} with {}", a, b)).collect::<Vec<_>>().join(", ")));
    }
}
// @end map.recipes.steps
