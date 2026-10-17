// @map map.brief.print: where a task starts: the components its words name, ranked, each with its parts, declarations, relations, tests, docs and commits
use crate::config::*;
use crate::files::*;
use crate::imports::Graph;
use crate::parse::{everything, facts, save_cache, Block};
use crate::query::git;
use crate::recipes::recipes_matching;
use crate::write::components;
use indexmap::IndexMap;
use std::collections::{HashMap, HashSet};

const STOP: &str = "a an and are as at be by can do does for from has have how i in into is it its me my new of on or our should so that the their them then there these this to us was we what when where which who why will with add change changes make fix use using want need needs";

pub fn words_in(args: &[String]) -> Vec<String> {
    let stop: HashSet<&str> = STOP.split(' ').collect();
    lower_words(&args.join(" ")).into_iter().filter(|w| !stop.contains(w.as_str()) && w.len() > 1).collect()
}

fn round9(x: f64) -> f64 { (x * 1e9).round() / 1e9 }

fn has_in(pool: &HashSet<String>, w: &str) -> bool {
    pool.iter().any(|h| h.starts_with(w) || (w.len() > 3 && w.ends_with('s') && h.starts_with(&w[..w.len() - 1])))
}

pub fn ranked<'a>(blocks: &'a [Block], g: &Graph, words: &[String]) -> Vec<(f64, &'a Block)> {
    let mut names: HashMap<String, HashSet<String>> = HashMap::new();
    for p in files() {
        for d in facts(p).decls {
            if d.kind == "heading" { continue; }
            if let Some(b) = g.at(p, d.first) {
                names.entry(b).or_default().extend(words_of(&d.name));
            }
        }
    }
    struct Pools<'a> { b: &'a Block, id: HashSet<String>, purpose: HashSet<String>, other: HashSet<String> }
    let mut seen: IndexMap<String, Pools> = IndexMap::new();
    for b in blocks {
        let mut other: HashSet<String> = lower_words(&b.path).into_iter().collect();
        if let Some(n) = names.get(&b.id) { other.extend(n.iter().cloned()); }
        seen.insert(format!("{}\0{}", b.id, b.path), Pools { b, id: words_of(&b.id), purpose: lower_words(&b.purpose).into_iter().collect(), other });
    }
    let mut df: HashMap<&String, usize> = HashMap::new();
    for w in words {
        let n = seen.values().filter(|p| {
            let all: HashSet<String> = p.id.iter().chain(p.purpose.iter()).chain(p.other.iter()).cloned().collect();
            has_in(&all, w)
        }).count();
        df.insert(w, n);
    }
    let mut out = Vec::new();
    for p in seen.values() {
        let mut s = 0.0;
        for w in words {
            let weight = if has_in(&p.id, w) { 3.0 } else if has_in(&p.purpose, w) { 2.0 } else if has_in(&p.other, w) { 1.0 } else { 0.0 };
            s += weight * (1.0 + seen.len() as f64 / (1.0 + df[w] as f64)).ln();
        }
        if s != 0.0 {
            if is_test(&p.b.path) { s -= 0.5; }
            out.push((round9(s), p.b));
        }
    }
    out.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap().then(a.1.path.cmp(&b.1.path)).then(a.1.first.cmp(&b.1.first)));
    out
}

pub fn brief(args: &[String]) {
    let words = words_in(args);
    if words.is_empty() {
        die("Say the task in a few words, as the code names things: brief cart totals discount");
    }
    let (blocks, _, untagged) = everything();
    let g = Graph::new(&blocks);
    let comps = components(&blocks, &g);
    let hits = ranked(&blocks, &g, &words);
    let mut per: IndexMap<String, Vec<(f64, &Block)>> = IndexMap::new();
    for (s, b) in &hits {
        if !is_test(&b.path) {
            per.entry(component(&b.id)).or_default().push((*s, b));
        }
    }
    let mut score: HashMap<String, f64> = HashMap::new();
    for (c, xs) in &per {
        let mut v = xs.clone();
        v.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
        let t: f64 = v.iter().take(3).enumerate().map(|(i, (s, _))| s * [1.0, 0.5, 0.25][i]).sum();
        score.insert(c.clone(), round9(t));
    }
    let mut order: Vec<String> = per.keys().cloned().collect();
    order.sort_by(|a, b| score[b].partial_cmp(&score[a]).unwrap());
    if order.is_empty() {
        die(&format!("No block matches those words. Try others, or {} find <word>.", cmd()));
    }
    let near: Vec<String> = order.iter().filter(|c| score[*c] >= 0.25 * score[&order[0]]).take(10).cloned().collect();
    let (chosen, also) = if near.len() > 3 { (near[..3].to_vec(), near[3..].to_vec()) } else { (near.clone(), vec![]) };
    print(&format!("brief {}: {} of {} components that match, best first. ask <id or name> reads a block.", words.join(" "), near.len(), order.len()));
    for (ci, c) in chosen.iter().enumerate() {
        let info = &comps[c];
        let fs = sorted(&info.files);
        print(&format!("\n{}  {}  [{}{}]", c, short(&info.what, 100), fs.iter().take(4).map(|s| s.as_str()).collect::<Vec<_>>().join(", "), if fs.len() > 4 { " …" } else { "" }));
        let mut xs = per[c].clone();
        xs.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
        let mut best: IndexMap<String, (&Block, usize)> = IndexMap::new();
        for (_, b) in &xs {
            best.entry(b.id.clone()).or_insert((b, 0)).1 += 1;
        }
        let limit = if ci < 2 { 5 } else { 3 };
        for (i, (b, n)) in best.values().take(limit).enumerate() {
            print(&format!("  {} {} {}:{}-{}{} — {}", if i == 0 { "parts:" } else { "      " }, b.id, b.path, b.first, b.last, if *n > 1 { format!(" (+{} files)", n - 1) } else { String::new() }, short(&b.purpose, 70)));
        }
        let decl = unique(&info.declares);
        if !decl.is_empty() {
            let about: Vec<&String> = decl.iter().filter(|d| words_of(d).iter().any(|h| words.iter().any(|w| h.starts_with(w.as_str())))).collect();
            let mut shown: Vec<&String> = about.clone();
            shown.extend(decl.iter().filter(|d| !about.contains(d)));
            print(&format!("  declares ({}): {}{}", decl.len(), shown.iter().take(8).map(|s| s.as_str()).collect::<Vec<_>>().join(", "), if decl.len() > 8 { " …" } else { "" }));
        }
        let top = |s: &HashSet<String>| -> String { let v = sorted(s); if v.is_empty() { String::new() } else { format!("{}{}", v.iter().take(5).map(|x| x.as_str()).collect::<Vec<_>>().join(", "), if v.len() > 5 { " …" } else { "" }) } };
        let (near_, by) = (top(&info.needs), top(&info.by));
        if !near_.is_empty() || !by.is_empty() {
            print(&format!("  needs (imports): {}; needed by: {}", if near_.is_empty() { "—".into() } else { near_ }, if by.is_empty() { "—".into() } else { by }));
        }
        let mut ts: Vec<&String> = info.tests.keys().collect();
        ts.sort();
        if ts.is_empty() {
            print("  tests (0): none import or name it");
        } else {
            print(&format!("  tests ({}): {}{}", ts.len(), ts.iter().take(6).map(|s| s.as_str()).collect::<Vec<_>>().join(" "), if ts.len() > 6 { " …" } else { "" }));
        }
        if !info.docs.is_empty() {
            print(&format!("  docs: {}", sorted(&info.docs).iter().take(5).map(|s| s.as_str()).collect::<Vec<_>>().join(", ")));
        }
        let mut gargs: Vec<&str> = vec!["log", "-n", "2", "--format=%ad %h %s", "--date=short", "--"];
        gargs.extend(fs.iter().map(|s| s.as_str()));
        for ln in git(&gargs).split('\n').filter(|l| !l.trim().is_empty()) {
            print(&format!("  changed {}", short(ln, 110)));
        }
    }
    if !also.is_empty() {
        print("\nalso:");
    }
    for c in &also {
        let mut xs = per[c].clone();
        xs.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
        let b = xs[0].1;
        print(&format!("{}  {} {}:{}-{} — {}; {} tests", c, b.id, b.path, b.first, b.last, short(&b.purpose, 70), comps[c].tests.len()));
    }
    let checks: Vec<String> = hits.iter().filter(|(_, b)| is_test(&b.path)).take(3).map(|(_, b)| format!("{} {}:{}-{}", b.id, b.path, b.first, b.last)).collect();
    if !checks.is_empty() {
        print(&format!("tests that say it: {}", checks.join("; ")));
    }
    for (name, about) in recipes_matching(&words) {
        print(&format!("recipe {}: {} ({} recipe {})", name, about, cmd(), name));
    }
    if !untagged.is_empty() {
        print(&format!("{} files carry no tag yet ({} gaps): ask <file> gives their declarations", untagged.len(), cmd()));
    }
    let first: Vec<String> = unique(&hits.iter().filter(|(_, b)| !is_test(&b.path)).map(|(_, b)| b.id.clone()).collect::<Vec<_>>()).into_iter().take(4).collect();
    if !first.is_empty() {
        print(&format!("Next, one call for the whole first round (add every other question to it): {} ask {}", cmd(), first.join(" ")));
    }
    print(&format!("End each change with: {} check", cmd()));
    save_cache();
}
// @end map.brief.print
