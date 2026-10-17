// @map map.core.files: the repository's files and their comment forms, what .gitignore and map.json leave out, each file's area, the tags' patterns
use crate::config::*;
use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::io::Read;
use std::process::Command;
use std::sync::{Mutex, OnceLock};

/// The comment forms a file writes its tags in, or None when it carries none (data, docs, pictures).
pub fn forms(p: &str) -> Option<&'static Vec<(&'static str, &'static str)>> {
    let name = p.rsplit('/').next().unwrap_or(p);
    let sfx = suffix(name);
    let mut form: Option<String> = cfg().forms.get(&sfx).cloned();
    if form.is_none() {
        form = named_table().get(name).or_else(|| ext_table().get(sfx.as_str())).map(|s| s.to_string());
    }
    if form.is_none() && sfx.is_empty() && is_file(p) {
        if let Ok(mut f) = std::fs::File::open(root().join(p)) {
            let mut b = [0u8; 2];
            if f.read(&mut b).unwrap_or(0) == 2 && &b == b"#!" {
                form = Some("hash".into());
            }
        }
    }
    match form {
        Some(f) if !f.is_empty() => forms_table().get(f.as_str()),
        _ => None,
    }
}

pub fn ignored(p: &str) -> bool {
    let parts: Vec<&str> = p.split('/').collect();
    if parts[..parts.len() - 1].iter().any(|x| skip_set().contains(x)) || parts[parts.len() - 1] == "map.yaml" {
        return true;
    }
    cfg().ignore.iter().any(|q| {
        let t = q.trim_end_matches('/');
        p == t || p.starts_with(&format!("{}/", t)) || fnmatch(p, q)
    })
}

static FILES: OnceLock<Vec<String>> = OnceLock::new();
static CODE: OnceLock<Vec<String>> = OnceLock::new();

fn git_ignored() -> Vec<String> {
    read_file(".gitignore").lines().map(|l| l.trim().to_string()).filter(|l| !l.is_empty() && !l.starts_with('#') && !l.starts_with('!')).collect()
}

/// Every file of the repository: tracked, or new and not ignored, when the root is a git repository's; every file
/// under the root otherwise, less what .gitignore and the usual folders leave out.
pub fn repo_files() -> &'static Vec<String> {
    FILES.get_or_init(|| {
        let mut found: Vec<String> = Vec::new();
        let top = Command::new("git").args(["-C", &root().to_string_lossy(), "rev-parse", "--show-toplevel"]).output().ok()
            .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_default();
        let same = !top.is_empty() && std::fs::canonicalize(&top).ok() == std::fs::canonicalize(root()).ok();
        if same {
            if let Ok(o) = Command::new("git").args(["-C", &root().to_string_lossy(), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]).output() {
                for p in String::from_utf8_lossy(&o.stdout).split('\0') {
                    if p.is_empty() {
                        continue;
                    }
                    if let Ok(m) = std::fs::symlink_metadata(root().join(p)) {
                        if m.is_file() {
                            found.push(p.to_string());
                        }
                    }
                }
            }
        } else {
            let skip = git_ignored();
            let left_out = |rel: &str, dir: bool| -> bool {
                let parts: Vec<&str> = rel.split('/').collect();
                for p in &skip {
                    let folder = p.ends_with('/');
                    let q = p.trim_matches('/');
                    if q.contains('/') {
                        if rel == q || rel.starts_with(&format!("{}/", q)) || fnmatch(rel, q) {
                            return true;
                        }
                    } else {
                        let cand: &[&str] = if !dir && folder { &parts[..parts.len() - 1] } else { &parts };
                        if cand.iter().any(|n| fnmatch(n, q)) {
                            return true;
                        }
                    }
                }
                false
            };
            fn walk(rel: &str, found: &mut Vec<String>, left_out: &dyn Fn(&str, bool) -> bool) {
                let base = if rel == "." { root().to_path_buf() } else { root().join(rel) };
                let Ok(entries) = std::fs::read_dir(&base) else { return };
                let mut dirs = Vec::new();
                let mut names = Vec::new();
                for e in entries.flatten() {
                    let n = e.file_name().to_string_lossy().to_string();
                    if e.file_type().map(|t| t.is_dir()).unwrap_or(false) { dirs.push(n); } else { names.push(n); }
                }
                dirs.sort();
                names.sort();
                for n in names {
                    let p = if rel == "." { n.clone() } else { format!("{}/{}", rel, n) };
                    if let Ok(m) = std::fs::symlink_metadata(root().join(&p)) {
                        if m.is_file() && !left_out(&p, false) {
                            found.push(p);
                        }
                    }
                }
                for d in dirs {
                    let p = if rel == "." { d.clone() } else { format!("{}/{}", rel, d) };
                    if !skip_set().contains(d.as_str()) && !left_out(&p, true) {
                        walk(&p, found, left_out);
                    }
                }
            }
            walk(".", &mut found, &left_out);
        }
        let mut kept: Vec<String> = found.into_iter().filter(|p| !ignored(p)).collect();
        kept.sort();
        kept
    })
}

/// The [pattern, kind, about] of a file without code to read, or None.
pub fn described(p: &str) -> Option<&'static [String; 3]> {
    let name = p.rsplit('/').next().unwrap_or(p);
    cfg().describe.iter().find(|d| fnmatch(p, &d[0]) || fnmatch(name, &d[0]))
}

/// Every file that may carry tags: a code file, not described as something else.
pub fn files() -> &'static Vec<String> {
    CODE.get_or_init(|| repo_files().iter().filter(|p| forms(p).is_some() && described(p).is_none()).cloned().collect())
}

/// The configured prefix, else the folder under a root, else the top folder.
pub fn area_of(p: &str) -> String {
    let mut best: Option<(String, String)> = None;
    for (prefix, area) in &cfg().areas {
        let q = prefix.trim_end_matches('/');
        if q.is_empty() || q == "." {
            if !p.contains('/') && best.is_none() {
                best = Some((String::new(), area.clone()));
            }
        } else if (p == q || p.starts_with(&format!("{}/", q))) && best.as_ref().map(|b| q.len() > b.0.len()).unwrap_or(true) {
            best = Some((q.to_string(), area.clone()));
        }
    }
    if let Some((_, area)) = best {
        return slug(&area);
    }
    let parts: Vec<&str> = p.split('/').collect();
    if parts.len() == 1 {
        return "root".into();
    }
    if cfg().roots.iter().any(|r| r == parts[0]) && parts.len() > 2 {
        return slug(parts[1]);
    }
    let top = parts[0].trim_start_matches('.');
    slug(if top.is_empty() { parts[0] } else { top })
}

static AREAS: OnceLock<HashSet<String>> = OnceLock::new();

pub fn areas() -> &'static HashSet<String> {
    AREAS.get_or_init(|| {
        let mut s: HashSet<String> = files().iter().map(|p| area_of(p)).collect();
        for a in cfg().areas.values() {
            s.insert(slug(a));
        }
        for a in cfg().holds.keys() {
            s.insert(a.clone());
        }
        s
    })
}

pub struct TagPat {
    pub tag: Regex,
    pub looks: Regex,
}

pub fn tag_patterns(form: &[(&str, &str)]) -> &'static TagPat {
    static C: Mutex<Option<HashMap<String, &'static TagPat>>> = Mutex::new(None);
    let key: String = form.iter().map(|(o, c)| format!("{}\0{}\x01", o, c)).collect();
    let mut cache = C.lock().unwrap();
    let map = cache.get_or_insert_with(HashMap::new);
    if let Some(p) = map.get(&key) {
        return p;
    }
    let tags: Vec<String> = form.iter().map(|(o, c)| format!(r"^[ \t]*{}[ \t]*@(map|end)[ \t]+({})(?::[ \t]*(.*?))?[ \t]*{}[ \t]*$", regex::escape(o), ID, regex::escape(c))).collect();
    let looks: Vec<String> = form.iter().map(|(o, _)| format!(r"^[ \t]*{}[ \t]*@(?:map|end)\b", regex::escape(o))).collect();
    let p: &'static TagPat = Box::leak(Box::new(TagPat { tag: Regex::new(&tags.join("|")).unwrap(), looks: Regex::new(&looks.join("|")).unwrap() }));
    map.insert(key, p);
    p
}

/// (kind, id, purpose) of a tag line, whichever comment form it is written in.
pub fn tag_match(p: &TagPat, line: &str) -> Option<(String, String, String)> {
    let caps = p.tag.captures(line)?;
    let mut i = 1;
    while i < caps.len() {
        if let Some(k) = caps.get(i) {
            return Some((k.as_str().to_string(), caps.get(i + 1).map(|m| m.as_str()).unwrap_or("").to_string(),
                caps.get(i + 2).map(|m| m.as_str().trim()).unwrap_or("").to_string()));
        }
        i += 3;
    }
    None
}

pub fn component(id: &str) -> String { id.split('.').take(2).collect::<Vec<_>>().join(".") }

pub fn is_test(p: &str) -> bool {
    static R: OnceLock<Regex> = OnceLock::new();
    let rx = R.get_or_init(|| Regex::new(r"(^|[._-])(test|tests|spec)([._-]|$)").unwrap());
    let name = p.rsplit('/').next().unwrap_or(p);
    if cfg().tests.iter().any(|g| fnmatch(p, g)) {
        return true;
    }
    let parts: Vec<&str> = p.split('/').collect();
    if parts[..parts.len() - 1].iter().any(|x| matches!(*x, "tests" | "test" | "spec" | "specs" | "__tests__")) {
        return true;
    }
    let stem = match name.rfind('.') { Some(i) => &name[..i], None => name };
    rx.is_match(&format!("{}.", stem))
}
// @end map.core.files
