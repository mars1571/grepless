// @map map.query.find: find by words or by an identifier, where, gaps, history from git, deps and impact from imports, tests
use crate::ask::{declarations, Repo};
use crate::config::*;
use crate::files::*;
use crate::imports::Graph;
use crate::parse::{everything, facts, save_cache, Block};
use crate::write::test_files;
use indexmap::IndexMap;
use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::process::Command;
use std::sync::OnceLock;

pub fn identifier(w: &str) -> bool {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| Regex::new(r"[a-z][A-Z]|[A-Za-z0-9]-[A-Za-z0-9]|_|^[#.][A-Za-z]|^--").unwrap()).is_match(w)
}

const SHOWN: usize = 15;

fn has_word(text: &str, w: &str) -> bool { lower_words(text).iter().any(|h| h.starts_with(w)) }
fn count_words(text: &str, words: &[String]) -> usize { words.iter().filter(|w| has_word(text, w)).count() }

pub fn find(args: &[String]) {
    let (blocks, _, _) = everything();
    let raw: Vec<String> = args.iter().flat_map(|a| a.split_whitespace().map(String::from)).collect();
    let words: Vec<String> = raw.iter().filter(|x| !identifier(x) || raw.len() == 1).map(|x| x.to_lowercase()).collect();
    let mut said = false;
    if raw.len() == 1 || raw.iter().any(|w| identifier(w)) {
        let repo = Repo::new(Some(blocks.clone()));
        for w in &raw {
            if raw.len() == 1 || identifier(w) {
                for d in declarations(&repo, w.trim_start_matches(['#', '.'])).iter().take(5) {
                    let mut wh = repo.where_(&d.path, d.first, 0);
                    if wh.is_empty() { wh = d.path.clone(); }
                    print(&format!("{}: {}, declared in {}  {}:{}-{}", w, d.what, wh, d.path, d.first, d.last));
                    said = true;
                }
            }
        }
    }
    let mut hits: Vec<&Block> = if words.is_empty() { vec![] } else {
        blocks.iter().filter(|b| words.iter().all(|w| has_word(&format!("{} {} {}", b.id, b.purpose, b.path), w))).collect()
    };
    hits.sort_by(|a, b| {
        let ka = (-(count_words(&a.id, &words) as i64), is_test(&a.path) as i64, -(count_words(&a.purpose, &words) as i64));
        let kb = (-(count_words(&b.id, &words) as i64), is_test(&b.path) as i64, -(count_words(&b.purpose, &words) as i64));
        ka.cmp(&kb).then(a.path.cmp(&b.path)).then(a.first.cmp(&b.first))
    });
    if said && raw.len() == 1 {
        hits.retain(|b| has_word(&b.id, &words[0]));
    }
    for b in hits.iter().take(SHOWN) {
        let r: Vec<char> = b.purpose.chars().collect();
        let purpose = if r.len() <= 120 { b.purpose.clone() } else {
            let mut cut = 0;
            let mut i = 118i64;
            while i >= 0 { if r[i as usize] == ' ' { cut = i as usize; break; } i -= 1; }
            format!("{}…", r[..cut].iter().collect::<String>())
        };
        print(&format!("{} {}:{}-{} ({} lines)  {}", pad_r(&b.id, 44), b.path, b.first, b.last, b.lines, purpose));
    }
    if hits.len() > SHOWN {
        print(&format!("… {} more: add a word to narrow them", hits.len() - SHOWN));
    }
    if hits.is_empty() && !said {
        print(&format!("No block matches. Try fewer words, or the code's text: {} ask '<text>'", cmd()));
    }
}

pub fn matching<'a>(id: &str, blocks: &'a [Block]) -> Vec<&'a Block> {
    blocks.iter().filter(|b| b.id == id || b.id.starts_with(&format!("{}.", id))).collect()
}

pub fn where_cmd(id: &str) {
    let (blocks, _, _) = everything();
    let hits = matching(id, &blocks);
    for b in &hits {
        print(&format!("{} {}:{}-{} ({} lines)", pad_r(&b.id, 44), b.path, b.first, b.last, b.lines));
    }
    if hits.is_empty() {
        die(&format!("No block {}. Search with: {} find <words>", id, cmd()));
    }
}

pub fn gaps(paths: &[String]) {
    let every = files();
    let chosen: Vec<&String> = if paths.is_empty() { every.iter().collect() } else {
        every.iter().filter(|f| paths.iter().any(|p| *f == p || f.starts_with(&format!("{}/", p.trim_end_matches('/'))))).collect()
    };
    let (mut untagged, mut printed) = (0, false);
    for p in &chosen {
        let f = facts(p);
        let big: Vec<&Block> = f.blocks.iter().filter(|b| b.own > cfg().block).collect();
        let elsewhere: HashSet<String> = f.blocks.iter().map(|b| b.id.split('.').next().unwrap().to_string()).filter(|a| *a != area_of(p)).collect();
        if f.blocks.is_empty() {
            untagged += 1;
            printed = true;
            let decls: Vec<&String> = f.decls.iter().filter(|d| matches!(d.kind.as_str(), "function" | "class" | "method")).map(|d| &d.name).collect();
            let mut line = format!("{}: no tags ({} lines; area {}", p, f.outside.len(), area_of(p));
            if !decls.is_empty() {
                line.push_str(&format!("; declares {}", decls.iter().take(6).map(|s| s.as_str()).collect::<Vec<_>>().join(", ")));
                if decls.len() > 6 { line.push_str(" …"); }
            }
            print(&format!("{})", line));
        } else if f.outside.len() > cfg().untagged || !big.is_empty() || !f.problems.is_empty() || !elsewhere.is_empty() {
            printed = true;
            let mut line = format!("{}: {} blocks, {} lines outside", p, f.blocks.len(), f.outside.len());
            if !f.outside.is_empty() { line.push_str(&format!(" (from line {})", f.outside[0])); }
            print(&line);
            if !elsewhere.is_empty() {
                print(&format!("  note: blocks of {} live in this file", sorted(&elsewhere).join(", ")));
            }
            for b in big {
                print(&format!("  split {} (lines {}-{}, {} characters of its own)", b.id, b.first, b.last, commas(b.own)));
            }
            for (n, text) in &f.problems {
                print(&format!("  line {}: {}", n, text));
            }
        }
    }
    save_cache();
    if untagged > 0 {
        print(&format!("{} of {} files carry no tag: docs/TAGGING.md says how to tag them with an agent", untagged, chosen.len()));
    } else if !printed {
        print(&format!("All {} code files are tagged, no block to split, no problem.", chosen.len()));
    }
}

pub fn git(args: &[&str]) -> String {
    Command::new("git").arg("-C").arg(root()).args(args).output().map(|o| String::from_utf8_lossy(&o.stdout).to_string()).unwrap_or_default()
}

pub fn history(what: &str) {
    let (blocks, _, _) = everything();
    let mut hits: Vec<Block> = blocks.iter().filter(|b| b.id == what).cloned().collect();
    if hits.is_empty() {
        hits = matching(what, &blocks).into_iter().take(3).cloned().collect();
    }
    if hits.is_empty() && is_file(what) {
        hits = vec![Block { id: what.into(), purpose: String::new(), first: 0, last: 0, path: what.into(), own: 0, lines: 0 }];
    }
    if hits.is_empty() {
        die(&format!("No block or file {}. Search with: {} find <words>", what, cmd()));
    }
    for b in &hits {
        let raw = if b.first == 0 {
            git(&["log", "-n", "12", "--format=%h %ad %s", "--date=short", "--", &b.path])
        } else {
            git(&["log", "-s", "-n", "12", "--format=%h %ad %s", "--date=short", &format!("-L{},{}:{}", b.first, b.last, b.path)])
        };
        let lines: Vec<&str> = raw.split('\n').filter(|l| !l.trim().is_empty()).collect();
        let mut head = format!("{}  {}", b.id, b.path);
        if b.first != 0 { head.push_str(&format!(":{}-{}", b.first, b.last)); }
        head.push_str(&format!(": {} commits", lines.len()));
        head.push_str(if lines.is_empty() { " (not in git, or no history yet)" } else { ", latest first" });
        print(&head);
        for l in lines {
            print(&format!("  {}", l));
        }
    }
}

pub fn deps(what: &str) {
    let (blocks, _, _) = everything();
    let g = Graph::new(&blocks);
    let mut paths: HashSet<String> = matching(what, &blocks).iter().map(|b| b.path.clone()).collect();
    if paths.is_empty() && (g.file_edges.contains_key(what) || is_file(what)) {
        paths.insert(what.into());
    }
    if paths.is_empty() {
        die(&format!("No block or file {}.", what));
    }
    for p in sorted(&paths) {
        let ts: Vec<String> = g.file_edges.get(&p).map(sorted).unwrap_or_default();
        print(&format!("{} imports {} files of the repository{}", p, ts.len(), if ts.is_empty() { "" } else { ":" }));
        for t in &ts {
            print(&format!("  {}  {}", t, g.main.get(t).cloned().unwrap_or_default()));
        }
    }
}

/// The test files that import these files (one step, then one more) or name one of them or of the names.
pub fn reaching(g: &Graph, paths: &[String], names: &HashSet<String>) -> IndexMap<String, String> {
    let ps: HashSet<&String> = paths.iter().collect();
    let mut direct: HashSet<String> = HashSet::new();
    for p in paths {
        if let Some(s) = g.importers.get(p) {
            for x in s { if !ps.contains(x) { direct.insert(x.clone()); } }
        }
    }
    let mut second: HashSet<String> = HashSet::new();
    for p in &direct {
        if let Some(s) = g.importers.get(p) {
            for x in s { if !ps.contains(x) && !direct.contains(x) { second.insert(x.clone()); } }
        }
    }
    let mut found: IndexMap<String, String> = IndexMap::new();
    let tests = test_files();
    for t in &tests {
        if ps.contains(t) {
            found.insert(t.clone(), "the test itself".into());
        } else if direct.contains(t) {
            let mut both: Vec<&String> = g.file_edges[t].iter().filter(|x| ps.contains(x)).collect();
            both.sort();
            found.insert(t.clone(), format!("imports {}", both.iter().take(2).map(|s| s.as_str()).collect::<Vec<_>>().join(", ")));
        } else if second.contains(t) {
            found.insert(t.clone(), "imports what imports it".into());
        }
    }
    let mut short_names: HashSet<String> = paths.iter().map(|p| p.rsplit('/').next().unwrap().to_string()).filter(|n| n.len() > 6).collect();
    short_names.extend(names.iter().cloned());
    for t in &tests {
        if found.contains_key(t) { continue; }
        let text = read_file(t);
        if paths.iter().any(|p| text.contains(p.as_str())) || short_names.iter().any(|n| bounded(&text, n, ".", "-")) {
            found.insert(t.clone(), "names it".into());
        }
    }
    found
}

pub fn impact(what: &str) {
    let (blocks, _, _) = everything();
    let g = Graph::new(&blocks);
    let mut mine: HashSet<String> = matching(what, &blocks).iter().map(|b| b.path.clone()).collect();
    if mine.is_empty() && is_file(what) {
        mine.insert(what.into());
    }
    if mine.is_empty() {
        die(&format!("No block or file {}.", what));
    }
    let mut direct: HashSet<String> = HashSet::new();
    for p in &mine {
        if let Some(s) = g.importers.get(p) { for x in s { if !mine.contains(x) { direct.insert(x.clone()); } } }
    }
    let mut second: HashSet<String> = HashSet::new();
    for p in &direct {
        if let Some(s) = g.importers.get(p) { for x in s { if !mine.contains(x) && !direct.contains(x) { second.insert(x.clone()); } } }
    }
    print(&format!("{} files import {} directly{}", direct.len(), what, if direct.is_empty() { "." } else { ":" }));
    for p in sorted(&direct) {
        print(&format!("  {}  {}", p, g.main.get(&p).cloned().unwrap_or_default()));
    }
    if !second.is_empty() {
        let keys = sorted(&second);
        print(&format!("{} more import those: {}{}", second.len(), keys.iter().take(12).map(|s| s.as_str()).collect::<Vec<_>>().join(", "), if keys.len() > 12 { " …" } else { "" }));
    }
    let names: HashSet<String> = matching(what, &blocks).iter().map(|b| component(&b.id)).collect();
    let mut tests: Vec<String> = reaching(&g, &sorted(&mine), &names).keys().cloned().collect();
    tests.sort();
    if tests.is_empty() {
        print("Tests that reach it (0): none import or name it; run the suite");
    } else {
        print(&format!("Tests that reach it ({}): {}", tests.len(), tests.join(" ")));
    }
}

pub fn changed() -> Vec<String> {
    git(&["status", "--porcelain=v1", "-z", "--untracked-files=all"]).split('\0').filter(|e| e.len() > 3).map(|e| e[3..].split('\0').next().unwrap().to_string()).collect()
}

pub fn tests(args: &[String]) {
    let paths: Vec<String> = if args.is_empty() || (args.len() == 1 && args[0] == "--changed") { changed() } else { args.to_vec() };
    if paths.is_empty() {
        print("Nothing changed: no test to run.");
        return;
    }
    let (blocks, _, _) = everything();
    let g = Graph::new(&blocks);
    let mut chosen: IndexMap<String, String> = IndexMap::new();
    let mut sorted_paths = paths.clone();
    sorted_paths.sort();
    for p in &sorted_paths {
        let ids: HashSet<String> = g.by_file.get(p).map(|bs| bs.iter().map(|b| component(&b.id)).collect()).unwrap_or_default();
        let found = reaching(&g, std::slice::from_ref(p), &ids);
        for (t, why) in &found {
            chosen.entry(t.clone()).or_insert_with(|| why.clone());
        }
        print(&format!("  {}: {} test file{}", p, found.len(), if found.len() != 1 { "s" } else { "" }));
    }
    if chosen.is_empty() {
        print("No test file imports or names these files.");
    } else {
        let mut keys: Vec<&String> = chosen.keys().collect();
        keys.sort();
        print(&format!("Run: {}", keys.iter().map(|s| s.as_str()).collect::<Vec<_>>().join(" ")));
        for t in keys {
            print(&format!("  {}  ({})", t, chosen[t]));
        }
    }
}

pub fn bool_usize(b: bool) -> usize { if b { 1 } else { 0 } }
pub fn _unused(_: &HashMap<String, String>) {}
// @end map.query.find
