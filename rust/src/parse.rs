// @map map.core.parse: a file's tags into blocks, the problems found on the way, and every block of the repository
use crate::config::*;
use crate::decl::declarations_in;
use crate::files::*;
use crate::imports::imports_in;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Mutex;

#[derive(Clone, Serialize, Deserialize, Debug)]
pub struct Block {
    pub id: String,
    pub purpose: String,
    pub first: usize,
    pub last: usize,
    pub path: String,
    pub own: usize,
    pub lines: usize,
}

#[derive(Clone, Debug)]
pub struct Problem {
    pub path: String,
    pub line: usize,
    pub text: String,
}

#[derive(Clone, Serialize, Deserialize, Debug)]
pub struct Decl {
    pub name: String,
    pub kind: String,
    pub first: usize,
    pub last: usize,
    pub what: String,
}

#[derive(Clone, Serialize, Deserialize, Debug)]
pub struct Import {
    pub line: usize,
    pub what: String,
}

#[derive(Clone, Serialize, Deserialize, Debug)]
pub struct Facts {
    pub key: String,
    pub blocks: Vec<Block>,
    pub problems: Vec<(usize, String)>,
    pub outside: Vec<usize>,
    pub decls: Vec<Decl>,
    pub imports: Vec<Import>,
}

/// The blocks of one file (id, purpose, first and last line, own size), problems, lines outside any block.
pub fn parse(p: &str, text: &str) -> (Vec<Block>, Vec<(usize, String)>, Vec<usize>) {
    let mut lines: Vec<&str> = text.split('\n').collect();
    if lines.last() == Some(&"") {
        lines.pop();
    }
    let mut blocks: Vec<Block> = Vec::new();
    let mut open: Vec<usize> = Vec::new();
    let mut problems = Vec::new();
    let Some(form) = forms(p) else { return (blocks, problems, Vec::new()) };
    let pat = tag_patterns(form);
    let known = areas();
    for (k, line) in lines.iter().enumerate() {
        let n = k + 1;
        let Some((kind, id, purpose)) = tag_match(pat, line) else {
            if pat.looks.is_match(line) {
                problems.push((n, "a tag that cannot be read: \"@map <id>: <purpose>\" or \"@end <id>\", alone on its line".to_string()));
            } else if line.starts_with("#!") && n > 1 {
                problems.push((n, "the #! line must stay the first line: put the tag below it".to_string()));
            }
            continue;
        };
        if kind == "map" {
            if !known.contains(id.split('.').next().unwrap_or("")) {
                problems.push((n, format!("{}: its first word is not an area ({}); the file's area is {}", id, sorted(known).join(", "), area_of(p))));
            }
            if purpose.split_whitespace().count() < 3 {
                problems.push((n, format!("{} needs a purpose of three words or more", id)));
            }
            if blocks.iter().any(|b| b.id == id) {
                problems.push((n, format!("{} appears twice in this file", id)));
            }
            while let Some(&top) = open.last() {
                let tid = &blocks[top].id;
                if id == *tid || id.starts_with(&format!("{}.", tid)) {
                    break;
                }
                blocks[top].last = n - 1;
                open.pop();
            }
            blocks.push(Block { id: id.clone(), purpose, first: n, last: 0, path: p.to_string(), own: 0, lines: 0 });
            open.push(blocks.len() - 1);
        } else if !open.iter().any(|&i| blocks[i].id == id) {
            problems.push((n, format!("@end {} closes no open block", id)));
        } else {
            while let Some(top) = open.pop() {
                blocks[top].last = n;
                if blocks[top].id == id {
                    break;
                }
            }
        }
    }
    while let Some(top) = open.pop() {
        blocks[top].last = lines.len();
    }
    let mut depth = vec![0usize; lines.len() + 1];
    for b in &blocks {
        for d in &mut depth[b.first..=b.last] {
            *d += 1;
        }
    }
    let snapshot: Vec<(usize, usize)> = blocks.iter().map(|b| (b.first, b.last)).collect();
    for b in blocks.iter_mut() {
        let mine = snapshot.iter().filter(|(f, l)| *f <= b.first && *l >= b.last).count();
        b.own = (b.first..=b.last).filter(|&i| depth[i] == mine).map(|i| lines[i - 1].chars().count() + 1).sum();
        b.lines = b.last - b.first + 1;
    }
    let outside: Vec<usize> = (1..=lines.len()).filter(|&i| depth[i] == 0 && !lines[i - 1].trim().is_empty()).collect();
    (blocks, problems, outside)
}

#[derive(Serialize, Deserialize, Default)]
struct CacheFile {
    version: String,
    files: HashMap<String, Facts>,
}

static CACHE: Mutex<Option<CacheFile>> = Mutex::new(None);
static DIRTY: Mutex<bool> = Mutex::new(false);

/// A file's blocks, declarations, imports and problems, read once per change of the file (a cache in the temp folder).
pub fn facts(p: &str) -> Facts {
    let mut guard = CACHE.lock().unwrap();
    if guard.is_none() {
        let loaded = std::fs::read_to_string(cache_file("rs")).ok().and_then(|t| serde_json::from_str::<CacheFile>(&t).ok())
            .filter(|c| c.version == VERSION).unwrap_or_default();
        *guard = Some(CacheFile { version: VERSION.into(), files: loaded.files });
    }
    let cache = guard.as_mut().unwrap();
    let Ok(meta) = std::fs::metadata(root().join(p)) else {
        return Facts { key: String::new(), blocks: vec![], problems: vec![], outside: vec![], decls: vec![], imports: vec![] };
    };
    let mtime = meta.modified().ok().and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok()).map(|d| d.as_nanos()).unwrap_or(0);
    let key = format!("{}:{}:{}", mtime, meta.len(), area_of(p));
    if let Some(kept) = cache.files.get(p) {
        if kept.key == key {
            return kept.clone();
        }
    }
    let text = read_file(p);
    let (blocks, problems, outside) = parse(p, &text);
    let f = Facts { key, blocks, problems, outside, decls: declarations_in(p, &text), imports: imports_in(p, &text) };
    cache.files.insert(p.to_string(), f.clone());
    *DIRTY.lock().unwrap() = true;
    f
}

pub fn save_cache() {
    if !*DIRTY.lock().unwrap() {
        return;
    }
    let guard = CACHE.lock().unwrap();
    let Some(cache) = guard.as_ref() else { return };
    let keep: std::collections::HashSet<&String> = repo_files().iter().collect();
    let c = CacheFile { version: VERSION.into(), files: cache.files.iter().filter(|(p, _)| keep.contains(p)).map(|(p, f)| (p.clone(), f.clone())).collect() };
    let path = cache_file("rs");
    if let Some(dir) = path.parent() {
        if std::fs::create_dir_all(dir).is_err() {
            return;
        }
    }
    if let Ok(text) = serde_json::to_string(&c) {
        let tmp = path.with_extension(format!("{}.tmp", std::process::id()));
        if std::fs::write(&tmp, text).is_ok() {
            let _ = std::fs::rename(&tmp, &path);
        }
    }
}

/// All blocks of the repository, every problem with them, and the files that carry no tag yet.
pub fn everything() -> (Vec<Block>, Vec<Problem>, Vec<String>) {
    let mut all = Vec::new();
    let mut problems = Vec::new();
    let mut untagged = Vec::new();
    for p in files() {
        let f = facts(p);
        all.extend(f.blocks.iter().cloned());
        for (n, text) in &f.problems {
            problems.push(Problem { path: p.clone(), line: *n, text: text.clone() });
        }
        if f.blocks.is_empty() {
            untagged.push(p.clone());
        } else if f.outside.len() > cfg().untagged {
            problems.push(Problem { path: p.clone(), line: f.outside[0], text: format!("{} lines outside blocks (at most {}); the first is this one", f.outside.len(), cfg().untagged) });
        }
        for b in &f.blocks {
            if b.own > cfg().block {
                problems.push(Problem { path: p.clone(), line: b.first, text: format!("{} holds {} characters of its own (at most {}): split it with blocks inside it", b.id, commas(b.own), commas(cfg().block)) });
            }
        }
    }
    (all, problems, untagged)
}
// @end map.core.parse
