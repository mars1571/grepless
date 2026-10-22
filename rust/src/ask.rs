// @map map.ask.repo: what ask reads (the tagged code and the repository's text), and the block or section holding a line
use crate::config::*;
use crate::files::*;
use crate::parse::{everything, facts, save_cache, Block};
use crate::query::{find, identifier};
use indexmap::IndexMap;
use regex::Regex;
use serde_json::{json, Value};
use std::cell::RefCell;
use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

pub const MANY: usize = 120;
pub const SMALL: usize = 150;
pub const LONG: usize = 80;
pub const CUT: usize = 240;
pub const FEW: usize = 12;

#[derive(Clone, Debug)]
pub struct Section {
    pub first: usize,
    pub last: usize,
    pub level: usize,
    pub title: String,
}

#[derive(Clone, Debug)]
pub struct DeclAt {
    pub path: String,
    pub first: usize,
    pub last: usize,
    pub what: String,
    pub line: String,
}

pub struct Repo {
    pub blocks: Vec<Block>,
    pub files: Vec<String>,
    pub by_file: HashMap<String, Vec<Block>>,
    text: RefCell<HashMap<String, Vec<String>>>,
    sections: RefCell<HashMap<String, Vec<Section>>>,
    decls: RefCell<Option<HashMap<String, Vec<DeclAt>>>>,
}

fn rx(s: &'static str) -> &'static Regex {
    static C: std::sync::Mutex<Option<HashMap<&'static str, &'static Regex>>> = std::sync::Mutex::new(None);
    let mut c = C.lock().unwrap();
    let m = c.get_or_insert_with(HashMap::new);
    if let Some(r) = m.get(s) { return r; }
    let r: &'static Regex = Box::leak(Box::new(Regex::new(s).unwrap()));
    m.insert(s, r);
    r
}

impl Repo {
    pub fn new(blocks: Option<Vec<Block>>) -> Self {
        let blocks = blocks.unwrap_or_else(|| everything().0);
        let files: Vec<String> = repo_files().iter().filter(|p| (is_text_ext(&suffix(p).to_lowercase()) || forms(p).is_some()) && !binary_rx().is_match(p)).cloned().collect();
        let mut by_file: HashMap<String, Vec<Block>> = HashMap::new();
        for b in &blocks {
            by_file.entry(b.path.clone()).or_default().push(b.clone());
        }
        Repo { blocks, files, by_file, text: RefCell::new(HashMap::new()), sections: RefCell::new(HashMap::new()), decls: RefCell::new(None) }
    }

    pub fn lines(&self, p: &str) -> Vec<String> {
        if let Some(l) = self.text.borrow().get(p) {
            return l.clone();
        }
        let mut lines: Vec<String> = read_file(p).split('\n').map(String::from).collect();
        if lines.len() > 1 && lines.last().map(|s| s.is_empty()).unwrap_or(false) {
            lines.pop();
        }
        self.text.borrow_mut().insert(p.to_string(), lines.clone());
        lines
    }

    pub fn holder(&self, p: &str, n: usize) -> Option<Block> {
        let mut best: Option<&Block> = None;
        if let Some(bs) = self.by_file.get(p) {
            for b in bs {
                if b.first <= n && n <= b.last && best.map(|x| b.first > x.first || (b.first == x.first && b.last < x.last)).unwrap_or(true) {
                    best = Some(b);
                }
            }
        }
        best.cloned()
    }

    pub fn sections(&self, p: &str) -> Vec<Section> {
        if let Some(s) = self.sections.borrow().get(p) {
            return s.clone();
        }
        let lines = self.lines(p);
        let mut heads: Vec<(usize, usize, String)> = Vec::new();
        let mut fence = false;
        for (k, line) in lines.iter().enumerate() {
            if line.starts_with("```") {
                fence = !fence;
            } else if !fence {
                if let Some(m) = rx(r"^(#{1,6})\s+(.*)").captures(line) {
                    heads.push((k + 1, m[1].len(), m[2].trim().to_string()));
                }
            }
        }
        let out: Vec<Section> = heads.iter().enumerate().map(|(k, (i, level, title))| {
            let last = heads[k + 1..].iter().find(|(_, lv, _)| lv <= level).map(|(j, _, _)| j - 1).unwrap_or(lines.len());
            Section { first: *i, last, level: *level, title: title.clone() }
        }).collect();
        self.sections.borrow_mut().insert(p.to_string(), out.clone());
        out
    }

    pub fn section_at(&self, p: &str, n: usize) -> Option<Section> {
        self.sections(p).into_iter().filter(|s| s.first <= n && n <= s.last).max_by_key(|s| s.first)
    }

    pub fn decls(&self) -> HashMap<String, Vec<DeclAt>> {
        if let Some(d) = self.decls.borrow().as_ref() {
            return d.clone();
        }
        let mut m: HashMap<String, Vec<DeclAt>> = HashMap::new();
        for p in files() {
            for d in facts(p).decls {
                if d.kind != "heading" {
                    m.entry(d.name.clone()).or_default().push(DeclAt { path: p.clone(), first: d.first, last: d.last, what: format!("{} {}", d.kind, d.name), line: d.what.clone() });
                }
            }
        }
        *self.decls.borrow_mut() = Some(m.clone());
        m
    }

    pub fn where_(&self, p: &str, a: usize, b: usize) -> String {
        if is_doc_ext(&suffix(p).to_lowercase()) {
            return self.section_at(p, a).map(|s| format!("{} {}", "#".repeat(s.level), s.title)).unwrap_or_default();
        }
        let b = if b == 0 { a } else { b };
        let mut ids: Vec<String> = Vec::new();
        for n in a..=b {
            if let Some(h) = self.holder(p, n) {
                if !ids.contains(&h.id) { ids.push(h.id); }
            }
        }
        let mut s = ids.iter().take(4).map(|s| s.as_str()).collect::<Vec<_>>().join(", ");
        if ids.len() > 4 { s.push_str(&format!(" (+{})", ids.len() - 4)); }
        s
    }
}

pub fn relative(q: &str) -> Option<String> {
    let r = root().to_string_lossy().to_string();
    // on Windows a path is written with `\` or `/`, the drive letter in either case, or as Git Bash's /c/…
    let (r, q) = if cfg!(windows) { (r.replace('\\', "/"), crate::guard::msys_path(q).unwrap_or_else(|| q.to_string()).replace('\\', "/")) } else { (r, q.to_string()) };
    let q = q.as_str();
    let under = q.len() > r.len() && q.as_bytes()[r.len()] == b'/' && q.is_char_boundary(r.len())
        && if cfg!(windows) { q[..r.len()].eq_ignore_ascii_case(&r) } else { q[..r.len()] == r };
    let mut p = if under { q[r.len() + 1..].to_string() } else { q.to_string() };
    if p.starts_with("./") { p = p[2..].to_string(); }
    p = p.trim_end_matches('/').to_string();
    if p.is_empty() { p = ".".into(); }
    if exists(&p) && !p.starts_with("..") { Some(p) } else { None }
}

pub fn within(p: &str, places: &[String]) -> bool {
    places.is_empty() || places.iter().any(|q| p == q || p.starts_with(&format!("{}/", q.trim_end_matches('/'))) || fnmatch(p, q))
}

pub fn put(lines: &[String], a: usize, b: usize) {
    for i in a..=b {
        print(&format!("{}\t{}", i, lines[i - 1]));
    }
}

fn word_rx() -> &'static Regex { rx(r"^[A-Za-z_$][\w$]*$") }

/// Where word is declared, as the files' shapes show it; else the values assigned to it.
pub fn declarations(repo: &Repo, word: &str) -> Vec<DeclAt> {
    let mut out: Vec<DeclAt> = repo.decls().get(word).cloned().unwrap_or_default();
    if out.is_empty() && word_rx().is_match(word) {
        let r = Regex::new(&format!(r"(?:\b(?:const|let|var|val|final|static|export)\s+|^\s*){}\s*[:=]", regex::escape(word))).unwrap();
        for p in files() {
            let lines = repo.lines(p);
            if !lines.join("\n").contains(word) { continue; }
            for (k, line) in lines.iter().enumerate() {
                if out.len() >= 6 || rx(r"^\s*(#|//|\*)").is_match(line) { continue; }
                if let Some(m) = r.find(line) {
                    let next = line[m.end()..].chars().next();
                    if !matches!(next, Some('=') | Some('>')) {
                        out.push(DeclAt { path: p.clone(), first: k + 1, last: k + 1, what: format!("value {}", word), line: cut_chars(line.trim(), 120) });
                    }
                }
            }
        }
    }
    out
}
// @end map.ask.repo

// @map map.ask.answer: each kind of question answered whole, and the command reading a call's questions
pub struct Hit {
    pub path: String,
    pub line: usize,
    pub text: String,
}

type Skip = (String, usize, usize);

fn skipped(skip: &[Skip], p: &str, n: usize) -> bool { skip.iter().any(|(sp, a, b)| sp == p && *a <= n && n <= *b) }

pub fn search(repo: &Repo, r: &Regex, places: &[String], skip: &[Skip]) -> Vec<Hit> {
    let mut hits = Vec::new();
    for p in &repo.files {
        if !within(p, places) || size_of(p) > LARGE { continue; }
        let lines = repo.lines(p);
        if !r.is_match(&lines.join("\n")) { continue; }
        for (k, line) in lines.iter().enumerate() {
            if r.is_match(line) && !skipped(skip, p, k + 1) {
                hits.push(Hit { path: p.clone(), line: k + 1, text: line.clone() });
            }
        }
    }
    hits
}

pub fn search_word(repo: &Repo, word: &str, places: &[String], skip: &[Skip], hyphen: bool) -> Vec<Hit> {
    let edge = if hyphen { "-" } else { "" };
    let mut hits = Vec::new();
    for p in &repo.files {
        if !within(p, places) || size_of(p) > LARGE { continue; }
        let lines = repo.lines(p);
        if !lines.join("\n").contains(word) { continue; }
        for (k, line) in lines.iter().enumerate() {
            if line.contains(word) && bounded(line, word, edge, edge) && !skipped(skip, p, k + 1) {
                hits.push(Hit { path: p.clone(), line: k + 1, text: line.clone() });
            }
        }
    }
    hits
}

/// A block as `--json` shows it.
pub fn block_json(b: &Block) -> Value { json!({"id": b.id, "file": b.path, "first": b.first, "last": b.last, "purpose": b.purpose}) }

pub fn show_hits(repo: &Repo, hits: &[Hit], every: bool, numbers: bool) {
    let mut places: IndexMap<String, (String, Vec<&Hit>)> = IndexMap::new();
    for h in hits {
        rec("hits", json!({"file": h.path, "line": h.line, "text": h.text, "block": repo.holder(&h.path, h.line).map(|b| b.id)}));
        let (key, label) = if let Some(b) = repo.holder(&h.path, h.line) {
            (format!("{}\0{}\0{}", h.path, b.id, b.first), format!("{}  {}:{}-{}  {}", b.id, h.path, b.first, b.last, short(&b.purpose, 110)))
        } else if let Some(s) = if is_doc_ext(&suffix(&h.path).to_lowercase()) { repo.section_at(&h.path, h.line) } else { None } {
            (format!("{}\0{}", h.path, s.first), format!("{}:{}-{}  {} {}", h.path, s.first, s.last, "#".repeat(s.level), s.title))
        } else {
            (h.path.clone(), h.path.clone())
        };
        places.entry(key).or_insert_with(|| (label, Vec::new())).1.push(h);
    }
    if hits.len() > MANY && !every {
        print(&format!("  {} lines in {} places; the places (their lines: --all, or --in <file, folder or glob>)", hits.len(), places.len()));
        for (label, found) in places.values().take(60) {
            print(&format!("    {}  ({} lines)", label, found.len()));
        }
        if places.len() > 60 {
            print(&format!("    … {} more places", places.len() - 60));
        }
        return;
    }
    for (label, found) in places.values() {
        if numbers {
            print(&format!("    {}: {}", label, found.iter().map(|h| h.line.to_string()).collect::<Vec<_>>().join(", ")));
            continue;
        }
        print(&format!("  {}", label));
        for h in found {
            let r: Vec<char> = h.text.chars().collect();
            let line = if r.len() <= CUT { h.text.clone() } else { format!("{} …(+{})", r[..CUT].iter().collect::<String>(), r.len() - CUT) };
            print(&format!("{}\t{}", h.line, line));
        }
    }
}

fn answer_lines(repo: &Repo, p: &str, a0: usize, b0: Option<usize>) {
    let lines = repo.lines(p);
    let (mut a, mut b, label) = match b0 {
        Some(b) => (a0, b, repo.where_(p, a0, b)),
        None => {
            let h = repo.holder(p, a0);
            let s = if is_doc_ext(&suffix(p).to_lowercase()) { repo.section_at(p, a0) } else { None };
            if let Some(h) = h { (h.first, h.last, format!("{}: {}", h.id, h.purpose)) }
            else if let Some(s) = s { (s.first, s.last, format!("{} {}", "#".repeat(s.level), s.title)) }
            else { (if a0 > 15 { a0 - 15 } else { 1 }, a0 + 15, String::new()) }
        }
    };
    if a < 1 { a = 1; }
    if b > lines.len() { b = lines.len(); }
    if let Some(h) = repo.holder(p, a0) { if b0.is_none() { rec("blocks", block_json(&h)); } }
    print(&format!("  {}:{}-{}{}", p, a, b, if label.is_empty() { String::new() } else { format!("  {}", label) }));
    put(&lines, a, b);
}

fn py_type(v: &Value) -> &'static str {
    match v {
        Value::Null => "NoneType", Value::Bool(_) => "bool",
        Value::Number(n) => if n.is_i64() || n.is_u64() { "int" } else { "float" },
        Value::String(_) => "str", Value::Array(_) => "list", Value::Object(_) => "dict",
    }
}

// @map map.ask.answer.file: a file answered whole, by its outline, its sections, its keys or its declarations
fn answer_file(repo: &Repo, p: &str) {
    let lines = repo.lines(p);
    let sfx = suffix(p).to_lowercase();
    if size_of(p) > LARGE {
        print(&format!("  {}: {} lines, {} bytes: data, not printed (ask {}:<first>-<last>)", p, lines.len(), commas(size_of(p) as usize), p));
    } else if lines.len() <= SMALL {
        print(&format!("  {}: {} lines, whole", p, lines.len()));
        put(&lines, 1, lines.len());
    } else if is_doc_ext(&sfx) && !repo.sections(p).is_empty() {
        print(&format!("  {}: {} lines; its sections (one: ask {}#<words of its heading>)", p, lines.len(), p));
        for s in repo.sections(p) {
            print(&format!("{}-{}{}{} {}", pad_l(&s.first.to_string(), 6), pad_r(&s.last.to_string(), 6), "  ".repeat(s.level - 1), "#".repeat(s.level), s.title));
        }
    } else if sfx == ".json" {
        match serde_json::from_str::<Value>(&lines.join("\n")) {
            Ok(Value::Object(m)) => {
                print(&format!("  {}: {} lines; its keys (one: ask {}#<key>)", p, lines.len(), p));
                for (k, v) in &m {
                    let sub = match v { Value::Object(sm) => format!(" {{{}{}}}", sm.keys().take(8).cloned().collect::<Vec<_>>().join(", "), if sm.len() > 8 { ", …" } else { "" }), _ => String::new() };
                    print(&format!("    {}: {}, {} characters{}", k, py_type(v), commas(jdump(v, 0, 0).chars().count()), sub));
                }
            }
            Ok(Value::Array(a)) => {
                print(&format!("  {}: {} lines; its keys (one: ask {}#<key>)", p, lines.len(), p));
                for (i, v) in a.iter().enumerate() {
                    let sub = match v { Value::Object(sm) => format!(" {{{}{}}}", sm.keys().take(8).cloned().collect::<Vec<_>>().join(", "), if sm.len() > 8 { ", …" } else { "" }), _ => String::new() };
                    print(&format!("    {}: {}, {} characters{}", i, py_type(v), commas(jdump(v, 0, 0).chars().count()), sub));
                }
            }
            _ => {
                print(&format!("  {}: {} lines; the first {} (more: ask {}:<first>-<last>)", p, lines.len(), SMALL, p));
                put(&lines, 1, SMALL);
            }
        }
    } else if repo.by_file.get(p).map(|v| !v.is_empty()).unwrap_or(false) {
        let mut named: HashMap<String, Vec<String>> = HashMap::new();
        if forms(p).is_some() {
            for d in facts(p).decls {
                if matches!(d.kind.as_str(), "function" | "class" | "method") {
                    if let Some(h) = repo.holder(p, d.first) {
                        named.entry(h.id).or_default().push(d.name);
                    }
                }
            }
        }
        print(&format!("  {}: {} lines; its blocks (one: ask <id>, or {}:<first>-<last>)", p, lines.len(), p));
        let mut bs = repo.by_file[p].clone();
        bs.sort_by(|a, b| a.first.cmp(&b.first).then(b.last.cmp(&a.last)));
        let mut outer: Vec<usize> = Vec::new();
        for b in bs {
            while outer.last().map(|l| *l < b.first).unwrap_or(false) { outer.pop(); }
            rec("blocks", block_json(&b));
            let mut line = format!("{}-{}{}{}  {}", pad_l(&b.first.to_string(), 6), pad_r(&b.last.to_string(), 6), "  ".repeat(outer.len()), b.id, short(&b.purpose, 110));
            if let Some(ns) = named.get(&b.id) {
                line.push_str(&format!("  [{}{}]", ns.iter().take(8).map(|s| s.as_str()).collect::<Vec<_>>().join(", "), if ns.len() > 8 { " …" } else { "" }));
            }
            print(&line);
            outer.push(b.last);
        }
    } else if forms(p).is_some() && facts(p).decls.iter().any(|d| d.kind != "heading") {
        let decls = facts(p).decls;
        print(&format!("  {}: {} lines, no tags yet; what it declares (one: ask <name>, or {}:<first>-<last>)", p, lines.len(), p));
        for d in decls.iter().take(80) {
            print(&format!("{}-{}{} {}  {}", pad_l(&d.first.to_string(), 6), pad_r(&d.last.to_string(), 6), d.kind, d.name, short(&d.what, 90)));
        }
        if decls.len() > 80 {
            print(&format!("    … {} more", decls.len() - 80));
        }
    } else {
        print(&format!("  {}: {} lines; the first {} (more: ask {}:<first>-<last>)", p, lines.len(), SMALL, p));
        put(&lines, 1, SMALL);
    }
}
// @end map.ask.answer.file

fn answer_files(repo: &Repo, paths: &[String], about: &str) {
    print(&format!("  {}: {} files", about, paths.len()));
    for p in paths {
        let first = repo.by_file.get(p).and_then(|bs| bs.iter().min_by_key(|b| b.first));
        let what = match first {
            Some(b) => short(&b.purpose, 90),
            None => if is_doc_ext(&suffix(p).to_lowercase()) { repo.sections(p).first().map(|s| s.title.clone()).unwrap_or_default() } else { String::new() },
        };
        rec("files", json!({"file": p, "lines": repo.lines(p).len(), "what": what}));
        print(&format!("    {}  ({} lines)  {}", p, repo.lines(p).len(), what));
    }
}

fn answer_folder(repo: &Repo, p: &str) {
    let base = if p == "." { String::new() } else { format!("{}/", p.trim_end_matches('/')) };
    let under: Vec<&String> = repo.files.iter().filter(|x| x.starts_with(&base)).collect();
    let here: Vec<String> = under.iter().filter(|x| !x[base.len()..].contains('/')).map(|x| (*x).clone()).collect();
    let mut folders: HashMap<String, usize> = HashMap::new();
    for x in &under {
        let rest = &x[base.len()..];
        if let Some(i) = rest.find('/') {
            *folders.entry(rest[..i].to_string()).or_insert(0) += 1;
        }
    }
    answer_files(repo, &here, p);
    let mut keys: Vec<&String> = folders.keys().collect();
    keys.sort();
    for f in keys {
        print(&format!("    {}{}/  ({} files)", base, f, folders[f]));
    }
}

fn words_match(text: &str, ws: &[String]) -> bool {
    let toks = lower_words(text);
    ws.iter().all(|w| toks.iter().any(|t| t.starts_with(w)))
}

fn answer_part(repo: &Repo, p: &str, words: &str) -> bool {
    let ws = lower_words(words);
    if p.ends_with(".json") {
        let Ok(mut data) = serde_json::from_str::<Value>(&repo.lines(p).join("\n")) else { return false };
        for k in words.split('.') {
            data = match data {
                Value::Array(a) => match k.parse::<usize>() { Ok(i) if i < a.len() && i.to_string() == k => a[i].clone(), _ => return false },
                Value::Object(m) => match m.get(k) { Some(v) => v.clone(), None => return false },
                _ => return false,
            };
        }
        print(&format!("  {}#{}", p, words));
        print(&jdump(&data, 1, 0));
        return true;
    }
    if is_doc_ext(&suffix(p).to_lowercase()) {
        let found: Vec<Section> = repo.sections(p).into_iter().filter(|s| words_match(&s.title, &ws)).collect();
        for s in &found {
            print(&format!("  {}:{}-{}  {} {}", p, s.first, s.last, "#".repeat(s.level), s.title));
            put(&repo.lines(p), s.first, s.last);
        }
        return !found.is_empty();
    }
    let found: Vec<Block> = repo.by_file.get(p).cloned().unwrap_or_default().into_iter().filter(|b| words_match(&format!("{} {}", b.id, b.purpose), &ws)).collect();
    for b in &found {
        rec("blocks", block_json(b));
        print(&format!("  {}:{}-{}  {}: {}", p, b.first, b.last, b.id, b.purpose));
        put(&repo.lines(p), b.first, b.last);
    }
    !found.is_empty()
}

fn answer_block(repo: &Repo, q: &str) {
    let exact: Vec<&Block> = repo.blocks.iter().filter(|b| b.id == q).collect();
    let inside: Vec<&Block> = repo.blocks.iter().filter(|b| b.id.starts_with(&format!("{}.", q))).collect();
    if !exact.is_empty() {
        for b in exact {
            rec("blocks", block_json(b));
            let nested: Vec<&Block> = repo.by_file[&b.path].iter().filter(|x| !(x.id == b.id && x.first == b.first) && b.first <= x.first && x.last <= b.last).collect();
            print(&format!("  {}:{}-{}  {}: {}", b.path, b.first, b.last, b.id, b.purpose));
            if b.last - b.first + 1 > SMALL && !nested.is_empty() {
                print(&format!("  {} lines; the blocks inside it (one: ask <id>, or {}:<first>-<last>)", b.last - b.first + 1, b.path));
                for x in nested {
                    rec("blocks", block_json(x));
                    print(&format!("{}-{}{}  {}", pad_l(&x.first.to_string(), 6), pad_r(&x.last.to_string(), 6), x.id, short(&x.purpose, 110)));
                }
            } else {
                put(&repo.lines(&b.path), b.first, b.last);
            }
        }
    } else if inside.len() <= 60 {
        print(&format!("  {} blocks under {} (one: ask <id>)", inside.len(), q));
        for b in inside {
            rec("blocks", block_json(b));
            print(&format!("    {} {}:{}-{}  {}", pad_r(&b.id, 44), b.path, b.first, b.last, short(&b.purpose, 110)));
        }
    } else {
        let depth = q.split('.').count() + 1;
        let mut parts: IndexMap<String, Vec<&Block>> = IndexMap::new();
        for b in inside.iter() {
            let k = b.id.split('.').take(depth).collect::<Vec<_>>().join(".");
            parts.entry(k).or_default().push(b);
        }
        print(&format!("  {} blocks under {}, in {} parts (one: ask <id>)", inside.len(), q, parts.len()));
        for (k, bs) in &parts {
            let paths: HashSet<String> = bs.iter().map(|b| b.path.clone()).collect();
            print(&format!("    {} {} blocks  {}  {}", pad_r(k, 40), pad_l(&bs.len().to_string(), 3), cut_chars(&sorted(&paths).join(", "), 80), short(&bs[0].purpose, 70)));
        }
    }
}

fn answer_name(repo: &Repo, q: &str, places: &[String], every: bool) -> bool {
    let word = if q.starts_with("--") { q.to_string() } else { q.trim_start_matches(['#', '.']).to_string() };
    let decls = if word_rx().is_match(&word) { declarations(repo, &word) } else { vec![] };
    if decls.len() > 3 {
        print(&format!("  declared in {} places (the code of one: ask <file>:<first>-<last>)", decls.len()));
    }
    for d in &decls {
        rec("declarations", json!({"what": d.what, "file": d.path, "first": d.first, "last": d.last}));
        let mut wh = repo.where_(&d.path, d.first, 0);
        if wh.is_empty() { wh = d.path.clone(); }
        print(&format!("  {}: {}:{}-{}  in {}", d.what, d.path, d.first, d.last, wh));
        if decls.len() <= 3 && d.last - d.first < LONG {
            put(&repo.lines(&d.path), d.first, d.last);
        } else if decls.len() <= 3 {
            put(&repo.lines(&d.path), d.first, d.first + 11);
            print(&format!("  … {} more lines: ask {}:{}-{}", d.last - d.first - 11, d.path, d.first + 12, d.last));
        }
    }
    let hyphen = word.contains('-') || q.starts_with("--") || !word.chars().next().map(|c| c.is_alphanumeric()).unwrap_or(false);
    let skip: Vec<Skip> = decls.iter().map(|d| (d.path.clone(), d.first, d.last)).collect();
    let hits = search_word(repo, &word, places, &skip, hyphen);
    if !hits.is_empty() {
        print(&if decls.is_empty() { format!("  on {} lines", hits.len()) } else { format!("  named on {} other lines", hits.len()) });
        show_hits(repo, &hits, every, hits.len() > FEW && !every);
    }
    !decls.is_empty() || !hits.is_empty()
}

fn names_in(q: &str) -> Vec<String> {
    let declared = rx(r"^\^?\s*(?:(?:export|async|static|pub|public|private)\s+)*(?:function\*?|def|fn|func|class|const|let|var|val)\s+([A-Za-z_$][\w$]*)\b.*$|^(?:global\.|window\.|\.)?([A-Za-z_$][\w$]*)\s*(?:\\?\(|=)\s*$");
    let mut out = Vec::new();
    for alt in rx(r"\\\||\|").split(q) {
        let Some(m) = declared.captures(alt.trim()) else { return vec![] };
        out.push(m.get(1).or_else(|| m.get(2)).map(|x| x.as_str().to_string()).unwrap_or_default());
    }
    unique(&out)
}

fn unescaped_pipe(q: &str) -> bool {
    let r: Vec<char> = q.chars().collect();
    r.iter().enumerate().any(|(i, c)| *c == '|' && (i == 0 || r[i - 1] != '\\'))
}

fn answer_text(repo: &Repo, q0: &str, places: &[String], every: bool) -> bool {
    let literal = literal_on();
    let q = if !literal && q0.contains("\\|") && !unescaped_pipe(q0) { q0.replace("\\|", "|") } else { q0.to_string() };
    let r = if literal { Regex::new(&regex::escape(&q)).unwrap() } else { Regex::new(&q).unwrap_or_else(|_| Regex::new(&regex::escape(&q)).unwrap()) };
    let hits = search(repo, &r, places, &[]);
    if !hits.is_empty() {
        show_hits(repo, &hits, every, false);
        return true;
    }
    if !literal && q.trim().contains(' ') {
        print("  no line holds it; the blocks whose id, purpose or file have these words:");
        find(&q.split_whitespace().map(String::from).collect::<Vec<_>>());
        return true;
    }
    false
}

// @map map.ask.answer.call: the command reading a call's questions, each answered into its own part of the output, then fitted to the budget
pub fn ask(args: &[String]) {
    let every = args.iter().any(|a| a == "--all");
    let mut budget = cfg().answer;
    let mut questions: Vec<(String, Vec<String>)> = Vec::new();
    let mut waiting: Vec<String> = Vec::new();
    let mut i = 0;
    while i < args.len() {
        if args[i] == "--in" && i + 1 < args.len() {
            let places: Vec<String> = args[i + 1].split(',').filter(|x| !x.is_empty()).map(|x| relative(x).unwrap_or_else(|| x.trim_start_matches(['.', '/']).to_string())).collect();
            for q in waiting.drain(..) {
                questions.push((q, places.clone()));
            }
            i += 2;
            continue;
        }
        if args[i] == "--budget" && i + 1 < args.len() && !args[i + 1].is_empty() && args[i + 1].chars().all(|c| c.is_ascii_digit()) {
            budget = args[i + 1].parse().unwrap_or(usize::MAX);
            i += 2;
            continue;
        }
        if args[i] == "--json" {
            set_json(true);
            i += 1;
            continue;
        }
        if args[i] == "--literal" || args[i] == "-F" {
            set_literal(true);
            i += 1;
            continue;
        }
        if args[i] != "--all" {
            waiting.push(args[i].clone());
        }
        i += 1;
    }
    for q in waiting {
        questions.push((q, vec![]));
    }
    if questions.is_empty() {
        die(&crate::cli::usage());
    }
    let repo = Repo::new(None);
    let ids: HashSet<&String> = repo.blocks.iter().map(|b| &b.id).collect();
    flush();
    let mut answers: Vec<(String, String)> = Vec::new();
    let mut docs: Vec<Value> = Vec::new();
    for (q, places) in &questions {
        let _ = take_rec();
        answer(&repo, &ids, q, places, every);
        let text = take_out();
        if json_on() {
            let mut doc = serde_json::Map::new();
            doc.insert("question".into(), json!(q));
            for k in ["blocks", "declarations", "files", "hits"] { doc.insert(k.into(), json!([])); }
            for (k, v) in take_rec() { doc.insert(k, v); }
            doc.insert("found".into(), json!(!text.contains("nothing in the code or the docs holds it")));
            doc.insert("text".into(), json!(text));
            docs.push(Value::Object(doc));
        }
        answers.push((q.clone(), text));
    }
    if json_on() {
        print_json(&json!({"questions": docs}));
        save_cache();
        return;
    }
    for t in fit(&answers, budget) { crate::config::print_raw(&t); }
    save_cache();
}

/// One question of a call, answered whole.
fn answer(repo: &Repo, ids: &HashSet<&String>, q: &String, places: &[String], every: bool) {
    let line_q = rx(r"^(.+?):(\d+)(?:-(\d+))?$");
    {
        print(&format!("== {}", q));
        if literal_on() {
            if !answer_text(repo, q, places, every) {
                print("  nothing in the code or the docs holds it");
            }
            return;
        }
        if let Some(m) = line_q.captures(q) {
            if let Some(p) = relative(&m[1]).filter(|p| is_file(p)) {
                let a: usize = m[2].parse().unwrap_or(1);
                let b: Option<usize> = m.get(3).and_then(|x| x.as_str().parse().ok());
                answer_lines(repo, &p, a, b);
                return;
            }
        }
        if let Some(h) = q.find('#') {
            let (head, part) = (&q[..h], &q[h + 1..]);
            if !part.is_empty() && !head.is_empty() {
                if let Some(p) = relative(head).filter(|p| is_file(p)) {
                    if !answer_part(repo, &p, part) {
                        print(&format!("  nothing in {} is called \"{}\"; its outline:", p, part));
                        answer_file(repo, &p);
                    }
                    return;
                }
            }
        }
        let p = relative(q);
        if let Some(p) = p.as_ref().filter(|p| is_file(p)) {
            answer_file(repo, p);
        } else if let Some(p) = p.as_ref().filter(|p| is_dir(p)) {
            answer_folder(repo, p);
        } else if rx(r"[*?]").is_match(q) && q.contains('/') && !rx(r"[\\|()+^$]").is_match(q) {
            let pat = q.trim_start_matches(['.', '/']);
            let paths: Vec<String> = repo.files.iter().filter(|x| fnmatch(x, pat)).cloned().collect();
            answer_files(repo, &paths, q);
        } else if !names_in(q).is_empty() {
            let ns = names_in(q);
            for name in &ns {
                print(&if ns.len() > 1 { format!("  {}:", name) } else { format!("  the name {}", name) });
                if !answer_name(repo, name, places, every) {
                    print("  nothing in the code or the docs holds it");
                }
            }
        } else if ids.contains(q) || ids.iter().any(|x| x.starts_with(&format!("{}.", q))) {
            answer_block(repo, q);
        } else if (identifier(q) || word_rx().is_match(q)) && answer_name(repo, q, places, every) {
        } else if !answer_text(repo, q, places, every) {
            print("  nothing in the code or the docs holds it");
        }
    }
}
// @end map.ask.answer.call

// @map map.ask.answer.fit: a call's answers kept within its budget of characters: the longest leave their code out, and say so
const CODE_LEFT: &str = "  … ";

/// A call's answers within its budget of characters: while they run over it, the longest answer (the first of equals) keeps its
/// places and leaves out its lines of code, and says so. One question is always answered whole.
fn fit(answers: &[(String, String)], budget: usize) -> Vec<String> {
    let mut texts: Vec<String> = answers.iter().map(|(_, t)| t.clone()).collect();
    let mut total: usize = texts.iter().map(|t| t.chars().count()).sum();
    if budget == 0 || texts.len() < 2 { return texts; }
    let mut order: Vec<usize> = (0..texts.len()).collect();
    let lens: Vec<usize> = texts.iter().map(|t| t.chars().count()).collect();
    order.sort_by_key(|&k| (std::cmp::Reverse(lens[k]), k));
    let code = rx(r"^\d+\t");
    for k in order {
        if total <= budget { break; }
        let lines: Vec<&str> = texts[k].trim_end_matches('\n').split('\n').collect();
        let kept: Vec<&str> = lines.iter().copied().filter(|x| !code.is_match(x)).collect();
        if kept.len() == lines.len() { continue; }
        let short = format!("{}\n{}{} lines of code left out to keep this call under {} characters: ask {} in a call of its own\n", kept.join("\n"), CODE_LEFT, lines.len() - kept.len(), commas(budget), answers[k].0);
        total = total + short.chars().count() - texts[k].chars().count();
        texts[k] = short;
    }
    texts
}
// @end map.ask.answer.fit

pub fn _keep(_: &OnceLock<u8>) {}
// @end map.ask.answer
