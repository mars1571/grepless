// @map map.guard.scope: what the map reads (the code and the docs of the repository), how a command's paths resolve, and the agents' hook formats
//! The Rust version of python/map-guard.py: the same refusals, the same asks, the same five agents.
use regex::Regex;
use serde_json::{json, Map, Value};
use std::collections::{HashMap, HashSet};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};

pub struct Guard {
    pub root: PathBuf,
    pub ask: String,
    skipped: Vec<String>,
    text: HashSet<String>,
    ignored: Mutex<Option<Vec<String>>>,
}

static G: OnceLock<Guard> = OnceLock::new();
pub fn g() -> &'static Guard { G.get().expect("guard setup") }

const REASON: &str = "This repository's code and docs are read and located through its map, every question of a round in one call (AGENTS.md, \"Finding code\"); it answers what this would, by block, with the code. None of this command ran: send its other steps again. Run instead:\n  ";

fn set(words: &str) -> HashSet<&'static str> {
    let leaked: &'static str = Box::leak(words.to_string().into_boxed_str());
    leaked.split_whitespace().collect()
}
fn skip_set() -> &'static HashSet<&'static str> {
    static T: OnceLock<HashSet<&'static str>> = OnceLock::new();
    T.get_or_init(|| set("node_modules dist build out target vendor venv .venv __pycache__ .git .hg .svn .tox .mypy_cache .pytest_cache .cache coverage .idea .vscode bower_components .next .nuxt .terraform Pods DerivedData map"))
}
fn search_set() -> &'static HashSet<&'static str> { static T: OnceLock<HashSet<&'static str>> = OnceLock::new(); T.get_or_init(|| set("grep egrep fgrep rg ag ack")) }
fn read_set() -> &'static HashSet<&'static str> { static T: OnceLock<HashSet<&'static str>> = OnceLock::new(); T.get_or_init(|| set("cat sed head tail awk nl less more bat cut strings xxd od perl ruby")) }
fn list_set() -> &'static HashSet<&'static str> { static T: OnceLock<HashSet<&'static str>> = OnceLock::new(); T.get_or_init(|| set("ls find tree fd")) }
fn filter_set() -> &'static HashSet<&'static str> { static T: OnceLock<HashSet<&'static str>> = OnceLock::new(); T.get_or_init(|| set("head tail cut grep egrep sort uniq wc sed awk tr column")) }
fn named_set() -> &'static HashSet<&'static str> { static T: OnceLock<HashSet<&'static str>> = OnceLock::new(); T.get_or_init(|| set("Makefile GNUmakefile Dockerfile Containerfile Rakefile Gemfile Justfile Vagrantfile CMakeLists.txt Jenkinsfile")) }

fn rx(s: &'static str) -> &'static Regex {
    static C: Mutex<Option<HashMap<&'static str, &'static Regex>>> = Mutex::new(None);
    let mut c = C.lock().unwrap();
    let m = c.get_or_insert_with(HashMap::new);
    if let Some(r) = m.get(s) { return r; }
    let r: &'static Regex = Box::leak(Box::new(Regex::new(s).unwrap()));
    m.insert(s, r);
    r
}

fn realpath(p: &Path) -> PathBuf {
    let full = if p.is_absolute() { p.to_path_buf() } else { std::env::current_dir().unwrap_or_default().join(p) };
    if let Ok(r) = std::fs::canonicalize(&full) { return r; }
    let mut base = full.clone();
    let mut rest: Vec<std::ffi::OsString> = Vec::new();
    while std::fs::symlink_metadata(&base).is_err() {
        match (base.file_name(), base.parent()) {
            (Some(n), Some(up)) => { rest.insert(0, n.to_os_string()); base = up.to_path_buf(); }
            _ => return full,
        }
    }
    let mut out = std::fs::canonicalize(&base).unwrap_or(base);
    for r in rest { out.push(r); }
    out
}

fn find_root() -> PathBuf {
    if let Ok(r) = std::env::var("MAP_ROOT") { return realpath(Path::new(&r)); }
    let cwd = std::env::current_dir().unwrap_or_default();
    let here = std::env::current_exe().ok().and_then(|e| std::fs::canonicalize(e).ok()).and_then(|e| e.parent().map(|p| p.to_path_buf())).unwrap_or(cwd.clone());
    for start in [&cwd, &here] {
        for mark in ["map.json", ".git"] {
            let mut base = start.clone();
            loop {
                if std::fs::symlink_metadata(base.join(mark)).is_ok() { return base; }
                match base.parent() { Some(up) => base = up.to_path_buf(), None => break }
            }
        }
    }
    cwd
}

fn expanduser(p: &str) -> PathBuf {
    if let Some(rest) = p.strip_prefix('~') {
        if let Ok(home) = std::env::var("HOME") { return PathBuf::from(home).join(rest.trim_start_matches('/')); }
    }
    PathBuf::from(p)
}

/// Finds the root and reads map.json; called once by the commands.
pub fn setup() {
    let root = find_root();
    let cfg: Value = std::fs::read_to_string(root.join("map.json")).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or(Value::Null);
    let command = cfg.get("command").and_then(|c| c.as_str()).filter(|c| !c.is_empty()).unwrap_or("python3 tools/map.py").to_string();
    let mut skipped: Vec<String> = Vec::new();
    for key in [cfg.get("guard").and_then(|g| g.get("skip")), cfg.get("ignore")] {
        if let Some(a) = key.and_then(|v| v.as_array()) {
            skipped.extend(a.iter().map(|e| e.as_str().map(String::from).unwrap_or_else(|| e.to_string())));
        }
    }
    let mut text: HashSet<String> = (".js .mjs .cjs .jsx .ts .tsx .mts .cts .java .kt .kts .scala .groovy .go .rs .swift .c .h .cc .cpp .cxx .hpp .hh .cs \
.m .mm .php .dart .css .scss .less .proto .zig .d .v .py .pyi .rb .rake .sh .bash .zsh .fish .pl .pm .r .R .yml .yaml .toml .ps1 .ex .exs .nim .jl .cmake .tf \
.nix .cr .coffee .mk .html .htm .xml .vue .svelte .astro .xhtml .sql .lua .hs .elm .ada .vhd .clj .cljs .cljc .edn .el .lisp .scm .rkt .erl .hrl .tex .md \
.markdown .rst .txt .adoc .json .ini .cfg .csv .editorconfig").split_whitespace().map(String::from).collect();
    if let Some(f) = cfg.get("forms").and_then(|f| f.as_object()) {
        text.extend(f.keys().cloned());
    }
    let _ = G.set(Guard { root, ask: format!("{} ask ", command), skipped, text, ignored: Mutex::new(None) });
}

/// The path relative to the repository, or None when it is outside it.
pub fn inside(p: &str, base: &str) -> Option<String> {
    let e = expanduser(p);
    let full = realpath(&if e.is_absolute() { e } else { Path::new(base).join(e) });
    let rel = full.strip_prefix(&g().root).ok()?;
    let s = rel.to_string_lossy().to_string();
    Some(if s.is_empty() { ".".into() } else { s })
}

pub fn fnmatch(name: &str, pattern: &str) -> bool { mapcore_fnmatch(name, pattern) }

fn mapcore_fnmatch(name: &str, pattern: &str) -> bool {
    static C: Mutex<Option<HashMap<String, Regex>>> = Mutex::new(None);
    let mut cache = C.lock().unwrap();
    let map = cache.get_or_insert_with(HashMap::new);
    if !map.contains_key(pattern) {
        let p: Vec<char> = pattern.chars().collect();
        let mut out = String::new();
        let mut i = 0;
        while i < p.len() {
            let c = p[i];
            i += 1;
            match c {
                '*' => out.push_str(".*"),
                '?' => out.push('.'),
                '[' => {
                    let mut j = i;
                    if j < p.len() && p[j] == '!' { j += 1; }
                    if j < p.len() && p[j] == ']' { j += 1; }
                    while j < p.len() && p[j] != ']' { j += 1; }
                    if j >= p.len() { out.push_str("\\["); } else {
                        let mut stuff: String = p[i..j].iter().collect::<String>().replace('\\', "\\\\");
                        i = j + 1;
                        if stuff.starts_with('!') { stuff = format!("^{}", &stuff[1..]); } else if stuff.starts_with('^') { stuff = format!("\\{}", stuff); }
                        out.push_str(&format!("[{}]", stuff));
                    }
                }
                c => out.push_str(&regex::escape(&c.to_string())),
            }
        }
        map.insert(pattern.to_string(), Regex::new(&format!("(?s)^(?:{})$", out)).unwrap());
    }
    map[pattern].is_match(name)
}

fn ignored(rel: &str) -> bool {
    let mut guard = g().ignored.lock().unwrap();
    if guard.is_none() {
        let mut pats: Vec<String> = std::fs::read_to_string(g().root.join(".gitignore")).unwrap_or_default().lines()
            .map(|l| l.trim().to_string()).filter(|l| !l.is_empty() && !l.starts_with('#')).collect();
        pats.extend(g().skipped.iter().cloned());
        *guard = Some(pats);
    }
    let parts: Vec<&str> = rel.split('/').collect();
    if parts[..parts.len() - 1].iter().any(|x| skip_set().contains(x)) || skip_set().contains(parts[0]) {
        return true;
    }
    for p in guard.as_ref().unwrap() {
        let folder = p.ends_with('/');
        let q = p.trim_matches('/');
        if q.contains('/') {
            if rel == q || rel.starts_with(&format!("{}/", q)) || fnmatch(rel, q) { return true; }
        } else {
            let is_dir = std::fs::metadata(g().root.join(rel)).map(|m| m.is_dir()).unwrap_or(false);
            let cand: &[&str] = if folder && !is_dir { &parts[..parts.len() - 1] } else { &parts };
            if cand.iter().any(|n| fnmatch(n, q)) { return true; }
        }
    }
    false
}

fn is_text(rel: &str) -> bool {
    let name = rel.rsplit('/').next().unwrap_or(rel);
    let ext = name.rfind('.').map(|i| name[i..].to_lowercase()).unwrap_or_default();
    if named_set().contains(name) || (!ext.is_empty() && g().text.contains(&ext)) { return true; }
    if !name.contains('.') {
        if let Ok(mut f) = std::fs::File::open(g().root.join(rel)) {
            let mut b = [0u8; 2];
            return f.read(&mut b).unwrap_or(0) == 2 && &b == b"#!";
        }
    }
    false
}

fn expand(rel: &str) -> Vec<String> {
    let (folder, name) = match rel.rfind('/') { Some(i) => (&rel[..i], &rel[i + 1..]), None => ("", rel) };
    if rx(r"[*?\[]").is_match(folder) { return vec![]; }
    let dir = if folder.is_empty() { g().root.clone() } else { g().root.join(folder) };
    let Ok(entries) = std::fs::read_dir(dir) else { return vec![] };
    let mut names: Vec<String> = entries.flatten().map(|e| e.file_name().to_string_lossy().to_string()).collect();
    names.sort();
    names.into_iter().filter(|n| fnmatch(n, name)).map(|n| if folder.is_empty() { n } else { format!("{}/{}", folder, n) }).collect()
}

pub fn mapped(rel: Option<&str>, folder_ok: bool) -> bool {
    let Some(rel) = rel else { return false };
    if rx(r"[*?\[]").is_match(rel) {
        return expand(rel).iter().take(50).any(|x| mapped(Some(x), folder_ok));
    }
    if rel == "." { return folder_ok; }
    if rel == "map.yaml" || rel.split('/').next() == Some("map") { return false; }
    let Ok(meta) = std::fs::metadata(g().root.join(rel)) else { return false };
    if meta.is_dir() { return folder_ok && !ignored(rel); }
    is_text(rel) && !ignored(rel)
}

fn quote_word(w: &str) -> String {
    if w.is_empty() { return "''".into(); }
    if rx(r"^[A-Za-z0-9@%+=:,./_-]+$").is_match(w) { return w.to_string(); }
    format!("'{}'", w.replace('\'', "'\"'\"'"))
}
pub fn quote(words: &[String]) -> String { words.iter().map(|w| quote_word(w)).collect::<Vec<_>>().join(" ") }
// @end map.guard.scope

// @map map.guard.commands: a shell line into its commands (heredocs left out, cd followed), and each command's map question
const PUNCT: &str = "();<>|&";

pub fn shell_words(line: &str) -> Vec<String> {
    let r: Vec<char> = line.chars().collect();
    let n = r.len();
    let mut out = Vec::new();
    let mut word = String::new();
    let mut had = false;
    let mut quote: Option<char> = None;
    let mut i = 0;
    while i < n {
        let c = r[i];
        if let Some(q) = quote {
            if c == q { quote = None; }
            else if q == '"' && c == '\\' && i + 1 < n && "\"\\$`\n".contains(r[i + 1]) { word.push(r[i + 1]); i += 1; }
            else { word.push(c); }
        } else if c == '\'' || c == '"' {
            quote = Some(c);
            had = true;
        } else if c == '\\' && i + 1 < n {
            word.push(r[i + 1]);
            had = true;
            i += 1;
        } else if c.is_whitespace() {
            if had { out.push(std::mem::take(&mut word)); had = false; }
        } else if PUNCT.contains(c) {
            if had { out.push(std::mem::take(&mut word)); had = false; }
            let mut j = i;
            while j < n && PUNCT.contains(r[j]) { j += 1; }
            out.push(r[i..j].iter().collect());
            i = j;
            continue;
        } else if c == '#' && !had {
            break;
        } else {
            word.push(c);
            had = true;
        }
        i += 1;
    }
    if had { out.push(word); }
    out
}

struct Heredoc { start: usize, end: usize, head: String, body: String }

fn heredocs(line: &str) -> Vec<Heredoc> {
    let head_rx = rx(r#"^<<-?\s*(['"]?)(\w+)"#);
    let mut out = Vec::new();
    let mut pos = 0;
    while let Some(off) = line[pos..].find("<<") {
        let i = pos + off;
        let Some(m) = head_rx.captures(&line[i..]) else { pos = i + 2; continue };
        let q = m.get(1).map(|x| x.as_str()).unwrap_or("");
        if !q.is_empty() && !line[i + m.get(0).unwrap().end()..].starts_with(q) { pos = i + 2; continue; }
        let Some(he) = line[i..].find('\n') else { pos = i + 2; continue };
        let head_end = i + he;
        let tag = m.get(2).unwrap().as_str().to_string();
        let mut k = head_end + 1;
        let body_start = k;
        let mut end = None;
        while k <= line.len() {
            let nl = line[k..].find('\n');
            let seg = match nl { Some(j) => &line[k..k + j], None => &line[k..] };
            if seg.trim() == tag {
                end = Some(match nl { Some(j) => k + j, None => line.len() });
                let body = if k > body_start { line[body_start..k - 1].to_string() } else { String::new() };
                let head = line[line[..i].rfind('\n').map(|x| x + 1).unwrap_or(0)..i].to_string();
                out.push(Heredoc { start: i, end: end.unwrap(), head, body });
                break;
            }
            match nl { Some(j) => k += j + 1, None => break }
        }
        pos = end.unwrap_or(i + 2);
    }
    out
}

fn marker_len(s: &str) -> usize {
    let m = rx(r#"^<<-?\s*(['"]?)(\w+)"#).captures(s).unwrap();
    m.get(0).unwrap().end() + if m.get(1).map(|x| !x.as_str().is_empty()).unwrap_or(false) { 1 } else { 0 }
}

fn without_heredocs(line: &str) -> String {
    let mut line = line.to_string();
    for h in heredocs(&line.clone()).into_iter().rev() {
        let head_end = line[h.start..].find('\n').unwrap() + h.start;
        let ml = marker_len(&line[h.start..]);
        line = format!("{}{}{}", &line[..h.start], &line[h.start + ml..head_end], &line[h.end..]);
    }
    line
}

pub struct Cmd { pub words: Vec<String>, pub piped: bool, pub base: String }

pub fn commands(line: &str, cwd: &str) -> Vec<Cmd> {
    let line = without_heredocs(line).replace("\\\n", " ").replace('\n', " ; ");
    let line = rx(r"\d?>&\d|\d?>\s*/dev/null").replace_all(&line, " ").to_string();
    let mut split: Vec<String> = Vec::new();
    for t in shell_words(&line) {
        if rx(r"^[|&;()<>]+$").is_match(&t) {
            split.extend(rx(r"\|\||&&|\|&|;;|>>|&>|[|&;()<>]").find_iter(&t).map(|m| m.as_str().to_string()));
        } else {
            split.push(t);
        }
    }
    split.push(";".into());
    let mut out = Vec::new();
    let mut words: Vec<String> = Vec::new();
    let mut piped = false;
    let mut base = cwd.to_string();
    for t in split {
        if matches!(t.as_str(), "|" | "||" | "&&" | ";" | "&" | "(" | ")" | "|&" | ";;" | "\n") {
            if !words.is_empty() {
                if words[0] == "cd" && words.len() > 1 {
                    let e = expanduser(&words[1]);
                    base = (if e.is_absolute() { e } else { Path::new(&base).join(e) }).to_string_lossy().to_string();
                } else {
                    out.push(Cmd { words: std::mem::take(&mut words), piped, base: base.clone() });
                }
            }
            piped = t == "|" || t == "|&";
            words = Vec::new();
        } else {
            words.push(t);
        }
    }
    out
}

fn unique(xs: &[String]) -> Vec<String> {
    let mut seen = HashSet::new();
    xs.iter().filter(|x| seen.insert((*x).clone())).cloned().collect()
}

pub fn grep_question(words: &[String], base: &str) -> Option<Vec<String>> {
    let (mut pats, mut paths, mut includes) = (Vec::new(), Vec::new(), Vec::new());
    let mut flags: HashSet<String> = HashSet::new();
    let mut i = 1;
    while i < words.len() {
        let a = &words[i];
        if a == "-e" || a == "--regexp" {
            pats.push(words.get(i + 1).cloned().unwrap_or_default());
            i += 2;
            continue;
        }
        if let Some(g) = a.strip_prefix("--include=") { includes.push(g.to_string()); }
        else if matches!(a.as_str(), "-A" | "-B" | "-C" | "-m" | "--max-count" | "-g" | "--glob" | "-t" | "--type" | "--include" | "--exclude") {
            if matches!(a.as_str(), "-g" | "--glob" | "--include") { includes.push(words.get(i + 1).cloned().unwrap_or_default()); }
            i += 2;
            continue;
        } else if a.starts_with("--") { flags.insert(a.clone()); }
        else if a.starts_with('-') && a.len() > 1 { for ch in a[1..].chars() { flags.insert(ch.to_string()); } }
        else { paths.push(a.clone()); }
        i += 1;
    }
    if pats.is_empty() && !paths.is_empty() { pats = vec![paths.remove(0)]; }
    if ["c", "q", "l", "L", "--count", "--quiet", "--silent", "--files-with-matches", "--files-without-match"].iter().any(|f| flags.contains(*f)) { return None; }
    let recursive = matches!(words[0].as_str(), "rg" | "ag" | "ack") || ["r", "R", "--recursive"].iter().any(|f| flags.contains(*f));
    if paths.is_empty() && !recursive { return None; }
    let rels: Vec<Option<String>> = if paths.is_empty() { vec![inside(".", base)] } else { paths.iter().map(|p| inside(p, base)).collect() };
    if !rels.iter().any(|r| mapped(r.as_deref(), true)) { return None; }
    let mut places: Vec<String> = rels.iter().flatten().filter(|r| *r != ".").cloned().collect();
    if !includes.is_empty() {
        let bases = if places.is_empty() { vec![String::new()] } else { places.clone() };
        places = bases.iter().flat_map(|p| includes.iter().map(move |gl| {
            let joined = if p.is_empty() { format!("*{}", gl.trim_start_matches('*')) } else { format!("{}/*{}", p, gl.trim_start_matches('*')) };
            joined.trim_start_matches('/').to_string()
        })).collect();
    }
    let pattern = pats.join("|");
    if pattern.contains("@map") {
        if let Some(m) = rx(r"@map\s+([\w.-]+)").captures(&pattern) { return Some(vec![m[1].to_string()]); }
        return Some(if places.is_empty() { vec![".".into()] } else { places });
    }
    if rx(r"^\^#+.*$").is_match(&pattern) && places.iter().all(|p| p.ends_with(".md")) { return Some(places); }
    let plain = words[0] == "grep" && !flags.contains("E") && !flags.contains("P");
    let alternatives: Vec<String> = pats.iter().flat_map(|p| if plain { rx(r"\\\||\|").split(p).map(String::from).collect::<Vec<_>>() } else { p.split('|').map(String::from).collect() }).collect();
    let names: Vec<String> = alternatives.iter().map(|a| rx(r"^\^?\s*(?:(?:export|async|pub|public|private|static)\s+)*(?:function\*?|def|fn|func|class|const|let|var|val)\s+|(?:\\?\(|\\s\*=|\s*=|\\b)$").replace_all(a, "").to_string()).collect();
    if !names.is_empty() && names.iter().all(|n| rx(r"^[#.]?[A-Za-z_$][\w$-]*$").is_match(n)) && !flags.contains("v") && !flags.contains("F") {
        let mut out = unique(&names);
        if !places.is_empty() { out.push("--in".into()); out.push(places.join(",")); }
        return Some(out);
    }
    let mut r = if flags.contains("F") { regex::escape(&pattern) }
        else if flags.contains("E") || flags.contains("P") || matches!(words[0].as_str(), "egrep" | "rg" | "ag" | "ack") { pattern.clone() }
        else { rx(r"\\([|(){}+?])|([|(){}+?])").replace_all(&pattern, |c: &regex::Captures| c.get(1).map(|m| m.as_str().to_string()).unwrap_or_else(|| format!("\\{}", &c[2]))).to_string() };
    if flags.contains("w") { r = format!("\\b(?:{})\\b", r); }
    if flags.contains("i") { r = format!("(?i){}", r); }
    let mut out = vec![r];
    if !places.is_empty() { out.push("--in".into()); out.push(places.join(",")); }
    Some(out)
}

fn count_lines(rel: &str) -> usize {
    let text = std::fs::read_to_string(g().root.join(rel)).unwrap_or_default();
    if text.is_empty() { return 0; }
    text.matches('\n').count() + if text.ends_with('\n') { 0 } else { 1 }
}

pub fn read_question(words: &[String], base: &str) -> Option<Vec<String>> {
    let tool = words[0].as_str();
    let args = &words[1..];
    if tool == "sed" && args.iter().any(|a| a.starts_with("-i") || a == "--in-place") { return None; }
    if (tool == "perl" || tool == "ruby") && args.iter().any(|a| rx(r"^-\w*i\S*$").is_match(a)) { return None; }
    let mut script = String::new();
    let files: Vec<String> = match tool {
        "sed" => { let rest: Vec<&String> = args.iter().filter(|a| !a.starts_with('-')).collect(); if let Some(f) = rest.first() { script = (*f).clone(); } rest.iter().skip(1).map(|s| (*s).clone()).collect() }
        "awk" => args.iter().filter(|a| !a.starts_with('-')).skip(1).cloned().collect(),
        _ => args.iter().enumerate().filter(|(k, a)| !a.starts_with('-') && !(*k > 0 && matches!(args[k - 1].as_str(), "-n" | "-c" | "-f" | "-d"))).map(|(_, a)| a.clone()).collect(),
    };
    let (mut n, mut from_start, mut no_n) = (10usize, false, false);
    for (k, a) in args.iter().enumerate() {
        if a.starts_with("-c") { no_n = true; continue; }
        if let Some(m) = rx(r"^-n(\+?\d+)?$|^-(\d+)$").captures(a) {
            let v = m.get(1).or_else(|| m.get(2)).map(|x| x.as_str().to_string()).unwrap_or_else(|| args.get(k + 1).cloned().unwrap_or_else(|| "10".into()));
            let d = v.trim_start_matches('+');
            n = if rx(r"^\d+$").is_match(d) { d.parse().unwrap_or(10) } else { 10 };
            from_start = v.starts_with('+');
        }
    }
    let mut rels: Vec<Option<String>> = Vec::new();
    for f in &files {
        let r = inside(f, base);
        match (&r, rx(r"[*?\[]").is_match(f)) {
            (Some(rr), true) => rels.extend(expand(rr).into_iter().map(Some)),
            _ => rels.push(r),
        }
    }
    if files.is_empty() || !rels.iter().any(|r| mapped(r.as_deref(), false)) { return None; }
    let mut out = Vec::new();
    for rel in rels.into_iter().flatten() {
        if !mapped(Some(&rel), false) { continue; }
        let count = count_lines(&rel);
        let m = rx(r"^(\d+)(?:,(\d+|\$))?p$").captures(&script);
        let named = rx(r"/\^?\s*(?:(?:export|async|pub)\s+)*(?:function|def|fn|func|class|const)\s+([A-Za-z_$][\w$]*)").captures(&script);
        if let Some(m) = m {
            let end = match m.get(2).map(|x| x.as_str()) { Some("$") => count.to_string(), Some(e) => e.to_string(), None => m[1].to_string() };
            out.push(format!("{}:{}-{}", rel, &m[1], end));
        } else if let Some(nm) = named {
            out.push(nm[1].to_string()); out.push("--in".into()); out.push(rel);
        } else if tool == "head" && !no_n && n > 0 {
            out.push(format!("{}:1-{}", rel, count.min(n)));
        } else if tool == "tail" && !no_n && n > 0 {
            let start = if from_start { n } else { (count as isize - n as isize + 1).max(1) as usize };
            out.push(format!("{}:{}-{}", rel, start, count));
        } else {
            out.push(rel);
        }
    }
    Some(out)
}

pub fn list_question(words: &[String], base: &str) -> Option<Vec<String>> {
    let args: Vec<&String> = words[1..].iter().filter(|a| !a.starts_with('-')).collect();
    if words[0] == "find" {
        if words.iter().any(|a| matches!(a.as_str(), "-newer" | "-mtime" | "-mmin" | "-size" | "-exec" | "-delete" | "-empty" | "-perm")) { return None; }
        let pattern = words.iter().enumerate().find(|(k, a)| (*a == "-name" || *a == "-iname") && k + 1 < words.len()).map(|(k, _)| words[k + 1].clone());
        let root = words[1..].iter().find(|a| !a.starts_with('-') && Some((*a).clone()) != pattern).cloned().unwrap_or_else(|| ".".into());
        let rel = inside(&root, base);
        if !mapped(rel.as_deref(), true) || (rel.as_deref() == Some(".") && pattern.is_none()) { return None; }
        let rel = rel.unwrap();
        return Some(vec![match pattern {
            Some(p) => { let dir = if rel == "." { String::new() } else { rel }; let star = format!("*{}", p.trim_start_matches('*')); if dir.is_empty() { star } else { format!("{}/{}", dir, star) } }
            None => rel,
        }]);
    }
    let out: Vec<String> = args.iter().filter_map(|a| inside(a, base)).filter(|r| mapped(Some(r), true) && r != ".").collect();
    if out.is_empty() { None } else { Some(out) }
}
// @end map.guard.commands

// @map map.guard.commands.scripts: a script that opens a file of the code only to print it: python -c, node -e, a heredoc fed to them, a scratch script run by name
fn writes(text: &str) -> bool {
    if rx(r#"write_text\(|write_bytes\(|writeFileSync\(|writeFile\(|appendFileSync\(|open\([^)\n]*,\s*['"][wax+]"#).is_match(text) { return true; }
    let mut pos = 0;
    while let Some(off) = text[pos..].find(".write(") {
        let i = pos + off;
        if !(text[..i].ends_with("stdout") || text[..i].ends_with("stderr")) { return true; }
        pos = i + 7;
    }
    false
}

fn inline_scripts(line: &str) -> Vec<String> {
    let mut out = Vec::new();
    for m in rx(r#"\b(?:python3?\s+-c|node\s+(?:-e|--eval|-p|--print))\s+(['"])"#).captures_iter(line) {
        let q = &m[1];
        let start = m.get(0).unwrap().end();
        let mut i = start;
        while let Some(off) = line[i..].find(q) {
            let j = i + off;
            if j > 0 && &line[j - 1..j] != "\\" { out.push(line[start..j].to_string()); break; }
            i = j + 1;
        }
    }
    out
}

fn scripts(line: &str, cwd: &str) -> Vec<String> {
    let env: HashMap<String, String> = rx(r"(?:^|[;&\s])([A-Za-z_]\w*)=([^\s;&|]+)").captures_iter(line).map(|m| (m[1].to_string(), m[2].to_string())).collect();
    let expand_ = |p: &str| -> String {
        let p = p.trim_matches(|c| c == '\'' || c == '"');
        rx(r"\$\{?(\w+)\}?").replace_all(p, |c: &regex::Captures| env.get(&c[1]).cloned().unwrap_or_else(|| c[0].to_string())).to_string()
    };
    let mut out = inline_scripts(line);
    for h in heredocs(line) {
        if rx(r"\b(?:python3?|node)\b").is_match(&h.head) && !rx(r"\b(?:python3?|node)\s+(?:--?[\w=-]+\s+)*[^\s|;&-][^\s|;&]*\.(?:py|mjs|cjs|js)\b").is_match(&h.head) {
            out.push(h.body);
        } else if let Some(to) = rx(r"\bcat\s*>>?\s*(\S+)").captures(&h.head) {
            let target = expand_(&to[1]);
            if target.contains('$') || inside(&target, cwd).is_none() { out.push(h.body); }
        }
    }
    for c in commands(line, cwd) {
        let b = c.words[0].rsplit('/').next().unwrap_or("");
        if matches!(b, "node" | "python" | "python3") && c.words.len() > 1 && !c.words[1].starts_with('-') {
            let name = expand_(&c.words[1]);
            let e = expanduser(&name);
            let f = if e.is_absolute() { e } else { Path::new(&c.base).join(e) };
            if inside(&name, &c.base).is_none() {
                if let Ok(meta) = std::fs::metadata(&f) {
                    if meta.is_file() && meta.len() < 300000 {
                        if let Ok(t) = std::fs::read_to_string(&f) { out.push(t); }
                    }
                }
            }
        }
    }
    out
}

pub fn script_question(line: &str, cwd: &str) -> Vec<String> {
    let mut out = Vec::new();
    for text in scripts(line, cwd) {
        if !rx(r"\bprint\(|console\.(?:log|dir|table)\(|(?:process|sys)\.stdout\.write\(").is_match(&text) || writes(&text) { continue; }
        let names: HashMap<String, String> = rx(r#"\b([A-Za-z_$][\w$]*)\s*=\s*['"`]([^'"`\n]+)['"`]"#).captures_iter(&text).map(|m| (m[1].to_string(), m[2].to_string())).collect();
        let mut paths = Vec::new();
        for m in rx(r#"\b(?:open|readFileSync|readFile|read_text|read_bytes|Path)\s*\(\s*(?:['"`]([^'"`\n]+)['"`]|([A-Za-z_$][\w$]*)\s*[,)])"#).captures_iter(&text) {
            if let Some(lit) = m.get(1) { paths.push(lit.as_str().to_string()); }
            else if let Some(v) = m.get(2) {
                if let Some(nv) = names.get(v.as_str()) { paths.push(nv.clone()); }
                else {
                    for l in rx(r"\bfor\s*\(?\s*(?:const\s+|let\s+|var\s+)?(\w+)\s+(?:in|of)\s+[\[(]([^\])]*)[\])]").captures_iter(&text) {
                        if &l[1] == v.as_str() {
                            for p in rx(r#"['"`]([^'"`\s]+\.(?:js|mjs|cjs|ts|css|html|py|rb|go|rs|java|sh|md|json|yaml|yml|toml|txt))['"`]"#).captures_iter(&l[2]) { paths.push(p[1].to_string()); }
                        }
                    }
                }
            }
        }
        let dumped = rx(r"\b(\w+)\s*=\s*(?:json\.load|JSON\.parse)\(").captures_iter(&text).any(|m| {
            let v = regex::escape(&m[1]);
            Regex::new(&format!(r"(?:json\.dumps|JSON\.stringify)\(\s*{}\b|(?:print|console\.log)\(\s*{}\s*\)", v, v)).unwrap().is_match(&text)
        });
        for p in paths {
            if let Some(rel) = inside(&p, cwd) {
                let is_data = [".json", ".yaml", ".yml", ".toml"].iter().any(|d| rel.ends_with(d));
                if mapped(Some(&rel), false) && (!is_data || dumped) { out.push(rel); }
            }
        }
    }
    unique(&out)
}
// @end map.guard.commands.scripts

// @map map.guard.decide: each agent's input read into one shape, the ask that replaces the call, and the answer in the agent's format
fn question(words: &[String], base: &str) -> Option<Vec<String>> {
    let tool = words[0].rsplit('/').next().unwrap_or("").to_string();
    if tool == "git" && words.get(1).map(|s| s == "grep").unwrap_or(false) {
        let mut w = vec!["grep".to_string(), "-r".to_string()]; w.extend(words[2..].iter().cloned());
        return grep_question(&w, base);
    }
    if tool == "xargs" && words.len() > 1 && search_set().contains(words[1].rsplit('/').next().unwrap_or("")) {
        let mut w: Vec<String> = words[1..].to_vec(); w.push("-r".into()); w.push(".".into());
        return grep_question(&w, base);
    }
    let mut w = vec![tool.clone()]; w.extend(words[1..].iter().cloned());
    if search_set().contains(tool.as_str()) { return grep_question(&w, base); }
    if read_set().contains(tool.as_str()) { return read_question(&w, base); }
    if list_set().contains(tool.as_str()) { return list_question(&w, base); }
    None
}

pub fn shell_question(line: &str, cwd: &str) -> Option<String> {
    let first = line.split('\n').next().unwrap_or("");
    if line.contains("map.py") || line.contains("map.mjs") || (g().ask.starts_with("map ") && format!(" {} ", first).contains(" map ")) { return None; }
    let mut asked = script_question(line, cwd);
    let mut filtered = Vec::new();
    let parts = commands(line, cwd);
    for (k, c) in parts.iter().enumerate() {
        if c.piped || c.words.is_empty() || c.words.iter().any(|w| matches!(w.as_str(), ">" | ">>" | "&>")) { continue; }
        let after = parts.get(k + 1);
        let q = if c.words[0] == "find" && after.map(|a| a.piped && a.words.len() > 1 && a.words[0] == "xargs" && search_set().contains(a.words[1].rsplit('/').next().unwrap_or(""))).unwrap_or(false) {
            let a = after.unwrap();
            let pattern = c.words.iter().enumerate().find(|(j, x)| (*x == "-name" || *x == "-iname") && j + 1 < c.words.len()).map(|(j, _)| c.words[j + 1].clone()).unwrap_or_else(|| "*".into());
            let root = c.words[1..].iter().find(|x| !x.starts_with('-')).cloned().unwrap_or_else(|| ".".into());
            let mut w: Vec<String> = a.words[1..].to_vec(); w.push("-r".into()); w.push(root); w.push(format!("--include={}", pattern));
            grep_question(&w, &c.base)
        } else { question(&c.words, &c.base) };
        let Some(q) = q else { continue };
        if q.is_empty() { continue; }
        let mut pipe = Vec::new();
        for w in &parts[k + 1..] {
            if !w.piped || !filter_set().contains(w.words[0].rsplit('/').next().unwrap_or("")) { break; }
            pipe.push(quote(&w.words));
        }
        if pipe.is_empty() { asked.extend(q); } else { filtered.push(format!("{}{} | {}", g().ask, quote(&q), pipe.join(" | "))); }
    }
    let mut all = Vec::new();
    if !asked.is_empty() { all.push(format!("{}{}", g().ask, quote(&asked))); }
    all.extend(filtered);
    if all.is_empty() { None } else { Some(all.join("; ")) }
}

fn truthy(v: Option<&Value>) -> bool {
    match v { None | Some(Value::Null) => false, Some(Value::Bool(b)) => *b, Some(Value::Number(n)) => n.as_f64().unwrap_or(0.0) != 0.0, Some(Value::String(s)) => !s.is_empty(), Some(_) => true }
}
fn s(v: &Map<String, Value>, k: &str) -> String { v.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string() }

fn read_question_tool(path: &str, cwd: &str, offset: Option<&Value>, limit: Option<&Value>) -> Option<String> {
    let rel = inside(path, cwd);
    if !mapped(rel.as_deref(), false) || truthy(limit) || truthy(offset) { return None; }
    Some(format!("{}{}", g().ask, quote(&[rel.unwrap()])))
}

fn normalise(agent: &str, data: &Map<String, Value>) -> (String, Map<String, Value>, String) {
    let mut cwd = s(data, "cwd");
    if cwd.is_empty() { if let Some(r) = data.get("workspace_roots").and_then(|r| r.as_array()).and_then(|a| a.first()).and_then(|x| x.as_str()) { cwd = r.to_string(); } }
    if cwd.is_empty() { cwd = g().root.to_string_lossy().to_string(); }
    let has_tool = data.contains_key("tool_name");
    let obj = |k: &str| data.get(k).and_then(|v| v.as_object()).cloned().unwrap_or_default();
    match agent {
        "cursor" => {
            if data.contains_key("command") && !has_tool { let mut m = Map::new(); m.insert("command".into(), data["command"].clone()); return ("shell".into(), m, cwd); }
            if data.contains_key("file_path") && !has_tool { let mut m = Map::new(); m.insert("file_path".into(), data["file_path"].clone()); return ("read".into(), m, cwd); }
            let name = s(data, "tool_name").to_lowercase();
            let given = obj("tool_input");
            let wd = s(&given, "working_directory");
            if !wd.is_empty() { cwd = wd; }
            let kind = match name.as_str() { "shell" | "bash" | "terminal" => "shell", "read" | "read_file" => "read", _ => "" };
            (kind.into(), given, cwd)
        }
        "copilot" => {
            let mut name = s(data, "toolName").to_lowercase();
            if name.is_empty() { name = s(data, "tool_name").to_lowercase(); }
            let raw = if data.contains_key("toolArgs") { data.get("toolArgs") } else { data.get("tool_input") };
            let given: Map<String, Value> = match raw {
                Some(Value::String(x)) => serde_json::from_str::<Value>(x).ok().and_then(|v| v.as_object().cloned()).unwrap_or_else(|| { let mut m = Map::new(); m.insert("command".into(), json!(x)); m }),
                Some(Value::Object(m)) => m.clone(),
                _ => Map::new(),
            };
            let kind = match name.as_str() { "bash" | "powershell" => "shell", "view" => "read", "grep" => "grep", "glob" => "glob", _ => "" };
            (kind.into(), given, cwd)
        }
        "gemini" => {
            let name = s(data, "tool_name").to_lowercase();
            let given = obj("tool_input");
            let kind = if name.contains("shell") { "shell" } else if name == "read_file" || name == "read_many_files" { "read" } else if name.contains("grep") || name.contains("search_file") { "grep" } else if name == "glob" { "glob" } else if name == "list_directory" { "list" } else { "" };
            (kind.into(), given, cwd)
        }
        _ => {
            let kind = match s(data, "tool_name").as_str() { "Bash" => "shell", "Read" => "read", "Grep" => "grep", "Glob" => "glob", _ => "" };
            (kind.into(), obj("tool_input"), cwd)
        }
    }
}

/// The folder a search, a glob or a listing names (path, or Gemini's dir_path), the working folder by default.
fn folder_of(given: &Map<String, Value>) -> String {
    for k in ["path", "dir_path"] { let p = s(given, k); if !p.is_empty() { return p; } }
    ".".into()
}

/// The map's question for this call, or None when the call may go ahead.
pub fn replacement(agent: &str, data: &Map<String, Value>) -> Option<String> {
    let (kind, given, cwd) = normalise(agent, data);
    match kind.as_str() {
        "shell" => { let mut c = s(&given, "command"); if c.is_empty() { c = s(&given, "cmd"); } shell_question(&c, &cwd) }
        "read" => {
            let mut p = s(&given, "file_path");
            if p.is_empty() { p = s(&given, "absolute_path"); }
            if p.is_empty() { p = s(&given, "path"); }
            if p.is_empty() { p = given.get("paths").and_then(|a| a.as_array()).and_then(|a| a.first()).and_then(|x| x.as_str()).unwrap_or("").to_string(); }
            // a range is offset and limit, or Gemini's start_line and end_line
            let either = |a: &str, b: &str| if truthy(given.get(a)) { given.get(a) } else { given.get(b) };
            read_question_tool(&p, &cwd, either("offset", "start_line"), either("limit", "end_line"))
        }
        "grep" => {
            if s(&given, "output_mode") == "count" { return None; }
            let mut words = vec!["rg".to_string()];
            if truthy(given.get("-i")) || truthy(given.get("case_insensitive")) { words.push("-i".into()); }
            words.push("-e".into()); words.push(s(&given, "pattern"));
            words.push(folder_of(&given));
            for k in ["glob", "include"] { let v = s(&given, k); if !v.is_empty() { words.push("--glob".into()); words.push(v); } }
            grep_question(&words, &cwd).map(|q| format!("{}{}", g().ask, quote(&q)))
        }
        "glob" => {
            let rel = inside(&folder_of(&given), &cwd);
            if !mapped(rel.as_deref(), true) { return None; }
            let dir = rel.filter(|r| r != ".").unwrap_or_default();
            let pat = s(&given, "pattern");
            Some(format!("{}{}", g().ask, quote(&[if dir.is_empty() { pat } else { format!("{}/{}", dir, pat) }])))
        }
        "list" => {
            let rel = inside(&folder_of(&given), &cwd);
            if mapped(rel.as_deref(), true) && rel.as_deref() != Some(".") { Some(format!("{}{}", g().ask, quote(&[rel.unwrap()]))) } else { None }
        }
        _ => None,
    }
}

pub fn detect(data: &Map<String, Value>) -> &'static str {
    let has_tool = data.contains_key("tool_name");
    if data.contains_key("cursor_version") || (data.contains_key("command") && !has_tool) || (data.contains_key("file_path") && !has_tool) { return "cursor"; }
    if data.contains_key("toolName") || matches!(s(data, "tool_name").as_str(), "bash" | "powershell" | "view" | "grep" | "glob" | "create" | "edit") { return "copilot"; }
    if s(data, "hook_event_name") == "BeforeTool" { return "gemini"; }
    "claude"
}

pub fn answer(agent: &str, asked: &str) -> Value {
    let reason = format!("{}{}", REASON, asked);
    match agent {
        "cursor" => json!({"permission": "deny", "user_message": format!("map-guard: read it through the map (ask). {}", asked), "agent_message": reason}),
        "copilot" => json!({"permissionDecision": "deny", "permissionDecisionReason": reason}),
        "gemini" => json!({"decision": "deny", "reason": reason}),
        _ => json!({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}),
    }
}

fn merge(old: &Value, new: &Value) -> Value {
    match (old, new) {
        (Value::Object(o), Value::Object(n)) => {
            let mut out = o.clone();
            for (k, v) in n { let merged = match o.get(k) { Some(ov) => merge(ov, v), None => v.clone() }; out.insert(k.clone(), merged); }
            Value::Object(out)
        }
        (Value::Array(o), Value::Array(n)) => {
            let mut out = o.clone();
            for x in n { if !o.iter().any(|y| y == x) { out.push(x.clone()); } }
            Value::Array(out)
        }
        _ => new.clone(),
    }
}

pub fn install(agent: &str) {
    let exe = std::env::current_exe().ok().and_then(|e| std::fs::canonicalize(e).ok()).unwrap_or_default();
    let root = std::fs::canonicalize(&g().root).unwrap_or_else(|_| g().root.clone());   // links resolved on both sides
    let me = exe.strip_prefix(&root).map(|p| p.to_string_lossy().to_string()).unwrap_or_else(|_| exe.to_string_lossy().to_string());
    let (path, new) = match agent {
        "claude" => (".claude/settings.json", json!({"hooks": {"PreToolUse": [{"matcher": "Bash|Read|Grep|Glob", "hooks": [{"type": "command", "command": format!("\"$CLAUDE_PROJECT_DIR/{}\"", me)}]}]}})),
        "codex" => (".codex/hooks.json", json!({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": format!("\"$(git rev-parse --show-toplevel)/{}\" --agent codex", me), "statusMessage": "map-guard"}]}]}})),
        "cursor" => (".cursor/hooks.json", json!({"version": 1, "hooks": {"beforeShellExecution": [{"command": format!("{} --agent cursor", me)}], "beforeReadFile": [{"command": format!("{} --agent cursor", me)}]}})),
        "copilot" => (".github/hooks/map-guard.json", json!({"version": 1, "hooks": {"preToolUse": [{"type": "command", "bash": format!("{} --agent copilot", me), "cwd": ".", "timeoutSec": 10}]}})),
        "gemini" => (".gemini/settings.json", json!({"hooks": {"BeforeTool": [{"matcher": "run_shell_command|read_file|read_many_files|grep_search|glob|list_directory", "hooks": [{"name": "map-guard", "type": "command", "command": format!("\"$GEMINI_PROJECT_DIR/{}\" --agent gemini", me), "timeout": 5000}]}]}})),
        _ => { eprintln!("install <agent>: one of claude, codex, cursor, copilot, gemini"); std::process::exit(1); }
    };
    let full = g().root.join(path);
    let old: Value = std::fs::read_to_string(&full).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or(json!({}));
    if let Some(dir) = full.parent() { let _ = std::fs::create_dir_all(dir); }
    let _ = std::fs::write(&full, format!("{}\n", serde_json::to_string_pretty(&merge(&old, &new)).unwrap()));
    println!("{}: the map guard installed for {} ({}).{}", path, agent, me, if agent == "codex" { " Codex runs project hooks once the .codex folder is trusted." } else { "" });
}

/// What the map-guard binary runs: stdin in, the decision out.
pub fn main(argv: Vec<String>) {
    setup();
    if argv.len() == 2 && argv[0] == "install" { install(&argv[1]); return; }
    if argv.len() == 2 && argv[0] == "try" {
        let cwd = std::env::current_dir().unwrap_or_default().to_string_lossy().to_string();
        println!("{}", shell_question(&argv[1], &cwd).unwrap_or_else(|| "goes ahead".into()));
        return;
    }
    let mut agent = argv.iter().position(|a| a == "--agent").and_then(|i| argv.get(i + 1)).cloned().unwrap_or_default();
    let mut input = String::new();
    if std::io::stdin().read_to_string(&mut input).is_err() { return; }
    let Ok(Value::Object(data)) = serde_json::from_str::<Value>(&input) else { return };
    if agent.is_empty() { agent = detect(&data).to_string(); }
    if let Some(asked) = replacement(&agent, &data) {
        println!("{}", serde_json::to_string(&answer(&agent, &asked)).unwrap());
    }
}
// @end map.guard.decide
