// @map map.code.declarations: what each file declares (functions, classes, methods, values, headings), by the shape of each language, with each one's lines
use crate::config::*;
use crate::parse::Decl;
use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

pub fn keywords() -> &'static HashSet<&'static str> {
    static T: OnceLock<HashSet<&'static str>> = OnceLock::new();
    T.get_or_init(|| "if for while switch catch return else do new function sizeof typeof throw case super this await yield delete void in of try finally with elif until unless when match loop defer go select foreach lock using fixed typedef struct union enum".split(' ').collect())
}

pub fn lang_of(suffix: &str) -> Option<&'static str> {
    Some(match suffix {
        ".js" | ".mjs" | ".cjs" | ".jsx" | ".ts" | ".tsx" | ".mts" | ".cts" | ".dart" => "js",
        ".go" => "go", ".rs" => "rust",
        ".java" | ".kt" | ".kts" | ".scala" | ".groovy" | ".cs" => "jvm",
        ".swift" => "swift", ".rb" | ".rake" => "ruby", ".php" => "php",
        ".c" | ".h" | ".cc" | ".cpp" | ".cxx" | ".hpp" | ".hh" | ".m" | ".mm" => "c",
        ".sh" | ".bash" | ".zsh" => "sh", ".ex" | ".exs" => "elixir", ".lua" => "lua", ".sql" => "sql",
        ".pl" | ".pm" => "perl", ".py" | ".pyi" => "py",
        _ => return None,
    })
}

fn braces(lang: &str) -> bool { matches!(lang, "js" | "go" | "rust" | "jvm" | "swift" | "php" | "c" | "sh" | "perl") }

fn rules() -> &'static HashMap<&'static str, Vec<(Regex, &'static str)>> {
    static T: OnceLock<HashMap<&'static str, Vec<(Regex, &'static str)>>> = OnceLock::new();
    T.get_or_init(|| {
        let mk = |lang: &str, pairs: &[(&str, &'static str)]| -> Vec<(Regex, &'static str)> {
            pairs.iter().map(|(rx, kind)| (Regex::new(&format!("{}{}", if lang == "sql" { "(?i)" } else { "" }, rx)).unwrap(), *kind)).collect()
        };
        let mut m = HashMap::new();
        m.insert("py", mk("py", &[(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)", "function"), (r"^\s*class\s+([A-Za-z_]\w*)", "class"), (r"^([A-Za-z_]\w*)\s*(?::[^=]+?)?=", "value")]));
        m.insert("js", mk("js", &[
            (r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)", "function"),
            (r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)", "class"),
            (r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+?)?=\s*(?:async\s*)?(?:\([^)]*\)\s*(?::\s*[^=]+?)?=>|function\b|[A-Za-z_$][\w$]*\s*=>|class\b)", "function"),
            (r#"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+?)?=\s*(?:\{|\[|new\s+\w+|['"`\d-]|require\(|await\b)"#, "value"),
            (r"^\s*(?:export\s+)?(?:interface|type|enum|namespace)\s+([A-Za-z_$][\w$]*)", "type"),
            (r"^\s{2,}(?:(?:public|private|protected|static|async|readonly|override|get|set|abstract)\s+)*\*?([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\([^)]*\)\s*(?::\s*[^{;]+)?\s*\{\s*$", "method")]));
        m.insert("go", mk("go", &[(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)", "function"), (r"^type\s+([A-Za-z_]\w*)\s+(?:struct|interface)", "type"), (r"^(?:var|const)\s+([A-Za-z_]\w*)\s", "value")]));
        m.insert("rust", mk("rust", &[
            (r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:const\s+)?(?:unsafe\s+)?fn\s+([A-Za-z_]\w*)", "function"),
            (r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|type|mod|union)\s+([A-Za-z_]\w*)", "type"),
            (r"^\s*impl(?:<[^>]*>)?\s+(?:[\w:<>]+\s+for\s+)?([A-Za-z_]\w*)", "impl"),
            (r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:static|const)\s+([A-Za-z_]\w*)\s*:", "value")]));
        m.insert("jvm", mk("jvm", &[
            (r"^\s*(?:(?:public|private|protected|internal|static|final|abstract|sealed|open|data|inner|override|synchronized|native|default|case|partial)\s+)*(?:class|interface|enum|record|object|trait|struct)\s+([A-Za-z_]\w*)", "class"),
            (r"^\s*(?:(?:public|private|protected|internal|static|final|abstract|override|synchronized|native|default|open|suspend|inline|operator|virtual|async|partial|unsafe|extern|new)\s+)+(?:fun\s+|def\s+)?(?:[\w<>\[\],.?]+\s+)?([A-Za-z_]\w*)\s*(?:<[^>]*>)?\s*\(", "method"),
            (r"^\s+(?:fun|def)\s+(?:<[^>]*>\s*)?(?:[\w.]+\.)?([A-Za-z_]\w*)\s*\(", "method")]));
        m.insert("swift", mk("swift", &[(r"^\s*(?:(?:public|private|internal|fileprivate|open|static|final|override|mutating|class|convenience|required)\s+)*(?:func|class|struct|enum|protocol|extension|actor)\s+([A-Za-z_]\w*)", "function")]));
        m.insert("ruby", mk("ruby", &[(r"^\s*def\s+(?:self\.)?([A-Za-z_]\w*[?!=]?)", "method"), (r"^\s*(?:class|module)\s+([A-Z][\w:]*)", "class")]));
        m.insert("php", mk("php", &[(r"^\s*(?:(?:public|private|protected|static|abstract|final)\s+)*function\s+&?([A-Za-z_]\w*)", "function"), (r"^\s*(?:abstract\s+|final\s+|readonly\s+)*(?:class|interface|trait|enum)\s+([A-Za-z_]\w*)", "class")]));
        m.insert("c", mk("c", &[(r"^[A-Za-z_][\w\s\*&:<>,]*?[\s\*&]([A-Za-z_]\w*)\s*\([^;{]*\)\s*(?:const\s*)?(?:\{|$)", "function"), (r"^\s*(?:typedef\s+)?(?:struct|union|enum|class)\s+([A-Za-z_]\w*)\s*(?:\{|$)", "type"), (r"^#define\s+([A-Za-z_]\w*)", "value")]));
        m.insert("sh", mk("sh", &[(r"^\s*(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\s*\)\s*\{?", "function"), (r"^\s*function\s+([A-Za-z_][\w-]*)", "function")]));
        m.insert("elixir", mk("elixir", &[(r"^\s*defp?\s+([a-z_]\w*[?!]?)", "function"), (r"^\s*defmodule\s+([\w.]+)", "class")]));
        m.insert("lua", mk("lua", &[(r"^\s*(?:local\s+)?function\s+([\w.:]+)", "function")]));
        m.insert("sql", mk("sql", &[(r#"^\s*create\s+(?:or\s+replace\s+)?(?:temp(?:orary)?\s+)?(?:table|view|function|procedure|index|trigger|type)\s+(?:if\s+not\s+exists\s+)?([\w."]+)"#, "sql")]));
        m.insert("perl", mk("perl", &[(r"^\s*sub\s+([A-Za-z_]\w*)", "function")]));
        m
    })
}

fn rx(s: &'static str) -> &'static Regex {
    static C: std::sync::Mutex<Option<HashMap<&'static str, &'static Regex>>> = std::sync::Mutex::new(None);
    let mut c = C.lock().unwrap();
    let m = c.get_or_insert_with(HashMap::new);
    if let Some(r) = m.get(s) {
        return r;
    }
    let r: &'static Regex = Box::leak(Box::new(Regex::new(s).unwrap()));
    m.insert(s, r);
    r
}

/// The last line of the braced body starting on line i (1-based): strings and line comments skipped.
pub fn brace_end(lines: &[&str], i: usize, most: usize) -> usize {
    let (mut depth, mut seen) = (0i32, false);
    let mut quote: Option<u8> = None;
    let limit = (i - 1 + most).min(lines.len());
    for (k, line) in lines.iter().enumerate().take(limit).skip(i - 1) {
        let s = line.as_bytes();
        let mut j = 0;
        while j < s.len() {
            let c = s[j];
            if let Some(q) = quote {
                if c == b'\\' { j += 1; } else if c == q { quote = None; }
            } else if c == b'\'' || c == b'"' || c == b'`' {
                quote = Some(c);
            } else if s[j..].starts_with(b"//") {
                break;
            } else if c == b'{' {
                depth += 1;
                seen = true;
            } else if c == b'}' {
                depth -= 1;
                if seen && depth == 0 {
                    return k + 1;
                }
            }
            j += 1;
        }
        if quote == Some(b'"') || quote == Some(b'\'') {
            quote = None;
        }
        if !seen && k > i && !line.trim().is_empty() && !rx(r"^\s*(\{|//|/\*|\*|#)").is_match(line) {
            return i;
        }
    }
    if !seen { i } else { limit }
}

fn indent_of(s: &str) -> usize { s.len() - s.trim_start_matches([' ', '\t']).len() }

/// The last line of an indented body: to the line before the next at the same indent or less.
pub fn indent_end(lines: &[&str], i: usize, indent: usize) -> usize {
    let mut last = i;
    for (k, s) in lines.iter().enumerate().skip(i) {
        if s.trim().is_empty() {
            continue;
        }
        if indent_of(s) <= indent && k + 1 > i {
            if rx(r"^\s*(?:end|\}|\))\b").is_match(s) {
                return k + 1;
            }
            break;
        }
        last = k + 1;
    }
    last
}

/// What a file declares, read from the shape of its lines.
pub fn declarations_in(p: &str, text: &str) -> Vec<Decl> {
    let lines: Vec<&str> = text.split('\n').collect();
    let sfx = suffix(p).to_lowercase();
    let mut out = Vec::new();
    if is_doc_ext(&sfx) {
        let mut fence = false;
        for (k, line) in lines.iter().enumerate() {
            if line.starts_with("```") {
                fence = !fence;
            } else if !fence {
                if let Some(m) = rx(r"^(#{1,6})\s+(.*)").captures(line) {
                    out.push(Decl { name: m[2].trim().to_string(), kind: "heading".into(), first: k + 1, last: k + 1, what: cut_chars(line.trim(), 120) });
                }
            }
        }
        return out;
    }
    let Some(lang) = lang_of(&sfx) else { return out };
    let Some(rs) = rules().get(lang) else { return out };
    for (k, line) in lines.iter().enumerate() {
        let i = k + 1;
        let lead = line.trim_start_matches([' ', '\t']);
        if line.trim().is_empty() || (rx(r#"^(//|#|\*|/\*|--|"|')"#).is_match(lead) && !(lang == "c" && line.starts_with("#define"))) {
            continue;
        }
        for (r, kind) in rs {
            let Some(caps) = r.captures(line) else { continue };
            let name = caps.get(1).map(|m| m.as_str()).unwrap_or("");
            if keywords().contains(name) {
                continue;
            }
            let end = caps.get(0).unwrap().end();
            if lang == "py" && *kind == "value" && end < line.len() && line.as_bytes()[end] == b'=' {
                continue;
            }
            if lang == "jvm" && *kind == "method" && rx(r"\)\s*[;=]").is_match(&line[end - 1..]) {
                continue;
            }
            if lang == "c" && *kind == "function" {
                let first_word = line.split_whitespace().next().unwrap_or("");
                if line.starts_with(' ') || line.starts_with('\t') || keywords().contains(first_word) {
                    continue;
                }
            }
            let mut first = i;
            let last = if braces(lang) && *kind != "value" {
                brace_end(&lines, i, 1500)
            } else if *kind == "value" {
                let t = line.trim_end_matches([' ', '\t', '\r']);
                if t.ends_with('{') || t.ends_with('[') || t.ends_with('(') { brace_end(&lines, i, 1500) } else { i }
            } else {
                indent_end(&lines, i, indent_of(line))
            };
            if lang == "py" && (*kind == "function" || *kind == "class") {
                while first > 1 && lines[first - 2].trim_start_matches([' ', '\t']).starts_with('@') {
                    first -= 1;
                }
            }
            out.push(Decl { name: name.to_string(), kind: kind.to_string(), first, last: last.max(i), what: cut_chars(line.trim(), 120) });
            break;
        }
    }
    out
}
// @end map.code.declarations
