// @map map.core.rules: the configuration, the comment forms of each language, the repository's files, their areas and the limits
//! The Rust version of python/map.py: the same commands and the same answers (tests/conformance.py checks them).
use indexmap::IndexMap;
use regex::Regex;
use serde_json::{Map, Value};
use std::collections::{HashMap, HashSet};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};

pub const VERSION: &str = "1.0.0";
pub const ID: &str = r"[a-z][a-z0-9-]*(?:\.[a-z0-9-]+)+";
pub const LARGE: u64 = 1_000_000;

pub struct Config {
    pub command: String,
    pub name: String,
    pub roots: Vec<String>,
    pub areas: IndexMap<String, String>,
    pub holds: IndexMap<String, String>,
    pub describe: Vec<[String; 3]>,
    pub ignore: Vec<String>,
    pub forms: HashMap<String, String>,
    pub untagged: usize,
    pub block: usize,
    pub tests: Vec<String>,
    pub recipes: Map<String, Value>,
    pub strict: bool,
    pub guard_skip: Vec<String>,
}

pub struct State {
    pub root: PathBuf,
    pub cfg: Config,
}

static STATE: OnceLock<State> = OnceLock::new();
static OUT: Mutex<String> = Mutex::new(String::new());

pub fn st() -> &'static State { STATE.get().expect("setup") }
pub fn root() -> &'static Path { &st().root }
pub fn cfg() -> &'static Config { &st().cfg }
pub fn cmd() -> &'static str { &cfg().command }

pub fn print(s: &str) {
    let mut o = OUT.lock().unwrap();
    o.push_str(s);
    o.push('\n');
}
pub fn flush() {
    let mut o = OUT.lock().unwrap();
    if !o.is_empty() {
        let stdout = std::io::stdout();
        let mut h = stdout.lock();
        let _ = h.write_all(o.as_bytes());
        let _ = h.flush();
        o.clear();
    }
}
pub fn die(msg: &str) -> ! {
    flush();
    eprintln!("{}", msg);
    std::process::exit(1);
}
pub fn exit(code: i32) -> ! {
    flush();
    std::process::exit(code);
}

pub fn forms_table() -> &'static HashMap<&'static str, Vec<(&'static str, &'static str)>> {
    static T: OnceLock<HashMap<&'static str, Vec<(&'static str, &'static str)>>> = OnceLock::new();
    T.get_or_init(|| {
        HashMap::from([
            ("slash", vec![("/*", "*/"), ("//", "")]),
            ("hash", vec![("#", "")]),
            ("html", vec![("<!--", "-->"), ("/*", "*/"), ("//", "")]),
            ("dash", vec![("--", "")]),
            ("semicolon", vec![(";", "")]),
            ("percent", vec![("%", "")]),
        ])
    })
}

pub fn ext_table() -> &'static HashMap<&'static str, &'static str> {
    static T: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    T.get_or_init(|| {
        let mut m = HashMap::new();
        for (form, exts) in [
            ("slash", ".js .mjs .cjs .jsx .ts .tsx .mts .cts .java .kt .kts .scala .groovy .go .rs .swift .c .h .cc .cpp .cxx .hpp .hh .cs .m .mm .php .dart .css .scss .less .proto .zig .d .v"),
            ("hash", ".py .pyi .rb .rake .sh .bash .zsh .fish .pl .pm .r .R .yml .yaml .toml .ps1 .ex .exs .nim .jl .cmake .tf .nix .cr .coffee .mk"),
            ("html", ".html .htm .xml .vue .svelte .astro .xhtml"),
            ("dash", ".sql .lua .hs .elm .ada .vhd"),
            ("semicolon", ".clj .cljs .cljc .edn .el .lisp .scm .rkt"),
            ("percent", ".erl .hrl .tex"),
        ] {
            for e in exts.split_whitespace() {
                m.insert(e, form);
            }
        }
        m
    })
}

pub fn named_table() -> &'static HashMap<&'static str, &'static str> {
    static T: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    T.get_or_init(|| {
        HashMap::from([("Makefile", "hash"), ("GNUmakefile", "hash"), ("Dockerfile", "hash"), ("Containerfile", "hash"), ("Rakefile", "hash"),
            ("Gemfile", "hash"), ("Justfile", "hash"), ("Vagrantfile", "hash"), ("CMakeLists.txt", "hash"), ("Jenkinsfile", "slash")])
    })
}

pub fn is_text_ext(suffix: &str) -> bool {
    ext_table().contains_key(suffix) || matches!(suffix, ".md" | ".markdown" | ".rst" | ".txt" | ".adoc" | ".json" | ".ini" | ".cfg" | ".csv" | ".editorconfig")
}
pub fn is_doc_ext(suffix: &str) -> bool { matches!(suffix, ".md" | ".markdown" | ".rst" | ".txt" | ".adoc") }

pub fn skip_set() -> &'static HashSet<&'static str> {
    static T: OnceLock<HashSet<&'static str>> = OnceLock::new();
    T.get_or_init(|| {
        "node_modules dist build out target vendor venv .venv __pycache__ .git .hg .svn .tox .mypy_cache .pytest_cache .cache coverage .idea .vscode bower_components .next .nuxt .terraform Pods DerivedData map"
            .split_whitespace().collect()
    })
}

pub fn binary_rx() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| Regex::new(r"(?i)\.(png|jpe?g|gif|webp|ico|pdf|zip|gz|woff2?|ttf|otf|mp4|mp3|bin|exe|dylib|so)$").unwrap())
}

// @map map.core.rules.json: JSON strings and values written as Python writes them, and the words of a name
/// A string as JSON writes it: only quotes, backslashes and control characters escaped.
pub fn jstr(s: &str) -> String {
    let mut out = String::from("\"");
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

/// A value as JSON: compact with ", " and ": " when indent is 0, else one item per line, like Python's json.
pub fn jdump(v: &Value, indent: usize, level: usize) -> String {
    match v {
        Value::Null => "null".into(),
        Value::Bool(b) => if *b { "true".into() } else { "false".into() },
        Value::Number(n) => {
            if let Some(i) = n.as_i64() { i.to_string() } else { format!("{}", n.as_f64().unwrap_or(0.0)) }
        }
        Value::String(s) => jstr(s),
        Value::Array(a) => {
            if a.is_empty() { return "[]".into(); }
            let parts: Vec<String> = a.iter().map(|x| jdump(x, indent, level + 1)).collect();
            wrap("[", "]", parts, indent, level)
        }
        Value::Object(m) => {
            if m.is_empty() { return "{}".into(); }
            let parts: Vec<String> = m.iter().map(|(k, x)| format!("{}: {}", jstr(k), jdump(x, indent, level + 1))).collect();
            wrap("{", "}", parts, indent, level)
        }
    }
}

fn wrap(open: &str, close: &str, parts: Vec<String>, indent: usize, level: usize) -> String {
    if indent == 0 {
        return format!("{}{}{}", open, parts.join(", "), close);
    }
    let pad = " ".repeat(indent * level);
    let pad_in = " ".repeat(indent * (level + 1));
    let inner: Vec<String> = parts.into_iter().map(|p| format!("{}{}", pad_in, p)).collect();
    format!("{}\n{}\n{}{}", open, inner.join(",\n"), pad, close)
}
// @end map.core.rules.json

pub fn commas(n: usize) -> String {
    let s = n.to_string();
    let mut out = String::new();
    for (i, c) in s.chars().enumerate() {
        if i > 0 && (s.len() - i) % 3 == 0 {
            out.push(',');
        }
        out.push(c);
    }
    out
}

/// The lowercase words of a name or a sentence: cartTotal → cart, total; HTMLParser → html, parser.
pub fn tokens(text: &str) -> Vec<String> {
    let t: Vec<char> = text.chars().collect();
    let n = t.len();
    let mut out = Vec::new();
    let mut i = 0;
    while i < n {
        let c = t[i];
        if c.is_uppercase() {
            if i + 1 < n && (t[i + 1].is_lowercase() || t[i + 1].is_ascii_digit()) {
                let mut j = i + 1;
                while j < n && (t[j].is_lowercase() || t[j].is_ascii_digit()) {
                    j += 1;
                }
                out.push(t[i..j].iter().collect::<String>().to_lowercase());
                i = j;
                continue;
            }
            let mut j = i;
            while j < n && t[j].is_uppercase() {
                j += 1;
            }
            if j < n && t[j].is_lowercase() && j - 1 > i {
                j -= 1;
            }
            out.push(t[i..j].iter().collect::<String>().to_lowercase());
            i = j;
        } else if c.is_lowercase() || c.is_ascii_digit() {
            let mut j = i;
            while j < n && (t[j].is_lowercase() || t[j].is_ascii_digit()) {
                j += 1;
            }
            out.push(t[i..j].iter().collect());
            i = j;
        } else {
            i += 1;
        }
    }
    out
}

pub fn words_of(text: &str) -> HashSet<String> { tokens(text).into_iter().collect() }

pub fn lower_words(text: &str) -> Vec<String> {
    static R: OnceLock<Regex> = OnceLock::new();
    let rx = R.get_or_init(|| Regex::new(r"[a-z0-9]+").unwrap());
    rx.find_iter(&text.to_lowercase()).map(|m| m.as_str().to_string()).collect()
}

/// Word occurs in text with no identifier character around it ([\w$] and left before, [\w$] and right after).
pub fn bounded(text: &str, word: &str, left: &str, right: &str) -> bool {
    let mut start = 0;
    while let Some(off) = text[start..].find(word) {
        let i = start + off;
        let ok_before = match text[..i].chars().last() {
            Some(c) => !(c.is_alphanumeric() || c == '_' || c == '$' || left.contains(c)),
            None => true,
        };
        let ok_after = match text[i + word.len()..].chars().next() {
            Some(c) => !(c.is_alphanumeric() || c == '_' || c == '$' || right.contains(c)),
            None => true,
        };
        if ok_before && ok_after {
            return true;
        }
        start = i + 1;
    }
    false
}

/// Python's fnmatch: * matches anything (slashes too), ? one character, [seq] a class.
pub fn fnmatch(name: &str, pattern: &str) -> bool {
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
                    if j >= p.len() {
                        out.push_str("\\[");
                    } else {
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

pub fn slug(name: &str) -> String {
    static R: OnceLock<Regex> = OnceLock::new();
    let rx = R.get_or_init(|| Regex::new(r"[^a-z0-9-]+").unwrap());
    let s = rx.replace_all(&name.to_lowercase(), "-").trim_matches('-').to_string();
    if s.is_empty() || !s.chars().next().unwrap().is_ascii_lowercase() { format!("x{}", s) } else { s }
}

pub fn sorted(set: &HashSet<String>) -> Vec<String> {
    let mut v: Vec<String> = set.iter().cloned().collect();
    v.sort();
    v
}

pub fn unique(xs: &[String]) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for x in xs {
        if seen.insert(x.clone()) {
            out.push(x.clone());
        }
    }
    out
}

pub fn pad_r(s: &str, n: usize) -> String {
    let w = s.chars().count();
    if w >= n { s.to_string() } else { format!("{}{}", s, " ".repeat(n - w)) }
}
pub fn pad_l(s: &str, n: usize) -> String {
    let w = s.chars().count();
    if w >= n { s.to_string() } else { format!("{}{}", " ".repeat(n - w), s) }
}

/// Cuts a text at a space before `most` characters, as Python's text[:text.rfind(' ', 0, most - 1)] + '…'.
pub fn short(text: &str, most: usize) -> String {
    let r: Vec<char> = text.chars().collect();
    if r.len() <= most {
        return text.to_string();
    }
    let mut cut = None;
    let mut i = most as isize - 2;
    while i >= 0 {
        if r[i as usize] == ' ' {
            cut = Some(i as usize);
            break;
        }
        i -= 1;
    }
    match cut {
        Some(c) => format!("{}…", r[..c].iter().collect::<String>()),
        None => "…".into(),
    }
}

pub fn cut_chars(s: &str, n: usize) -> String {
    let r: Vec<char> = s.chars().collect();
    if r.len() <= n { s.to_string() } else { r[..n].iter().collect() }
}

pub fn suffix(p: &str) -> String {
    let name = p.rsplit('/').next().unwrap_or(p);
    match name.rfind('.') {
        Some(0) | None => String::new(),
        Some(i) => name[i..].to_string(),
    }
}

pub fn read_file(p: &str) -> String {
    match std::fs::read(root().join(p)) {
        Ok(b) => String::from_utf8_lossy(&b).into_owned(),
        Err(_) => String::new(),
    }
}
pub fn is_file(p: &str) -> bool { std::fs::metadata(root().join(p)).map(|m| m.is_file()).unwrap_or(false) }
pub fn is_dir(p: &str) -> bool { std::fs::metadata(root().join(p)).map(|m| m.is_dir()).unwrap_or(false) }
pub fn exists(p: &str) -> bool { std::fs::symlink_metadata(root().join(p)).is_ok() }
pub fn size_of(p: &str) -> u64 { std::fs::metadata(root().join(p)).map(|m| m.len()).unwrap_or(0) }

// @map map.core.rules.setup: the root found from the working folder or the binary, map.json read with its defaults, the cache file's name
fn strs(v: Option<&Value>) -> Vec<String> {
    v.and_then(|x| x.as_array()).map(|a| a.iter().map(|e| e.as_str().map(|s| s.to_string()).unwrap_or_else(|| e.to_string())).collect()).unwrap_or_default()
}

fn find_root() -> PathBuf {
    if let Ok(r) = std::env::var("MAP_ROOT") {
        return std::fs::canonicalize(&r).unwrap_or(PathBuf::from(r));
    }
    let cwd = std::env::current_dir().unwrap_or(PathBuf::from("."));
    let exe = std::env::current_exe().ok().and_then(|e| std::fs::canonicalize(e).ok());
    let here = exe.and_then(|e| e.parent().map(|p| p.to_path_buf())).unwrap_or(cwd.clone());
    for mark in ["map.json", ".git"] {
        for start in [&cwd, &here] {
            let mut base = start.clone();
            loop {
                if base.join(mark).exists() {
                    return base;
                }
                match base.parent() {
                    Some(up) => base = up.to_path_buf(),
                    None => break,
                }
            }
        }
    }
    cwd
}

/// Resolves the root and reads map.json; takes --root out of the arguments.
pub fn setup(mut argv: Vec<String>) -> Vec<String> {
    let mut root = None;
    if let Some(i) = argv.iter().position(|a| a == "--root") {
        if i + 1 < argv.len() {
            root = Some(std::fs::canonicalize(&argv[i + 1]).unwrap_or(PathBuf::from(&argv[i + 1])));
            argv.drain(i..i + 2);
        }
    }
    let root = root.unwrap_or_else(find_root);
    let mut cfg = Config {
        command: "python3 tools/map.py".into(), name: String::new(),
        roots: "src lib app apps packages pkg internal cmd services".split(' ').map(String::from).collect(),
        areas: IndexMap::new(), holds: IndexMap::new(), describe: Vec::new(), ignore: Vec::new(), forms: HashMap::new(),
        untagged: 30, block: 16000, tests: Vec::new(), recipes: Map::new(), strict: false, guard_skip: Vec::new(),
    };
    if let Ok(text) = std::fs::read_to_string(root.join("map.json")) {
        let given: Value = match serde_json::from_str(&text) {
            Ok(v) => v,
            Err(e) => { eprintln!("map.json: not JSON ({})", e); std::process::exit(1); }
        };
        let known = ["command", "name", "roots", "areas", "holds", "describe", "ignore", "forms", "limits", "tests", "recipes", "strict", "guard"];
        if let Some(obj) = given.as_object() {
            for (k, v) in obj {
                if !known.contains(&k.as_str()) {
                    eprintln!("map.json: unknown setting \"{}\" (the settings: {})", k, known.join(", "));
                    std::process::exit(1);
                }
                match k.as_str() {
                    "command" => cfg.command = v.as_str().unwrap_or("").to_string(),
                    "name" => cfg.name = v.as_str().unwrap_or("").to_string(),
                    "roots" => cfg.roots = strs(Some(v)),
                    "areas" => if let Some(m) = v.as_object() { cfg.areas = m.iter().map(|(a, b)| (a.clone(), b.as_str().unwrap_or("").to_string())).collect(); },
                    "holds" => if let Some(m) = v.as_object() { cfg.holds = m.iter().map(|(a, b)| (a.clone(), b.as_str().unwrap_or("").to_string())).collect(); },
                    "describe" => if let Some(a) = v.as_array() {
                        for e in a {
                            let mut parts = strs(Some(e));
                            while parts.len() < 3 { parts.push(String::new()); }
                            cfg.describe.push([parts[0].clone(), parts[1].clone(), parts[2].clone()]);
                        }
                    },
                    "ignore" => cfg.ignore = strs(Some(v)),
                    "forms" => if let Some(m) = v.as_object() { for (a, b) in m { cfg.forms.insert(a.clone(), b.as_str().unwrap_or("").to_string()); } },
                    "limits" => if let Some(m) = v.as_object() {
                        if let Some(n) = m.get("untagged").and_then(|x| x.as_u64()) { cfg.untagged = n as usize; }
                        if let Some(n) = m.get("block").and_then(|x| x.as_u64()) { cfg.block = n as usize; }
                    },
                    "tests" => cfg.tests = strs(Some(v)),
                    "recipes" => if let Some(m) = v.as_object() { cfg.recipes = m.clone(); },
                    "strict" => cfg.strict = v.as_bool().unwrap_or(false),
                    "guard" => if let Some(m) = v.as_object() { cfg.guard_skip = strs(m.get("skip")); },
                    _ => {}
                }
            }
        }
    }
    let _ = STATE.set(State { root, cfg });
    argv
}

// @end map.core.rules.setup

pub fn cache_file(prefix: &str) -> PathBuf {
    let mut h: u64 = 0xcbf29ce484222325;
    for b in root().to_string_lossy().as_bytes() {
        h ^= *b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    std::env::temp_dir().join("code-map").join(format!("{}-{:012x}.json", prefix, h & 0xffffffffffff))
}
// @end map.core.rules
