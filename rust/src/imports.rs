// @map map.code.imports: what each file imports, by language, resolved to the repository's own files
use crate::config::*;
use crate::files::*;
use crate::parse::{facts, Block, Import};
use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

fn import_rules() -> &'static HashMap<&'static str, Vec<Regex>> {
    static T: OnceLock<HashMap<&'static str, Vec<Regex>>> = OnceLock::new();
    T.get_or_init(|| {
        let mut m = HashMap::new();
        let mk = |xs: &[&str]| xs.iter().map(|r| Regex::new(r).unwrap()).collect::<Vec<_>>();
        m.insert("py", mk(&[r"^\s*from\s+([\w.]+)\s+import\b", r"^\s*import\s+([\w.]+(?:\s*,\s*[\w.]+)*)"]));
        m.insert("js", mk(&[r#"\bfrom\s+['"]([^'"]+)['"]"#, r#"\brequire\(\s*['"]([^'"]+)['"]\s*\)"#, r#"\bimport\(\s*['"]([^'"]+)['"]\s*\)"#, r#"^\s*import\s+['"]([^'"]+)['"]"#]));
        m.insert("go", mk(&[r#"^\s*import\s+(?:\w+\s+)?"([^"]+)""#, r#"^\s+(?:\w+\s+)?"([\w./-]+)"\s*$"#]));
        m.insert("rust", mk(&[r"^\s*(?:pub\s+)?use\s+((?:crate|super|self)::[\w:]+)", r"^\s*(?:pub\s+)?mod\s+(\w+)\s*;"]));
        m.insert("jvm", mk(&[r"^\s*import\s+(?:static\s+)?([\w.]+)", r"^\s*using\s+([\w.]+)\s*;"]));
        m.insert("ruby", mk(&[r#"\brequire_relative\s+['"]([^'"]+)['"]"#, r#"\brequire\s+['"]([^'"]+)['"]"#]));
        m.insert("php", mk(&[r#"\b(?:require|include)(?:_once)?\s*\(?\s*(?:__DIR__\s*\.\s*)?['"]([^'"]+)['"]"#, r"^\s*use\s+([\w\\]+)"]));
        m.insert("c", mk(&[r#"^\s*#\s*include\s+"([^"]+)""#]));
        m.insert("sh", mk(&[r"^\s*(?:source|\.)\s+([^\s;|&]+)"]));
        m.insert("css", mk(&[r#"@import\s+(?:url\()?['"]([^'"]+)['"]"#, r#"@use\s+['"]([^'"]+)['"]"#]));
        m.insert("html", mk(&[r#"<script[^>]+src=["']([^"']+)["']"#, r#"<link[^>]+href=["']([^"']+\.css)["']"#]));
        m
    })
}

pub fn import_lang(sfx: &str) -> Option<&'static str> {
    match sfx {
        ".css" | ".scss" | ".less" => Some("css"),
        ".html" | ".htm" => Some("html"),
        ".vue" | ".svelte" | ".astro" => Some("js"),
        _ => crate::decl::lang_of(sfx),
    }
}

/// The imports a file writes, as written, with their lines.
pub fn imports_in(p: &str, text: &str) -> Vec<Import> {
    let Some(lang) = import_lang(&suffix(p).to_lowercase()) else { return vec![] };
    let Some(rs) = import_rules().get(lang) else { return vec![] };
    let open = Regex::new(r"^\s*import\s*\(").unwrap();
    let line_rx = Regex::new(r"^\s*import\b").unwrap();
    let comma = Regex::new(r"\s*,\s*").unwrap();
    let mut out = Vec::new();
    let mut in_block = false;
    for (k, line) in text.split('\n').enumerate() {
        if lang == "go" {
            if open.is_match(line) {
                in_block = true;
                continue;
            }
            if in_block && line.trim() == ")" {
                in_block = false;
                continue;
            }
            if !in_block && !line_rx.is_match(line) {
                continue;
            }
        }
        for rx in rs {
            for caps in rx.captures_iter(line) {
                for one in comma.split(&caps[1]) {
                    out.push(Import { line: k + 1, what: one.trim().to_string() });
                }
            }
        }
    }
    out
}

pub fn normpath(p: &str) -> String {
    let mut out: Vec<&str> = Vec::new();
    for seg in p.split('/') {
        match seg {
            "" | "." => {}
            ".." => {
                if !out.is_empty() && *out.last().unwrap() != ".." { out.pop(); } else { out.push(seg); }
            }
            s => out.push(s),
        }
    }
    if out.is_empty() { ".".into() } else { out.join("/") }
}

pub struct Resolver {
    paths: HashSet<String>,
    by_suffix: HashMap<String, Vec<String>>,
    gomod: String,
}

impl Resolver {
    pub fn new(paths: &[String]) -> Self {
        let mut by_suffix: HashMap<String, Vec<String>> = HashMap::new();
        for p in paths {
            let parts: Vec<&str> = p.split('/').collect();
            for k in 1..=parts.len().min(4) {
                by_suffix.entry(parts[parts.len() - k..].join("/")).or_default().push(p.clone());
            }
        }
        let gomod = if is_file("go.mod") {
            Regex::new(r"(?m)^module\s+(\S+)").unwrap().captures(&read_file("go.mod")).map(|c| c[1].to_string()).unwrap_or_default()
        } else { String::new() };
        Resolver { paths: paths.iter().cloned().collect(), by_suffix, gomod }
    }

    fn file(&self, p: &str) -> Option<String> {
        let q = normpath(p);
        if self.paths.contains(&q) { Some(q) } else { None }
    }

    pub fn resolve(&self, p: &str, what: &str) -> HashSet<String> {
        let folder = p.rfind('/').map(|i| p[..i].to_string()).unwrap_or_else(|| ".".into());
        let lang = import_lang(&suffix(p).to_lowercase()).unwrap_or("");
        let exts: Vec<&str> = match lang {
            "js" => vec![".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".mts", ".cts", ".vue", ".svelte"],
            "py" => vec![".py"], "ruby" => vec![".rb"], "rust" => vec![".rs"], "css" => vec![".css", ".scss", ".less"], "go" => vec![".go"],
            "jvm" => vec![".java", ".kt", ".scala", ".cs"], "php" => vec![".php"], "c" => vec![".h", ".hpp", ".c", ".cc", ".cpp"],
            "sh" => vec!["", ".sh"], "html" => vec![""], _ => vec![""],
        };
        let mut found = HashSet::new();
        let rel_lang = matches!(lang, "c" | "css" | "html" | "sh" | "php" | "ruby");
        let first = what.split('/').next().unwrap_or("");
        if what.starts_with("./") || what.starts_with("../") || what.starts_with('/') || (rel_lang && what.contains('/'))
            || (lang == "js" && !what.starts_with('.') && what.contains('/') && matches!(first, "src" | "lib" | "app")) {
            let base = if what.starts_with('/') { what.trim_start_matches('/').to_string() } else { format!("{}/{}", folder, what) };
            let mut cands = vec![base.clone()];
            cands.extend(candidates(&base, &exts));
            for c in cands {
                if let Some(f) = self.file(&c) {
                    found.insert(f);
                    break;
                }
            }
        } else if lang == "py" {
            let dots = what.len() - what.trim_start_matches('.').len();
            let name = what.trim_start_matches('.');
            let bases: Vec<String> = if dots > 0 {
                let mut up = folder.clone();
                for _ in 0..dots.saturating_sub(1) {
                    up = up.rfind('/').map(|i| up[..i].to_string()).unwrap_or_else(|| ".".into());
                }
                vec![up]
            } else {
                let mut b = vec![".".to_string(), folder.clone()];
                b.extend(cfg().roots.iter().filter(|r| is_dir(r)).cloned());
                b
            };
            let rel = name.replace('.', "/");
            for b in &bases {
                let base = if rel.is_empty() { b.clone() } else { format!("{}/{}", b, rel) };
                for c in candidates(&base, &[".py"]) {
                    if let Some(f) = self.file(&c) {
                        found.insert(f);
                        break;
                    }
                }
                if !found.is_empty() {
                    break;
                }
            }
            if found.is_empty() && !rel.is_empty() {
                for key in [format!("{}.py", rel), format!("{}/__init__.py", rel)] {
                    if let Some(v) = self.by_suffix.get(&key) {
                        for c in v {
                            found.insert(c.clone());
                        }
                    }
                }
            }
        } else if lang == "go" && !self.gomod.is_empty() && what.starts_with(&self.gomod) {
            let rel = what[self.gomod.len()..].trim_matches('/');
            let rel = if rel.is_empty() { "." } else { rel };
            for q in &self.paths {
                if q.ends_with(".go") && q.rfind('/').map(|i| &q[..i]).unwrap_or(".") == rel {
                    found.insert(q.clone());
                }
            }
        } else if lang == "rust" {
            let w = what.replace("crate::", "").replace("self::", "").replace("super::", "");
            let parts: Vec<&str> = w.split("::").filter(|x| !x.is_empty() && *x != "crate").collect();
            for k in (1..=parts.len()).rev() {
                for r in ["src".to_string(), folder.clone()] {
                    for c in candidates(&format!("{}/{}", r, parts[..k].join("/")), &[".rs"]) {
                        if let Some(f) = self.file(&c) {
                            found.insert(f);
                        }
                    }
                }
                if !found.is_empty() {
                    break;
                }
            }
        } else if lang == "jvm" {
            let parts: Vec<&str> = what.split('.').collect();
            for k in (2..=parts.len()).rev() {
                let head = &parts[..k];
                let tail = if head.len() > 4 { &head[head.len() - 4..] } else { head };
                for e in &exts {
                    if let Some(v) = self.by_suffix.get(&format!("{}{}", tail.join("/"), e)) {
                        for c in v {
                            if c.ends_with(&format!("{}{}", head.join("/"), e)) {
                                found.insert(c.clone());
                            }
                        }
                    }
                }
                if !found.is_empty() {
                    break;
                }
            }
        } else if lang == "php" && what.contains('\\') {
            let parts: Vec<&str> = what.trim_matches('\\').split('\\').collect();
            let last2 = if parts.len() > 2 { &parts[parts.len() - 2..] } else { &parts[..] };
            for key in [format!("{}.php", last2.join("/")), format!("{}.php", parts[parts.len() - 1])] {
                if let Some(v) = self.by_suffix.get(&key) {
                    for c in v {
                        found.insert(c.clone());
                    }
                }
            }
        } else if lang == "ruby" {
            for c in candidates(&format!("lib/{}", what), &[".rb"]) {
                if let Some(f) = self.file(&c) {
                    found.insert(f);
                }
            }
        }
        found
    }
}

fn candidates(base: &str, exts: &[&str]) -> Vec<String> {
    let mut out: Vec<String> = exts.iter().map(|e| format!("{}{}", base, e)).collect();
    for e in exts {
        out.push(format!("{}/index{}", base, e));
        out.push(format!("{}/__init__{}", base, e));
        out.push(format!("{}/mod{}", base, e));
    }
    out
}

pub struct Graph {
    pub blocks: Vec<Block>,
    pub by_file: HashMap<String, Vec<Block>>,
    pub purpose: HashMap<String, String>,
    pub main: HashMap<String, String>,
    pub file_edges: HashMap<String, HashSet<String>>,
    pub edges: HashMap<(String, String), usize>,
    pub edge_order: Vec<(String, String)>,
    pub importers: HashMap<String, HashSet<String>>,
}

impl Graph {
    pub fn new(blocks: &[Block]) -> Self {
        let mut by_file: HashMap<String, Vec<Block>> = HashMap::new();
        for b in blocks {
            by_file.entry(b.path.clone()).or_default().push(b.clone());
        }
        let mut purpose = HashMap::new();
        let mut by_path: Vec<&Block> = blocks.iter().collect();
        by_path.sort_by(|a, b| a.path.cmp(&b.path));
        for b in by_path {
            purpose.entry(b.id.clone()).or_insert_with(|| b.purpose.clone());
        }
        let mut main = HashMap::new();
        for (p, bs) in &by_file {
            let mut counts: Vec<(String, usize)> = Vec::new();
            for b in bs {
                let c = component(&b.id);
                match counts.iter_mut().find(|(k, _)| *k == c) {
                    Some(e) => e.1 += b.lines,
                    None => counts.push((c, b.lines)),
                }
            }
            let mut best = counts[0].clone();
            for c in &counts {
                if c.1 > best.1 {
                    best = c.clone();
                }
            }
            main.insert(p.clone(), best.0);
        }
        let paths: Vec<String> = repo_files().iter().filter(|p| is_text_ext(&suffix(p).to_lowercase()) || forms(p).is_some()).cloned().collect();
        let r = Resolver::new(&paths);
        let mut g = Graph { blocks: blocks.to_vec(), by_file, purpose, main, file_edges: HashMap::new(), edges: HashMap::new(), edge_order: Vec::new(), importers: HashMap::new() };
        for p in files() {
            for imp in facts(p).imports {
                for target in sorted(&r.resolve(p, &imp.what)) {
                    if &target == p {
                        continue;
                    }
                    g.file_edges.entry(p.clone()).or_default().insert(target.clone());
                    let src = g.at(p, imp.line).or_else(|| g.main.get(p).cloned());
                    let dst = g.main.get(&target).cloned();
                    if let (Some(src), Some(dst)) = (src, dst) {
                        if component(&src) != dst {
                            let key = (component(&src), dst);
                            if !g.edges.contains_key(&key) {
                                g.edge_order.push(key.clone());
                            }
                            *g.edges.entry(key).or_insert(0) += 1;
                        }
                    }
                }
            }
        }
        let edges: Vec<(String, String)> = g.file_edges.iter().flat_map(|(p, ts)| ts.iter().map(move |t| (p.clone(), t.clone()))).collect();
        for (p, t) in edges {
            g.importers.entry(t).or_default().insert(p);
        }
        g
    }

    /// The innermost block of a file holding a line, or None.
    pub fn at(&self, p: &str, line: usize) -> Option<String> {
        let mut best: Option<&Block> = None;
        if let Some(bs) = self.by_file.get(p) {
            for b in bs {
                if b.first <= line && line <= b.last && best.map(|x| b.first > x.first || (b.first == x.first && b.last < x.last)).unwrap_or(true) {
                    best = Some(b);
                }
            }
        }
        best.map(|b| b.id.clone())
    }
}
// @end map.code.imports
