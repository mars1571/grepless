// @map map.core.write: map.yaml, the central map of the areas, and map/<area>.yaml, each area's components; build and check
use crate::config::*;
use crate::files::*;
use crate::imports::Graph;
use crate::parse::{everything, facts, save_cache, Block, Problem};
use crate::recipes::recipe_problems;
use indexmap::IndexMap;
use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;

#[derive(Default, Clone)]
pub struct Comp {
    pub files: HashSet<String>,
    pub parts: HashSet<String>,
    pub needs: HashSet<String>,
    pub by: HashSet<String>,
    pub docs: HashSet<String>,
    pub declares: Vec<String>,
    pub blocks: usize,
    pub lines: usize,
    pub tests: HashMap<String, String>,
    pub what: String,
}

pub type Comps = IndexMap<String, Comp>;

fn header(name: &str, blocks: &[Block], per_file: &HashMap<String, usize>) -> String {
    let mine: Vec<&Block> = blocks.iter().filter(|b| component(&b.id) == name).collect();
    let Some(first) = mine.iter().min_by(|a, b| a.path.cmp(&b.path).then(a.first.cmp(&b.first))) else { return String::new() };
    let n = mine.iter().filter(|b| b.path == first.path).count();
    if per_file.get(&first.path) == Some(&n) { first.purpose.clone() } else { String::new() }
}

/// The id-like words of a text (shop.cart), each bounded: no letter, digit or dot before, none or a hyphen after.
pub fn ids_in(text: &str) -> HashSet<String> {
    let rx = Regex::new(r"[a-z][a-z0-9-]*\.[a-z0-9-]+").unwrap();
    let mut out = HashSet::new();
    for m in rx.find_iter(text) {
        let ok_before = text[..m.start()].chars().last().map(|c| !(c.is_alphanumeric() || c == '_' || c == '.')).unwrap_or(true);
        let ok_after = text[m.end()..].chars().next().map(|c| !(c.is_alphanumeric() || c == '_' || c == '-')).unwrap_or(true);
        if ok_before && ok_after {
            out.insert(m.as_str().to_string());
        }
    }
    out
}

fn docs_naming(comps: &Comps) -> HashMap<String, HashSet<String>> {
    let paths: Vec<&String> = repo_files().iter().filter(|p| is_doc_ext(&suffix(p).to_lowercase()) && size_of(p) < LARGE).collect();
    let mut names: HashMap<String, usize> = HashMap::new();
    let mut all_files = HashSet::new();
    for c in comps.values() {
        for f in &c.files {
            *names.entry(f.rsplit('/').next().unwrap().to_string()).or_insert(0) += 1;
            all_files.insert(f.clone());
        }
    }
    let mut found = HashMap::new();
    for p in paths {
        let text = read_file(p);
        let mut said: HashSet<String> = ids_in(&text).into_iter().filter(|id| comps.contains_key(id)).collect();
        let hit: HashSet<&String> = all_files.iter().filter(|f| {
            let base = f.rsplit('/').next().unwrap();
            text.contains(f.as_str()) || (names.get(base) == Some(&1) && text.contains(&format!("`{}`", base)))
        }).collect();
        for (name, c) in comps {
            if c.files.iter().any(|f| hit.contains(f)) {
                said.insert(name.clone());
            }
        }
        found.insert(p.clone(), said);
    }
    found
}

pub fn test_files() -> Vec<String> {
    repo_files().iter().filter(|p| is_test(p) && (forms(p).is_some() || is_text_ext(&suffix(p).to_lowercase()))).cloned().collect()
}

fn tests_reaching(g: &Graph, comps: &Comps) -> HashMap<String, HashMap<String, String>> {
    let mut out: HashMap<String, HashMap<String, String>> = comps.keys().map(|k| (k.clone(), HashMap::new())).collect();
    let mut files_of: HashMap<&String, HashSet<&String>> = HashMap::new();
    for (name, c) in comps {
        for f in &c.files {
            files_of.entry(f).or_default().insert(name);
        }
    }
    for t in test_files() {
        if let Some(ts) = g.file_edges.get(&t) {
            for target in sorted(ts) {
                if let Some(names) = files_of.get(&target) {
                    let mut ns: Vec<&&String> = names.iter().collect();
                    ns.sort();
                    for name in ns {
                        out.get_mut(*name).unwrap().insert(t.clone(), format!("imports {}", target));
                    }
                }
            }
        }
        let text = read_file(&t);
        for (name, c) in comps {
            if out[name].contains_key(&t) {
                continue;
            }
            if c.files.iter().any(|f| f != &t && text.contains(f.as_str())) || (text.contains(name.as_str()) && bounded(&text, name, ".", "-")) {
                out.get_mut(name).unwrap().insert(t.clone(), "names it".into());
            }
        }
    }
    out
}

/// Every component: what it is, its parts, files, declarations, needs and what needs it, tests and docs.
pub fn components(blocks: &[Block], g: &Graph) -> Comps {
    let mut purpose = HashMap::new();
    let mut by_path: Vec<&Block> = blocks.iter().collect();
    by_path.sort_by(|a, b| a.path.cmp(&b.path));
    for b in &by_path {
        purpose.entry(b.id.clone()).or_insert_with(|| b.purpose.clone());
    }
    let mut comps: Comps = IndexMap::new();
    for b in blocks {
        let c = comps.entry(component(&b.id)).or_default();
        c.files.insert(b.path.clone());
        c.blocks += 1;
        c.lines += b.lines;
        let parts: Vec<&str> = b.id.split('.').collect();
        if parts.len() > 2 {
            c.parts.insert(parts[2].to_string());
        }
    }
    let mut per_file: HashMap<String, usize> = HashMap::new();
    for b in blocks {
        *per_file.entry(b.path.clone()).or_insert(0) += 1;
    }
    let mut ordered: Vec<&Block> = blocks.iter().collect();
    ordered.sort_by(|a, b| a.path.cmp(&b.path).then(a.first.cmp(&b.first)));
    let mut first_of = HashMap::new();
    for b in ordered {
        first_of.entry(component(&b.id)).or_insert_with(|| b.purpose.clone());
    }
    for (name, c) in comps.iter_mut() {
        c.what = purpose.get(name).cloned().filter(|s| !s.is_empty())
            .or_else(|| Some(header(name, blocks, &per_file)).filter(|s| !s.is_empty()))
            .or_else(|| purpose.get(&format!("{}.api", name)).cloned().filter(|s| !s.is_empty()))
            .or_else(|| first_of.get(name).cloned()).unwrap_or_default();
    }
    for (s, d) in &g.edge_order {
        if comps.contains_key(s) && comps.contains_key(d) {
            comps.get_mut(s).unwrap().needs.insert(d.clone());
            comps.get_mut(d).unwrap().by.insert(s.clone());
        }
    }
    for p in files() {
        for d in facts(p).decls {
            if matches!(d.kind.as_str(), "function" | "class" | "method") {
                if let Some(b) = g.at(p, d.first) {
                    comps.get_mut(&component(&b)).unwrap().declares.push(d.name.clone());
                }
            }
        }
    }
    for (name, found) in tests_reaching(g, &comps) {
        comps.get_mut(&name).unwrap().tests = found;
    }
    for (doc, named) in docs_naming(&comps) {
        for c in named {
            comps.get_mut(&c).unwrap().docs.insert(doc.clone());
        }
    }
    comps
}

pub fn areas_of(comps: &Comps) -> IndexMap<String, Vec<String>> {
    let mut names: Vec<&String> = comps.keys().collect();
    names.sort();
    let mut out: IndexMap<String, Vec<String>> = IndexMap::new();
    for name in names {
        out.entry(name.split('.').next().unwrap().to_string()).or_default().push(name.clone());
    }
    out
}

fn counts_line(m: &HashMap<String, usize>) -> String {
    let mut items: Vec<(&String, &usize)> = m.iter().collect();
    items.sort_by(|a, b| b.1.cmp(a.1).then(a.0.cmp(b.0)));
    format!("{{{}}}", items.iter().map(|(k, v)| format!("{}: {}", k, v)).collect::<Vec<_>>().join(", "))
}

fn sorted_counts(m: &HashMap<String, usize>) -> String {
    let mut keys: Vec<&String> = m.keys().collect();
    keys.sort();
    keys.iter().map(|k| format!("{}: {}", k, m[*k])).collect::<Vec<_>>().join(", ")
}

// @map map.core.write.central: map.yaml's lines: the areas with what each needs, the untagged files, the other files by folder
pub fn central(comps: &Comps, untagged: &[String]) -> String {
    let name = if cfg().name.is_empty() { root().file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or_default() } else { cfg().name.clone() };
    let c = cmd();
    let mut lines = vec![
        format!("# The map of {}: the areas, what each needs from the others (read from imports), and where each one's map is.", name),
        format!("# Generated by `{} build`; never edit it. `{} check` fails when it is out of date.", c, c),
        "# An area's components, what each needs and what needs it: map/<area>.yaml.".to_string(),
        format!("# Reading and finding: `{} brief <words>`, then `{} ask <questions>` (AGENTS.md, \"Finding code\").", c, c),
        "version: 1".into(), String::new(), "areas:".into(),
        "  # needs: how many of its components import a component of that area; needed_by: the other way".into(),
    ];
    let al = areas_of(comps);
    let count = |area: &str, mine: &[String], by: bool| -> String {
        let mut n: HashMap<String, usize> = HashMap::new();
        for cname in mine {
            let src = if by { &comps[cname].by } else { &comps[cname].needs };
            for o in src {
                let a = o.split('.').next().unwrap();
                if a != area {
                    *n.entry(a.to_string()).or_insert(0) += 1;
                }
            }
        }
        counts_line(&n)
    };
    for (area, mine) in &al {
        let files: HashSet<&String> = mine.iter().flat_map(|c| comps[c].files.iter()).collect();
        let nb: usize = mine.iter().map(|c| comps[c].blocks).sum();
        let holds = cfg().holds.get(area).filter(|h| !h.is_empty()).map(|h| format!("holds: {}, ", jstr(h))).unwrap_or_default();
        lines.push(format!("  {}: {{{}components: {}, files: {}, blocks: {}, map: map/{}.yaml, needs: {}, needed_by: {}}}",
            area, holds, mine.len(), files.len(), nb, area, count(area, mine, false), count(area, mine, true)));
    }
    if !untagged.is_empty() {
        lines.push(String::new());
        lines.push("untagged:".into());
        lines.push(format!("  # code files that carry no tag yet, by folder ({} gaps lists them)", c));
        let mut groups: HashMap<String, usize> = HashMap::new();
        for p in untagged {
            let k = p.rfind('/').map(|i| format!("{}/", &p[..i])).unwrap_or_else(|| ".".into());
            *groups.entry(k).or_insert(0) += 1;
        }
        let mut keys: Vec<&String> = groups.keys().collect();
        keys.sort();
        for k in keys {
            lines.push(format!("  {}: {}", jstr(k), groups[k]));
        }
    }
    lines.push(String::new());
    lines.push("other:".into());
    lines.push("  # files without code to read, by folder; each kind described in map.json (describe)".into());
    let mut all: HashSet<String> = repo_files().iter().cloned().collect();
    all.insert("map.yaml".into());
    for a in al.keys() {
        all.insert(format!("map/{}.yaml", a));
    }
    let mut groups: HashMap<String, Vec<String>> = HashMap::new();
    for p in sorted(&all) {
        if forms(&p).is_none() || described(&p).is_some() {
            let k = p.find('/').map(|i| format!("{}/", &p[..i])).unwrap_or_else(|| ".".into());
            groups.entry(k).or_default().push(p);
        }
    }
    let mut gkeys: Vec<&String> = groups.keys().collect();
    gkeys.sort();
    for folder in gkeys {
        let paths = &groups[folder];
        let names: Vec<String> = paths.iter().map(|p| if folder != "." { p[p.find('/').unwrap() + 1..].to_string() } else { p.clone() }).collect();
        let mut kinds: HashMap<String, usize> = HashMap::new();
        for p in paths {
            let k = match described(p) {
                Some(d) => d[1].clone(),
                None => { let s = suffix(p).trim_start_matches('.').to_string(); if s.is_empty() { "file".into() } else { s } }
            };
            *kinds.entry(k).or_insert(0) += 1;
        }
        if names.len() <= 8 || folder == "." {
            lines.push(format!("  {}: [{}]", jstr(folder), names.iter().map(|n| jstr(n)).collect::<Vec<_>>().join(", ")));
        } else {
            lines.push(format!("  {}: {{files: {}, {}}}", jstr(folder), paths.len(), sorted_counts(&kinds)));
        }
    }
    format!("{}\n", lines.join("\n"))
}
// @end map.core.write.central

fn li(s: &HashSet<String>) -> String { format!("[{}]", sorted(s).join(", ")) }

pub fn zone(area: &str, comps: &Comps) -> String {
    let c = cmd();
    let head = match cfg().holds.get(area).filter(|h| !h.is_empty()) {
        Some(h) => format!("# The {} area of the code map: {}.", area, h),
        None => format!("# The {} area of the code map.", area),
    };
    let mut lines = vec![head,
        format!("# One line per component: what it is, its parts ({} ask <component>.<part>), its files, what it", c),
        "# declares, the components it needs (imports) and those that need it, the tests that reach it (by folder)".into(),
        "# and the docs that name it.".into(),
        format!("# Generated by `{} build`; never edit it. All the areas: map.yaml.", c), String::new(), format!("{}:", area)];
    for name in &areas_of(comps)[area] {
        let cp = &comps[name];
        let mut parts = Vec::new();
        if !cp.what.is_empty() {
            parts.push(format!("what: {}", jstr(&cp.what)));
        }
        if !cp.parts.is_empty() {
            parts.push(format!("parts: {}", li(&cp.parts)));
        }
        parts.push(format!("files: [{}]", sorted(&cp.files).iter().map(|f| jstr(f)).collect::<Vec<_>>().join(", ")));
        if !cp.declares.is_empty() {
            let seen = unique(&cp.declares);
            let shown: Vec<String> = seen.iter().take(8).cloned().collect();
            parts.push(format!("declares: [{}{}", shown.join(", "), if seen.len() > 8 { format!(", … {} more]", seen.len() - 8) } else { "]".into() }));
        }
        if !cp.needs.is_empty() {
            parts.push(format!("needs: {}", li(&cp.needs)));
        }
        if !cp.by.is_empty() {
            parts.push(format!("needed_by: {}", li(&cp.by)));
        }
        if !cp.tests.is_empty() {
            let mut folders: HashMap<String, usize> = HashMap::new();
            for t in cp.tests.keys() {
                let k = t.find('/').map(|i| t[..i].to_string()).unwrap_or_else(|| ".".into());
                *folders.entry(k).or_insert(0) += 1;
            }
            parts.push(format!("tests: {{{}}}", sorted_counts(&folders)));
        }
        if !cp.docs.is_empty() {
            parts.push(format!("docs: {}", li(&cp.docs)));
        }
        lines.push(format!("  {}: {{{}}}", name, parts.join(", ")));
    }
    format!("{}\n", lines.join("\n"))
}

pub fn written(comps: &Comps, untagged: &[String]) -> Vec<(PathBuf, String)> {
    let mut out = vec![(root().join("map.yaml"), central(comps, untagged))];
    for area in areas_of(comps).keys() {
        out.push((root().join("map").join(format!("{}.yaml", area)), zone(area, comps)));
    }
    out
}

pub fn build() -> Vec<Problem> {
    let (blocks, problems, untagged) = everything();
    let comps = components(&blocks, &Graph::new(&blocks));
    let texts = written(&comps, &untagged);
    let _ = std::fs::create_dir_all(root().join("map"));
    for (p, text) in &texts {
        if std::fs::read_to_string(p).ok().as_deref() != Some(text.as_str()) {
            let _ = std::fs::write(p, text);
        }
    }
    if let Ok(entries) = std::fs::read_dir(root().join("map")) {
        for e in entries.flatten() {
            let path = e.path();
            if path.extension().map(|x| x == "yaml").unwrap_or(false) && !texts.iter().any(|(p, _)| *p == path) {
                let _ = std::fs::remove_file(path);
            }
        }
    }
    save_cache();
    let files: HashSet<&String> = blocks.iter().map(|b| &b.path).collect();
    print(&format!("{} blocks in {} files, {} components, {} areas; {} files without tags; {} problems",
        blocks.len(), files.len(), comps.len(), areas_of(&comps).len(), untagged.len(), problems.len()));
    problems
}

pub fn problems() -> (Vec<Problem>, usize, usize) {
    let (blocks, mut found, untagged) = everything();
    if cfg().strict {
        for p in &untagged {
            found.push(Problem { path: p.clone(), line: 0, text: "no blocks: tag this file".into() });
        }
    }
    let comps = components(&blocks, &Graph::new(&blocks));
    for (p, text) in written(&comps, &untagged) {
        if std::fs::read_to_string(&p).ok().as_deref() != Some(text.as_str()) {
            let rel = p.strip_prefix(root()).map(|r| r.to_string_lossy().to_string()).unwrap_or_else(|_| p.to_string_lossy().to_string());
            found.push(Problem { path: rel, line: 0, text: format!("out of date: run {} build", cmd()) });
        }
    }
    if is_dir("map") {
        let mut names: Vec<String> = std::fs::read_dir(root().join("map")).map(|rd| rd.flatten().map(|e| e.file_name().to_string_lossy().to_string()).filter(|n| n.ends_with(".yaml")).collect()).unwrap_or_default();
        names.sort();
        let al = areas_of(&comps);
        for n in names {
            if !al.contains_key(n.trim_end_matches(".yaml")) {
                found.push(Problem { path: format!("map/{}", n), line: 0, text: format!("no such area: run {} build", cmd()) });
            }
        }
    }
    found.extend(recipe_problems(&blocks));
    save_cache();
    (found, blocks.len(), untagged.len())
}
// @end map.core.write
