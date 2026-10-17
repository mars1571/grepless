// @map map.code.declarations: what each file declares (functions, classes, methods, values, headings), by the shape of each language, with each one's lines
package mapcore

import (
	"regexp"
	"strings"
)

var KEYWORDS = set("if for while switch catch return else do new function sizeof typeof throw case super this await yield delete void in of try finally with elif until unless when match loop defer go select foreach lock using fixed typedef struct union enum")

var LANG = map[string]string{".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js", ".ts": "js", ".tsx": "js", ".mts": "js", ".cts": "js", ".dart": "js",
	".go": "go", ".rs": "rust", ".java": "jvm", ".kt": "jvm", ".kts": "jvm", ".scala": "jvm", ".groovy": "jvm", ".cs": "jvm", ".swift": "swift",
	".rb": "ruby", ".rake": "ruby", ".php": "php", ".c": "c", ".h": "c", ".cc": "c", ".cpp": "c", ".cxx": "c", ".hpp": "c", ".hh": "c", ".m": "c", ".mm": "c",
	".sh": "sh", ".bash": "sh", ".zsh": "sh", ".ex": "elixir", ".exs": "elixir", ".lua": "lua", ".sql": "sql", ".pl": "perl", ".pm": "perl", ".py": "py", ".pyi": "py"}

var BRACES = set("js go rust jvm swift php c sh perl")

type declRule struct {
	rx   *regexp.Regexp
	kind string
}

var DECL = map[string][]declRule{}

func rules(lang string, pairs ...string) {
	flag := ""
	if lang == "sql" {
		flag = "(?i)"
	}
	for i := 0; i < len(pairs); i += 2 {
		DECL[lang] = append(DECL[lang], declRule{regexp.MustCompile(flag + pairs[i]), pairs[i+1]})
	}
}

func init() {
	rules("py", `^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)`, "function", `^\s*class\s+([A-Za-z_]\w*)`, "class", `^([A-Za-z_]\w*)\s*(?::[^=]+?)?=`, "value")
	rules("js", `^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)`, "function",
		`^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)`, "class",
		`^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+?)?=\s*(?:async\s*)?(?:\([^)]*\)\s*(?::\s*[^=]+?)?=>|function\b|[A-Za-z_$][\w$]*\s*=>|class\b)`, "function",
		`^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+?)?=\s*(?:\{|\[|new\s+\w+|['"`+"`"+`\d-]|require\(|await\b)`, "value",
		`^\s*(?:export\s+)?(?:interface|type|enum|namespace)\s+([A-Za-z_$][\w$]*)`, "type",
		`^\s{2,}(?:(?:public|private|protected|static|async|readonly|override|get|set|abstract)\s+)*\*?([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\([^)]*\)\s*(?::\s*[^{;]+)?\s*\{\s*$`, "method")
	rules("go", `^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)`, "function", `^type\s+([A-Za-z_]\w*)\s+(?:struct|interface)`, "type", `^(?:var|const)\s+([A-Za-z_]\w*)\s`, "value")
	rules("rust", `^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:const\s+)?(?:unsafe\s+)?fn\s+([A-Za-z_]\w*)`, "function",
		`^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|type|mod|union)\s+([A-Za-z_]\w*)`, "type",
		`^\s*impl(?:<[^>]*>)?\s+(?:[\w:<>]+\s+for\s+)?([A-Za-z_]\w*)`, "impl",
		`^\s*(?:pub(?:\([^)]*\))?\s+)?(?:static|const)\s+([A-Za-z_]\w*)\s*:`, "value")
	rules("jvm", `^\s*(?:(?:public|private|protected|internal|static|final|abstract|sealed|open|data|inner|override|synchronized|native|default|case|partial)\s+)*(?:class|interface|enum|record|object|trait|struct)\s+([A-Za-z_]\w*)`, "class",
		`^\s*(?:(?:public|private|protected|internal|static|final|abstract|override|synchronized|native|default|open|suspend|inline|operator|virtual|async|partial|unsafe|extern|new)\s+)+(?:fun\s+|def\s+)?(?:[\w<>\[\],.?]+\s+)?([A-Za-z_]\w*)\s*(?:<[^>]*>)?\s*\(`, "method",
		`^\s+(?:fun|def)\s+(?:<[^>]*>\s*)?(?:[\w.]+\.)?([A-Za-z_]\w*)\s*\(`, "method")
	rules("swift", `^\s*(?:(?:public|private|internal|fileprivate|open|static|final|override|mutating|class|convenience|required)\s+)*(?:func|class|struct|enum|protocol|extension|actor)\s+([A-Za-z_]\w*)`, "function")
	rules("ruby", `^\s*def\s+(?:self\.)?([A-Za-z_]\w*[?!=]?)`, "method", `^\s*(?:class|module)\s+([A-Z][\w:]*)`, "class")
	rules("php", `^\s*(?:(?:public|private|protected|static|abstract|final)\s+)*function\s+&?([A-Za-z_]\w*)`, "function", `^\s*(?:abstract\s+|final\s+|readonly\s+)*(?:class|interface|trait|enum)\s+([A-Za-z_]\w*)`, "class")
	rules("c", `^[A-Za-z_][\w\s\*&:<>,]*?[\s\*&]([A-Za-z_]\w*)\s*\([^;{]*\)\s*(?:const\s*)?(?:\{|$)`, "function", `^\s*(?:typedef\s+)?(?:struct|union|enum|class)\s+([A-Za-z_]\w*)\s*(?:\{|$)`, "type", `^#define\s+([A-Za-z_]\w*)`, "value")
	rules("sh", `^\s*(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\s*\)\s*\{?`, "function", `^\s*function\s+([A-Za-z_][\w-]*)`, "function")
	rules("elixir", `^\s*defp?\s+([a-z_]\w*[?!]?)`, "function", `^\s*defmodule\s+([\w.]+)`, "class")
	rules("lua", `^\s*(?:local\s+)?function\s+([\w.:]+)`, "function")
	rules("sql", `^\s*create\s+(?:or\s+replace\s+)?(?:temp(?:orary)?\s+)?(?:table|view|function|procedure|index|trigger|type)\s+(?:if\s+not\s+exists\s+)?([\w."]+)`, "sql")
	rules("perl", `^\s*sub\s+([A-Za-z_]\w*)`, "function")
}

var prototypeRx = regexp.MustCompile(`\)\s*[;=]`)
var headingRx = regexp.MustCompile(`^(#{1,6})\s+(.*)`)
var commentStartRx = regexp.MustCompile(`^(//|#|\*|/\*|--|"|')`)
var noBodyRx = regexp.MustCompile(`^\s*(\{|//|/\*|\*|#)`)
var endWordRx = regexp.MustCompile(`^\s*(?:end|\}|\))\b`)

// BraceEnd: the last line of the braced body starting on line i (1-based): strings and line comments skipped.
func BraceEnd(lines []string, i int, most int) int {
	depth, seen := 0, false
	var quote byte
	limit := i - 1 + most
	if limit > len(lines) {
		limit = len(lines)
	}
	for k := i - 1; k < limit; k++ {
		s := lines[k]
		j := 0
		for j < len(s) {
			c := s[j]
			if quote != 0 {
				if c == '\\' {
					j++
				} else if c == quote {
					quote = 0
				}
			} else if c == '\'' || c == '"' || c == '`' {
				quote = c
			} else if strings.HasPrefix(s[j:], "//") {
				break
			} else if c == '{' {
				depth++
				seen = true
			} else if c == '}' {
				depth--
				if seen && depth == 0 {
					return k + 1
				}
			}
			j++
		}
		if quote == '"' || quote == '\'' {
			quote = 0
		}
		if !seen && k > i && strings.TrimSpace(s) != "" && !noBodyRx.MatchString(s) {
			return i
		}
	}
	if !seen {
		return i
	}
	return limit
}

func indentOf(s string) int { return len(s) - len(strings.TrimLeft(s, " \t")) }

// IndentEnd: the last line of an indented body: to the line before the next at the same indent or less.
func IndentEnd(lines []string, i, indent int) int {
	last := i
	for k := i; k < len(lines); k++ {
		s := lines[k]
		if strings.TrimSpace(s) == "" {
			continue
		}
		if indentOf(s) <= indent && k > i-1 {
			if endWordRx.MatchString(s) {
				return k + 1
			}
			break
		}
		last = k + 1
	}
	return last
}

func cut(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n])
}

// DeclarationsIn: what a file declares, read from the shape of its lines.
func DeclarationsIn(p, text string) []Decl {
	lines := strings.Split(text, "\n")
	suffix := strings.ToLower(Suffix(p))
	var out []Decl
	if DOCS[suffix] {
		fence := false
		for k, line := range lines {
			if strings.HasPrefix(line, "```") {
				fence = !fence
			} else if !fence {
				if m := headingRx.FindStringSubmatch(line); m != nil {
					out = append(out, Decl{strings.TrimSpace(m[2]), "heading", k + 1, k + 1, cut(strings.TrimSpace(line), 120)})
				}
			}
		}
		return out
	}
	lang := LANG[suffix]
	rs, ok := DECL[lang]
	if !ok {
		return nil
	}
	for k, line := range lines {
		i := k + 1
		lead := strings.TrimLeft(line, " \t")
		if strings.TrimSpace(line) == "" || (commentStartRx.MatchString(lead) && !(lang == "c" && strings.HasPrefix(line, "#define"))) {
			continue
		}
		for _, r := range rs {
			loc := r.rx.FindStringSubmatchIndex(line)
			if loc == nil {
				continue
			}
			name := line[loc[2]:loc[3]]
			if KEYWORDS[name] {
				continue
			}
			end := loc[1]
			if lang == "py" && r.kind == "value" && end < len(line) && line[end] == '=' {
				continue
			}
			if lang == "jvm" && r.kind == "method" && prototypeRx.MatchString(line[end-1:]) {
				continue
			}
			if lang == "c" && r.kind == "function" {
				fields := strings.Fields(line)
				if (len(line) > 0 && (line[0] == ' ' || line[0] == '\t')) || (len(fields) > 0 && KEYWORDS[fields[0]]) {
					continue
				}
			}
			first, last := i, i
			if BRACES[lang] && r.kind != "value" {
				last = BraceEnd(lines, i, 1500)
			} else if r.kind == "value" {
				t := strings.TrimRight(line, " \t\r")
				if strings.HasSuffix(t, "{") || strings.HasSuffix(t, "[") || strings.HasSuffix(t, "(") {
					last = BraceEnd(lines, i, 1500)
				}
			} else {
				last = IndentEnd(lines, i, indentOf(line))
			}
			if lang == "py" && (r.kind == "function" || r.kind == "class") {
				for first > 1 && strings.HasPrefix(strings.TrimLeft(lines[first-2], " \t"), "@") {
					first--
				}
			}
			if last < i {
				last = i
			}
			out = append(out, Decl{name, r.kind, first, last, cut(strings.TrimSpace(line), 120)})
			break
		}
	}
	return out
}

// @end map.code.declarations
