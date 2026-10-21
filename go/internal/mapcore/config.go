// @map map.core.rules: the configuration, the comment forms of each language, the repository's files, their areas and the limits
// Package mapcore is the Go version of python/map.py: the same commands and the same answers (tests/conformance.py checks
// them), the standard library only.
package mapcore

import (
	"bufio"
	"crypto/sha1"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"
)

const Version = "1.0.0"

// Config is map.json: every setting with its default.
type Config struct {
	Command  string
	Name     string
	Roots    []string
	Areas    *OMap // path prefix → area
	Holds    *OMap // area → what it holds
	Describe [][3]string
	Ignore   []string
	Forms    map[string]string
	Limits   map[string]int
	Tests    []string
	Recipes  *OMap // name → recipe (*OMap)
	Strict   bool
	Guard    map[string]any
}

var (
	ROOT, MAP, ZONES string
	CFG              Config
	CMD              string
	UNTAGGED         = 30
	LARGEST          = 16000
	out              = bufio.NewWriterSize(os.Stdout, 1<<16)
)

var FORMS = map[string][][2]string{
	"slash": {{"/*", "*/"}, {"//", ""}}, "hash": {{"#", ""}}, "html": {{"<!--", "-->"}, {"/*", "*/"}, {"//", ""}},
	"dash": {{"--", ""}}, "semicolon": {{";", ""}}, "percent": {{"%", ""}},
}
var EXT = map[string]string{}
var NAMED = map[string]string{"Makefile": "hash", "GNUmakefile": "hash", "Dockerfile": "hash", "Containerfile": "hash", "Rakefile": "hash",
	"Gemfile": "hash", "Justfile": "hash", "Vagrantfile": "hash", "CMakeLists.txt": "hash", "Jenkinsfile": "slash"}
var TEXT = map[string]bool{}
var DOCS = map[string]bool{".md": true, ".markdown": true, ".rst": true, ".txt": true, ".adoc": true}
var SKIP = set("node_modules dist build out target vendor venv .venv __pycache__ .git .hg .svn .tox .mypy_cache .pytest_cache .cache coverage .idea .vscode bower_components .next .nuxt .terraform Pods DerivedData map")
var BINARY = regexp.MustCompile(`(?i)\.(png|jpe?g|gif|webp|ico|pdf|zip|gz|woff2?|ttf|otf|mp4|mp3|bin|exe|dylib|so)$`)

const ID = `[a-z][a-z0-9-]*(?:\.[a-z0-9-]+)+`
const LARGE = 1_000_000

func init() {
	for form, exts := range map[string]string{
		"slash": ".js .mjs .cjs .jsx .ts .tsx .mts .cts .java .kt .kts .scala .groovy .go .rs .swift .c .h .cc .cpp .cxx .hpp .hh .cs .m .mm .php .dart .css .scss .less .proto .zig .d .v",
		"hash":  ".py .pyi .rb .rake .sh .bash .zsh .fish .pl .pm .r .R .yml .yaml .toml .ps1 .ex .exs .nim .jl .cmake .tf .nix .cr .coffee .mk",
		"html":  ".html .htm .xml .vue .svelte .astro .xhtml", "dash": ".sql .lua .hs .elm .ada .vhd",
		"semicolon": ".clj .cljs .cljc .edn .el .lisp .scm .rkt", "percent": ".erl .hrl .tex"} {
		for _, e := range strings.Fields(exts) {
			EXT[e] = form
		}
	}
	for e := range EXT {
		TEXT[e] = true
	}
	for _, e := range []string{".md", ".markdown", ".rst", ".txt", ".adoc", ".json", ".ini", ".cfg", ".csv", ".editorconfig"} {
		TEXT[e] = true
	}
}

func set(words string) map[string]bool {
	m := map[string]bool{}
	for _, w := range strings.Fields(words) {
		m[w] = true
	}
	return m
}

// Print and Die: every answer goes through one buffer; a message to stderr ends the run with code 1, as sys.exit does.
func Print(s string)            { out.WriteString(s); out.WriteByte('\n') }
func Printf(f string, a ...any) { fmt.Fprintf(out, f, a...); out.WriteByte('\n') }
func Flush()                    { out.Flush() }
func Die(msg string) {
	Flush()
	fmt.Fprintln(os.Stderr, msg)
	os.Exit(1)
}
func Exit(code int) { Flush(); os.Exit(code) }

// @map map.core.rules.json: ordered JSON in and out: the key order kept, strings and values written as Python writes them
// OMap is a JSON object with its keys in file order, as Python keeps them.
type OMap struct {
	Keys []string
	Vals map[string]any
}

func NewOMap() *OMap { return &OMap{Vals: map[string]any{}} }
func (m *OMap) Set(k string, v any) {
	if _, ok := m.Vals[k]; !ok {
		m.Keys = append(m.Keys, k)
	}
	m.Vals[k] = v
}
func (m *OMap) Get(k string) (any, bool) { v, ok := m.Vals[k]; return v, ok }
func (m *OMap) Str(k string) string {
	if v, ok := m.Vals[k].(string); ok {
		return v
	}
	return ""
}
func (m *OMap) Len() int { return len(m.Keys) }

// decodeOrdered reads JSON keeping object key order: objects become *OMap, arrays []any, numbers float64 or int64.
func decodeOrdered(dec *json.Decoder) (any, error) {
	t, err := dec.Token()
	if err != nil {
		return nil, err
	}
	switch v := t.(type) {
	case json.Delim:
		if v == '{' {
			m := NewOMap()
			for dec.More() {
				kt, err := dec.Token()
				if err != nil {
					return nil, err
				}
				val, err := decodeOrdered(dec)
				if err != nil {
					return nil, err
				}
				m.Set(kt.(string), val)
			}
			if _, err := dec.Token(); err != nil {
				return nil, err
			}
			return m, nil
		}
		var arr []any
		for dec.More() {
			val, err := decodeOrdered(dec)
			if err != nil {
				return nil, err
			}
			arr = append(arr, val)
		}
		if _, err := dec.Token(); err != nil {
			return nil, err
		}
		if arr == nil {
			arr = []any{}
		}
		return arr, nil
	case json.Number:
		if i, err := v.Int64(); err == nil {
			return i, nil
		}
		f, _ := v.Float64()
		return f, nil
	default:
		return v, nil
	}
}

func ParseJSON(text string) (any, error) {
	dec := json.NewDecoder(strings.NewReader(text))
	dec.UseNumber()
	v, err := decodeOrdered(dec)
	if err != nil {
		return nil, err
	}
	if _, err := dec.Token(); err == nil {
		return nil, fmt.Errorf("extra data")
	}
	return v, nil
}

// Jstr is a string as JSON writes it: only quotes, backslashes and control characters escaped.
func Jstr(s string) string {
	var b strings.Builder
	b.WriteByte('"')
	for _, ch := range s {
		switch ch {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		case '\b':
			b.WriteString(`\b`)
		case '\f':
			b.WriteString(`\f`)
		default:
			if ch < 0x20 {
				fmt.Fprintf(&b, `\u%04x`, ch)
			} else {
				b.WriteRune(ch)
			}
		}
	}
	b.WriteByte('"')
	return b.String()
}

// Jdump is a value as JSON: compact with ", " and ": " when indent is 0, else one item per line, like Python's json.
func Jdump(v any, indent, level int) string {
	switch x := v.(type) {
	case nil:
		return "null"
	case bool:
		if x {
			return "true"
		}
		return "false"
	case int:
		return fmt.Sprint(x)
	case int64:
		return fmt.Sprint(x)
	case float64:
		if x == float64(int64(x)) && !strings.ContainsAny(fmt.Sprint(x), "e.") {
			return fmt.Sprintf("%.1f", x)
		}
		return fmt.Sprint(x)
	case string:
		return Jstr(x)
	case *OMap:
		if x.Len() == 0 {
			return "{}"
		}
		parts := make([]string, 0, x.Len())
		for _, k := range x.Keys {
			parts = append(parts, Jstr(k)+": "+Jdump(x.Vals[k], indent, level+1))
		}
		return wrap("{", "}", parts, indent, level)
	case []any:
		if len(x) == 0 {
			return "[]"
		}
		parts := make([]string, 0, len(x))
		for _, e := range x {
			parts = append(parts, Jdump(e, indent, level+1))
		}
		return wrap("[", "]", parts, indent, level)
	case []string:
		arr := make([]any, len(x))
		for i, s := range x {
			arr[i] = s
		}
		return Jdump(arr, indent, level)
	}
	return fmt.Sprint(v)
}

// Jcompact is a value as one compact JSON document, like Python's json.dumps(separators=(",", ":"), ensure_ascii=False).
func Jcompact(v any) string {
	var b strings.Builder
	writeCompact(&b, v)
	return b.String()
}

func writeCompact(b *strings.Builder, v any) {
	switch x := v.(type) {
	case *OMap:
		b.WriteByte('{')
		for i, k := range x.Keys {
			if i > 0 {
				b.WriteByte(',')
			}
			b.WriteString(Jstr(k) + ":")
			writeCompact(b, x.Vals[k])
		}
		b.WriteByte('}')
	case []any:
		b.WriteByte('[')
		for i, e := range x {
			if i > 0 {
				b.WriteByte(',')
			}
			writeCompact(b, e)
		}
		b.WriteByte(']')
	case []string:
		arr := make([]any, len(x))
		for i, s := range x {
			arr[i] = s
		}
		writeCompact(b, arr)
	default:
		b.WriteString(Jdump(v, 0, 0))
	}
}

// Obj builds an ordered JSON object from key, value pairs.
func Obj(kv ...any) *OMap {
	m := NewOMap()
	for i := 0; i+1 < len(kv); i += 2 {
		m.Set(kv[i].(string), kv[i+1])
	}
	return m
}

// Strs is a list of texts for JSON that is [] and never null when empty.
func Strs(xs []string) []any {
	out := make([]any, len(xs))
	for i, s := range xs {
		out[i] = s
	}
	return out
}

func wrap(open, close string, parts []string, indent, level int) string {
	if indent == 0 {
		return open + strings.Join(parts, ", ") + close
	}
	pad, padIn := strings.Repeat(" ", indent*level), strings.Repeat(" ", indent*(level+1))
	for i := range parts {
		parts[i] = padIn + parts[i]
	}
	return open + "\n" + strings.Join(parts, ",\n") + "\n" + pad + close
}

// @end map.core.rules.json

// Commas formats an integer with thousands separators.
func Commas(n int) string {
	s := fmt.Sprint(n)
	neg := strings.HasPrefix(s, "-")
	if neg {
		s = s[1:]
	}
	var b strings.Builder
	for i, c := range s {
		if i > 0 && (len(s)-i)%3 == 0 {
			b.WriteByte(',')
		}
		b.WriteRune(c)
	}
	if neg {
		return "-" + b.String()
	}
	return b.String()
}

// Tokens are the lowercase words of a name or a sentence: cartTotal → cart, total; HTMLParser → html, parser.
func Tokens(text string) []string {
	t := []rune(text)
	n := len(t)
	var out []string
	i := 0
	for i < n {
		c := t[i]
		switch {
		case unicode.IsUpper(c):
			if i+1 < n && (unicode.IsLower(t[i+1]) || unicode.IsDigit(t[i+1])) {
				j := i + 1
				for j < n && (unicode.IsLower(t[j]) || unicode.IsDigit(t[j])) {
					j++
				}
				out = append(out, strings.ToLower(string(t[i:j])))
				i = j
				continue
			}
			j := i
			for j < n && unicode.IsUpper(t[j]) {
				j++
			}
			if j < n && unicode.IsLower(t[j]) && j-1 > i {
				j--
			}
			out = append(out, strings.ToLower(string(t[i:j])))
			i = j
		case unicode.IsLower(c) || unicode.IsDigit(c):
			j := i
			for j < n && (unicode.IsLower(t[j]) || unicode.IsDigit(t[j])) {
				j++
			}
			out = append(out, string(t[i:j]))
			i = j
		default:
			i++
		}
	}
	return out
}

func WordsOf(text string) map[string]bool {
	m := map[string]bool{}
	for _, w := range Tokens(text) {
		m[w] = true
	}
	return m
}

var lowerWordsRx = regexp.MustCompile(`[a-z0-9]+`)

func LowerWords(text string) []string { return lowerWordsRx.FindAllString(strings.ToLower(text), -1) }

func isAlnumRune(r rune) bool { return unicode.IsLetter(r) || unicode.IsNumber(r) }

// Bounded: word occurs in text with no identifier character around it ([\w$] and left before, [\w$] and right after).
func Bounded(text, word, left, right string) bool {
	start := 0
	for {
		i := strings.Index(text[start:], word)
		if i < 0 {
			return false
		}
		i += start
		okBefore, okAfter := true, true
		if i > 0 {
			r, _ := utf8.DecodeLastRuneInString(text[:i])
			if isAlnumRune(r) || strings.ContainsRune("_$"+left, r) {
				okBefore = false
			}
		}
		if i+len(word) < len(text) {
			r, _ := utf8.DecodeRuneInString(text[i+len(word):])
			if isAlnumRune(r) || strings.ContainsRune("_$"+right, r) {
				okAfter = false
			}
		}
		if okBefore && okAfter {
			return true
		}
		start = i + 1
	}
}

// Fnmatch is Python's fnmatch: * matches anything (slashes too), ? one character, [seq] a class.
var fnCache = map[string]*regexp.Regexp{}

func Fnmatch(name, pattern string) bool {
	re, ok := fnCache[pattern]
	if !ok {
		var b strings.Builder
		p := []rune(pattern)
		i := 0
		for i < len(p) {
			c := p[i]
			i++
			switch c {
			case '*':
				b.WriteString(".*")
			case '?':
				b.WriteString(".")
			case '[':
				j := i
				if j < len(p) && p[j] == '!' {
					j++
				}
				if j < len(p) && p[j] == ']' {
					j++
				}
				for j < len(p) && p[j] != ']' {
					j++
				}
				if j >= len(p) {
					b.WriteString(`\[`)
				} else {
					stuff := strings.ReplaceAll(string(p[i:j]), `\`, `\\`)
					i = j + 1
					if strings.HasPrefix(stuff, "!") {
						stuff = "^" + stuff[1:]
					} else if strings.HasPrefix(stuff, "^") {
						stuff = `\` + stuff
					}
					b.WriteString("[" + stuff + "]")
				}
			default:
				b.WriteString(regexp.QuoteMeta(string(c)))
			}
		}
		re = regexp.MustCompile(`(?s)^(?:` + b.String() + `)$`)
		fnCache[pattern] = re
	}
	return re.MatchString(name)
}

func Slug(name string) string {
	s := regexp.MustCompile(`[^a-z0-9-]+`).ReplaceAllString(strings.ToLower(name), "-")
	s = strings.Trim(s, "-")
	if s == "" || s[0] < 'a' || s[0] > 'z' {
		return "x" + s
	}
	return s
}

func SortedKeys(m map[string]bool) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func Unique(xs []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, x := range xs {
		if !seen[x] {
			seen[x] = true
			out = append(out, x)
		}
	}
	return out
}

func PadR(s string, n int) string {
	w := utf8.RuneCountInString(s)
	if w >= n {
		return s
	}
	return s + strings.Repeat(" ", n-w)
}
func PadL(s string, n int) string {
	w := utf8.RuneCountInString(s)
	if w >= n {
		return s
	}
	return strings.Repeat(" ", n-w) + s
}

// Short cuts a text at a space before `most` characters, as Python's text[:text.rfind(' ', 0, most - 1)] + '…' does.
func Short(text string, most int) string {
	r := []rune(text)
	if len(r) <= most {
		return text
	}
	cut := -1
	for i := most - 2; i >= 0; i-- {
		if r[i] == ' ' {
			cut = i
			break
		}
	}
	if cut < 0 {
		return "…"
	}
	return string(r[:cut]) + "…"
}

func Suffix(p string) string {
	name := p[strings.LastIndex(p, "/")+1:]
	i := strings.LastIndex(name, ".")
	if i <= 0 {
		return ""
	}
	return name[i:]
}

func ReadFile(p string) string {
	b, err := os.ReadFile(filepath.Join(ROOT, p))
	if err != nil {
		return ""
	}
	return strings.ToValidUTF8(string(b), "�")
}

func IsFile(p string) bool {
	st, err := os.Stat(filepath.Join(ROOT, p))
	return err == nil && st.Mode().IsRegular()
}
func IsDir(p string) bool {
	st, err := os.Stat(filepath.Join(ROOT, p))
	return err == nil && st.IsDir()
}
func Exists(p string) bool { _, err := os.Lstat(filepath.Join(ROOT, p)); return err == nil }
func SizeOf(p string) int {
	st, err := os.Stat(filepath.Join(ROOT, p))
	if err != nil {
		return 0
	}
	return int(st.Size())
}

// Setup resolves the root and reads map.json; it takes --root out of the arguments.
func Setup(argv []string) []string {
	root := ""
	for i, a := range argv {
		if a == "--root" && i+1 < len(argv) {
			root, _ = filepath.Abs(argv[i+1])
			argv = append(append([]string{}, argv[:i]...), argv[i+2:]...)
			break
		}
	}
	if root == "" {
		root = findRoot()
	}
	ROOT = root
	MAP = filepath.Join(ROOT, "map.yaml")
	ZONES = filepath.Join(ROOT, "map")
	CFG = Config{Command: "python3 tools/map.py", Roots: []string{"src", "lib", "app", "apps", "packages", "pkg", "internal", "cmd", "services"},
		Areas: NewOMap(), Holds: NewOMap(), Forms: map[string]string{}, Limits: map[string]int{"untagged": 30, "block": 16000, "answer": 28000},
		Recipes: NewOMap(), Guard: map[string]any{"skip": []any{}}}
	if b, err := os.ReadFile(filepath.Join(ROOT, "map.json")); err == nil {
		v, err := ParseJSON(string(b))
		if err != nil {
			Die("map.json: not JSON (" + err.Error() + ")")
		}
		given, _ := v.(*OMap)
		known := set("command name roots areas holds describe ignore forms limits tests recipes strict guard")
		for _, k := range given.Keys {
			if !known[k] {
				Die(`map.json: unknown setting "` + k + `" (the settings: command, name, roots, areas, holds, describe, ignore, forms, limits, tests, recipes, strict, guard)`)
			}
			val := given.Vals[k]
			switch k {
			case "command":
				CFG.Command, _ = val.(string)
			case "name":
				CFG.Name, _ = val.(string)
			case "roots":
				CFG.Roots = strs(val)
			case "areas":
				if m, ok := val.(*OMap); ok {
					CFG.Areas = m
				}
			case "holds":
				if m, ok := val.(*OMap); ok {
					CFG.Holds = m
				}
			case "describe":
				if arr, ok := val.([]any); ok {
					for _, e := range arr {
						parts := strs(e)
						for len(parts) < 3 {
							parts = append(parts, "")
						}
						CFG.Describe = append(CFG.Describe, [3]string{parts[0], parts[1], parts[2]})
					}
				}
			case "ignore":
				CFG.Ignore = strs(val)
			case "forms":
				if m, ok := val.(*OMap); ok {
					for _, kk := range m.Keys {
						CFG.Forms[kk] = m.Str(kk)
					}
				}
			case "limits":
				if m, ok := val.(*OMap); ok {
					for _, kk := range m.Keys {
						if n, ok := m.Vals[kk].(int64); ok {
							CFG.Limits[kk] = int(n)
						}
					}
				}
			case "tests":
				CFG.Tests = strs(val)
			case "recipes":
				if m, ok := val.(*OMap); ok {
					CFG.Recipes = m
				}
			case "strict":
				CFG.Strict, _ = val.(bool)
			case "guard":
				if m, ok := val.(*OMap); ok {
					for _, kk := range m.Keys {
						CFG.Guard[kk] = m.Vals[kk]
					}
				}
			}
		}
	}
	CMD = CFG.Command
	UNTAGGED, LARGEST = CFG.Limits["untagged"], CFG.Limits["block"]
	return argv
}

func strs(v any) []string {
	var out []string
	if arr, ok := v.([]any); ok {
		for _, e := range arr {
			if s, ok := e.(string); ok {
				out = append(out, s)
			} else {
				out = append(out, fmt.Sprint(e))
			}
		}
	}
	return out
}

func findRoot() string {
	if r := os.Getenv("MAP_ROOT"); r != "" {
		a, _ := filepath.Abs(r)
		return a
	}
	cwd, _ := os.Getwd()
	exe, _ := os.Executable()
	exe, _ = filepath.EvalSymlinks(exe)
	here := filepath.Dir(exe)
	for _, mark := range []string{"map.json", ".git"} {
		for _, start := range []string{cwd, here} {
			base := start
			for {
				if _, err := os.Lstat(filepath.Join(base, mark)); err == nil {
					return base
				}
				up := filepath.Dir(base)
				if up == base {
					break
				}
				base = up
			}
		}
	}
	return cwd
}

func CacheFile(prefix string) string {
	h := sha1.Sum([]byte(ROOT))
	return filepath.Join(os.TempDir(), "code-map", prefix+"-"+hex.EncodeToString(h[:])[:12]+".json")
}

// @end map.core.rules
