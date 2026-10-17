// @map map.guard.scope: what the map reads (the code and the docs of the repository), how a command's paths resolve, and the agents' hook formats
// Package guard is the Go version of python/map-guard.py: the same refusals, the same asks, the same five agents.
package guard

import (
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

var ROOT string
var CFG map[string]any
var ASK string
var skipped []string
var TEXT = map[string]bool{}
var NAMED = set("Makefile GNUmakefile Dockerfile Containerfile Rakefile Gemfile Justfile Vagrantfile CMakeLists.txt Jenkinsfile")
var SKIP = set("node_modules dist build out target vendor venv .venv __pycache__ .git .hg .svn .tox .mypy_cache .pytest_cache .cache coverage .idea .vscode bower_components .next .nuxt .terraform Pods DerivedData map")
var SEARCH = set("grep egrep fgrep rg ag ack")
var READ = set("cat sed head tail awk nl less more bat cut strings xxd od perl ruby")
var LIST = set("ls find tree fd")
var FILTERS = set("head tail cut grep egrep sort uniq wc sed awk tr column")

const REASON = "This repository's code and docs are read and located through its map, every question of a round in one call " +
	"(AGENTS.md, \"Finding code\"); it answers what this would, by block, with the code. None of this command ran: send its other steps again. Run instead:\n  "

func set(words string) map[string]bool {
	m := map[string]bool{}
	for _, w := range strings.Fields(words) {
		m[w] = true
	}
	return m
}

func init() {
	for _, e := range strings.Fields(".js .mjs .cjs .jsx .ts .tsx .mts .cts .java .kt .kts .scala .groovy .go .rs .swift .c .h .cc .cpp .cxx .hpp .hh .cs " +
		".m .mm .php .dart .css .scss .less .proto .zig .d .v .py .pyi .rb .rake .sh .bash .zsh .fish .pl .pm .r .R .yml .yaml .toml .ps1 .ex .exs .nim .jl .cmake .tf " +
		".nix .cr .coffee .mk .html .htm .xml .vue .svelte .astro .xhtml .sql .lua .hs .elm .ada .vhd .clj .cljs .cljc .edn .el .lisp .scm .rkt .erl .hrl .tex .md " +
		".markdown .rst .txt .adoc .json .ini .cfg .csv .editorconfig") {
		TEXT[e] = true
	}
}

// Setup finds the root and reads map.json; it is called once by the commands.
func Setup() {
	ROOT = findRoot()
	CFG = map[string]any{}
	if b, err := os.ReadFile(filepath.Join(ROOT, "map.json")); err == nil {
		json.Unmarshal(b, &CFG)
	}
	cmd := "python3 tools/map.py"
	if c, ok := CFG["command"].(string); ok && c != "" {
		cmd = c
	}
	ASK = cmd + " ask "
	if g, ok := CFG["guard"].(map[string]any); ok {
		skipped = append(skipped, strs(g["skip"])...)
	}
	skipped = append(skipped, strs(CFG["ignore"])...)
	if f, ok := CFG["forms"].(map[string]any); ok {
		for k := range f {
			TEXT[k] = true
		}
	}
}

func strs(v any) []string {
	var out []string
	if arr, ok := v.([]any); ok {
		for _, e := range arr {
			out = append(out, fmt.Sprint(e))
		}
	}
	return out
}

func findRoot() string {
	if r := os.Getenv("MAP_ROOT"); r != "" {
		return realpath(r)
	}
	cwd, _ := os.Getwd()
	exe, _ := os.Executable()
	exe, _ = filepath.EvalSymlinks(exe)
	here := filepath.Dir(exe)
	for _, start := range []string{cwd, here} {
		for _, mark := range []string{"map.json", ".git"} {
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

func expanduser(p string) string {
	if strings.HasPrefix(p, "~") {
		home, _ := os.UserHomeDir()
		return filepath.Join(home, p[1:])
	}
	return p
}

// realpath resolves symlinks of the longest existing prefix, like os.path.realpath.
func realpath(p string) string {
	full, _ := filepath.Abs(p)
	if r, err := filepath.EvalSymlinks(full); err == nil {
		return r
	}
	base, rest := full, []string{}
	for {
		if _, err := os.Lstat(base); err == nil {
			break
		}
		rest = append([]string{filepath.Base(base)}, rest...)
		up := filepath.Dir(base)
		if up == base {
			return full
		}
		base = up
	}
	r, err := filepath.EvalSymlinks(base)
	if err != nil {
		return full
	}
	return filepath.Join(append([]string{r}, rest...)...)
}

// Inside: the path relative to the repository, or "" (and false) when it is outside it.
func Inside(p, base string) (string, bool) {
	var full string
	if filepath.IsAbs(expanduser(p)) {
		full = realpath(expanduser(p))
	} else {
		full = realpath(filepath.Join(base, expanduser(p)))
	}
	rel, err := filepath.Rel(ROOT, full)
	if err != nil || strings.HasPrefix(rel, "..") {
		return "", false
	}
	return rel, true
}

var ignoredPats []string
var ignoredRead bool

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

func ignored(rel string) bool {
	if !ignoredRead {
		if b, err := os.ReadFile(filepath.Join(ROOT, ".gitignore")); err == nil {
			for _, l := range strings.Split(string(b), "\n") {
				l = strings.TrimSpace(l)
				if l != "" && !strings.HasPrefix(l, "#") {
					ignoredPats = append(ignoredPats, l)
				}
			}
		}
		ignoredPats = append(ignoredPats, skipped...)
		ignoredRead = true
	}
	parts := strings.Split(rel, string(os.PathSeparator))
	for _, x := range parts[:len(parts)-1] {
		if SKIP[x] {
			return true
		}
	}
	if SKIP[parts[0]] {
		return true
	}
	for _, p := range ignoredPats {
		folder, q := strings.HasSuffix(p, "/"), strings.Trim(p, "/")
		if strings.Contains(q, "/") {
			if rel == q || strings.HasPrefix(rel, q+string(os.PathSeparator)) || Fnmatch(rel, q) {
				return true
			}
		} else {
			cand := parts
			if folder {
				if st, err := os.Stat(filepath.Join(ROOT, rel)); err != nil || !st.IsDir() {
					cand = parts[:len(parts)-1]
				}
			}
			for _, n := range cand {
				if Fnmatch(n, q) {
					return true
				}
			}
		}
	}
	return false
}

func isText(rel string) bool {
	name := filepath.Base(rel)
	if NAMED[name] || TEXT[strings.ToLower(filepath.Ext(name))] {
		return true
	}
	if !strings.Contains(name, ".") {
		f, err := os.Open(filepath.Join(ROOT, rel))
		if err != nil {
			return false
		}
		defer f.Close()
		b := make([]byte, 2)
		n, _ := f.Read(b)
		return n == 2 && string(b) == "#!"
	}
	return false
}

var wildRx = regexp.MustCompile(`[*?[]`)

func expand(rel string) []string {
	folder, name := "", rel
	if i := strings.LastIndex(rel, "/"); i >= 0 {
		folder, name = rel[:i], rel[i+1:]
	}
	if wildRx.MatchString(folder) {
		return nil
	}
	dir := ROOT
	if folder != "" {
		dir = filepath.Join(ROOT, folder)
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}
	var names []string
	for _, e := range entries {
		names = append(names, e.Name())
	}
	sort.Strings(names)
	var out []string
	for _, n := range names {
		if Fnmatch(n, name) {
			if folder != "" {
				out = append(out, folder+"/"+n)
			} else {
				out = append(out, n)
			}
		}
	}
	return out
}

func Mapped(rel string, ok bool, folderOk bool) bool {
	if !ok {
		return false
	}
	if wildRx.MatchString(rel) {
		xs := expand(rel)
		if len(xs) > 50 {
			xs = xs[:50]
		}
		for _, x := range xs {
			if Mapped(x, true, folderOk) {
				return true
			}
		}
		return false
	}
	if rel == "." {
		return folderOk
	}
	if rel == "map.yaml" || strings.Split(rel, string(os.PathSeparator))[0] == "map" {
		return false
	}
	st, err := os.Stat(filepath.Join(ROOT, rel))
	if err != nil {
		return false
	}
	if st.IsDir() {
		return folderOk && !ignored(rel)
	}
	return isText(rel) && !ignored(rel)
}

var safeRx = regexp.MustCompile(`^[A-Za-z0-9@%+=:,./_-]+$`)

func quoteWord(w string) string {
	if w == "" {
		return "''"
	}
	if safeRx.MatchString(w) {
		return w
	}
	return "'" + strings.ReplaceAll(w, "'", `'"'"'`) + "'"
}

func Quote(words []string) string {
	var out []string
	for _, w := range words {
		out = append(out, quoteWord(w))
	}
	return strings.Join(out, " ")
}

// @end map.guard.scope

// @map map.guard.commands: a shell line into its commands (heredocs left out, cd followed), and each command's map question
const punct = "();<>|&"

func ShellWords(line string) []string {
	var out []string
	var word strings.Builder
	had := false
	var quote rune
	r := []rune(line)
	n := len(r)
	for i := 0; i < n; i++ {
		c := r[i]
		switch {
		case quote != 0:
			if c == quote {
				quote = 0
			} else if quote == '"' && c == '\\' && i+1 < n && strings.ContainsRune("\"\\$`\n", r[i+1]) {
				word.WriteRune(r[i+1])
				i++
			} else {
				word.WriteRune(c)
			}
		case c == '\'' || c == '"':
			quote = c
			had = true
		case c == '\\' && i+1 < n:
			word.WriteRune(r[i+1])
			had = true
			i++
		case unicode.IsSpace(c):
			if had {
				out = append(out, word.String())
				word.Reset()
				had = false
			}
		case strings.ContainsRune(punct, c):
			if had {
				out = append(out, word.String())
				word.Reset()
				had = false
			}
			j := i
			for j < n && strings.ContainsRune(punct, r[j]) {
				j++
			}
			out = append(out, string(r[i:j]))
			i = j - 1
		case c == '#' && !had:
			if had {
				out = append(out, word.String())
			}
			return out
		default:
			word.WriteRune(c)
			had = true
		}
	}
	if had {
		out = append(out, word.String())
	}
	return out
}

var headRx = regexp.MustCompile(`^<<-?\s*(['"]?)(\w+)`)

type heredoc struct {
	start, end int
	head, tag  string
	body       string
}

func heredocs(line string) []heredoc {
	var out []heredoc
	pos := 0
	for {
		i := strings.Index(line[pos:], "<<")
		if i < 0 {
			break
		}
		i += pos
		m := headRx.FindStringSubmatch(line[i:])
		if m == nil || (m[1] != "" && !strings.HasPrefix(line[i+len(m[0]):], m[1])) {
			pos = i + 2
			continue
		}
		headEnd := strings.Index(line[i:], "\n")
		if headEnd < 0 {
			pos = i + 2
			continue
		}
		headEnd += i
		tag := m[2]
		k := headEnd + 1
		bodyStart := k
		end := -1
		for k <= len(line) {
			nl := strings.Index(line[k:], "\n")
			var seg string
			if nl < 0 {
				seg = line[k:]
			} else {
				seg = line[k : k+nl]
			}
			if strings.TrimSpace(seg) == tag {
				if nl < 0 {
					end = len(line)
				} else {
					end = k + nl
				}
				body := ""
				if k > bodyStart {
					body = line[bodyStart : k-1]
				}
				head := line[strings.LastIndex(line[:i], "\n")+1 : i]
				out = append(out, heredoc{i, end, head, tag, body})
				break
			}
			if nl < 0 {
				break
			}
			k += nl + 1
		}
		if end >= 0 {
			pos = end
		} else {
			pos = i + 2
		}
	}
	return out
}

func markerLen(s string) int {
	m := headRx.FindStringSubmatch(s)
	if m == nil {
		return 0
	}
	n := len(m[0])
	if m[1] != "" {
		n++
	}
	return n
}

func withoutHeredocs(line string) string {
	hs := heredocs(line)
	for i := len(hs) - 1; i >= 0; i-- {
		h := hs[i]
		headEnd := strings.Index(line[h.start:], "\n") + h.start
		line = line[:h.start] + line[h.start+markerLen(line[h.start:]):headEnd] + line[h.end:]
	}
	return line
}

var quietRx = regexp.MustCompile(`\d?>&\d|\d?>\s*/dev/null`)
var opRx = regexp.MustCompile(`\|\||&&|\|&|;;|>>|&>|[|&;()<>]`)
var opOnlyRx = regexp.MustCompile(`^[|&;()<>]+$`)

type command struct {
	words []string
	piped bool
	base  string
}

func Commands(line, cwd string) []command {
	line = withoutHeredocs(line)
	line = strings.ReplaceAll(line, "\\\n", " ")
	line = strings.ReplaceAll(line, "\n", " ; ")
	line = quietRx.ReplaceAllString(line, " ")
	var split []string
	for _, t := range ShellWords(line) {
		if opOnlyRx.MatchString(t) {
			split = append(split, opRx.FindAllString(t, -1)...)
		} else {
			split = append(split, t)
		}
	}
	var out []command
	var words []string
	piped, base := false, cwd
	for _, t := range append(split, ";") {
		switch t {
		case "|", "||", "&&", ";", "&", "(", ")", "|&", ";;", "\n":
			if len(words) > 0 {
				if words[0] == "cd" && len(words) > 1 {
					if filepath.IsAbs(expanduser(words[1])) {
						base = expanduser(words[1])
					} else {
						base = filepath.Join(base, expanduser(words[1]))
					}
				} else {
					out = append(out, command{words, piped, base})
				}
			}
			piped = t == "|" || t == "|&"
			words = nil
		default:
			words = append(words, t)
		}
	}
	return out
}

func has(m map[string]bool, keys ...string) bool {
	for _, k := range keys {
		if m[k] {
			return true
		}
	}
	return false
}

var nameStrip = regexp.MustCompile(`^\^?\s*(?:(?:export|async|pub|public|private|static)\s+)*(?:function\*?|def|fn|func|class|const|let|var|val)\s+|(?:\\?\(|\\s\*=|\s*=|\\b)$`)
var nameOK = regexp.MustCompile(`^[#.]?[A-Za-z_$][\w$-]*$`)
var tagRx = regexp.MustCompile(`@map\s+([\w.-]+)`)
var headingPat = regexp.MustCompile(`^\^#+.*$`)
var basicRx = regexp.MustCompile(`\\([|(){}+?])|([|(){}+?])`)

func GrepQuestion(words []string, base string) []string {
	var pats, paths, includes []string
	flags := map[string]bool{}
	for i := 1; i < len(words); i++ {
		a := words[i]
		switch {
		case a == "-e" || a == "--regexp":
			if i+1 < len(words) {
				pats = append(pats, words[i+1])
			} else {
				pats = append(pats, "")
			}
			i++
		case strings.HasPrefix(a, "--include="):
			includes = append(includes, a[10:])
		case a == "-A" || a == "-B" || a == "-C" || a == "-m" || a == "--max-count" || a == "-g" || a == "--glob" || a == "-t" || a == "--type" || a == "--include" || a == "--exclude":
			if a == "-g" || a == "--glob" || a == "--include" {
				if i+1 < len(words) {
					includes = append(includes, words[i+1])
				} else {
					includes = append(includes, "")
				}
			}
			i++
		case strings.HasPrefix(a, "--"):
			flags[a] = true
		case strings.HasPrefix(a, "-") && len(a) > 1:
			for _, ch := range a[1:] {
				flags[string(ch)] = true
			}
		default:
			paths = append(paths, a)
		}
	}
	if len(pats) == 0 && len(paths) > 0 {
		pats, paths = []string{paths[0]}, paths[1:]
	}
	if has(flags, "c", "q", "l", "L", "--count", "--quiet", "--silent", "--files-with-matches", "--files-without-match") {
		return nil
	}
	recursive := words[0] == "rg" || words[0] == "ag" || words[0] == "ack" || has(flags, "r", "R", "--recursive")
	if len(paths) == 0 && !recursive {
		return nil
	}
	type rel struct {
		p  string
		ok bool
	}
	var rels []rel
	if len(paths) > 0 {
		for _, p := range paths {
			r, ok := Inside(p, base)
			rels = append(rels, rel{r, ok})
		}
	} else {
		r, ok := Inside(".", base)
		rels = append(rels, rel{r, ok})
	}
	anyMapped := false
	for _, r := range rels {
		if Mapped(r.p, r.ok, true) {
			anyMapped = true
		}
	}
	if !anyMapped {
		return nil
	}
	var places []string
	for _, r := range rels {
		if r.ok && r.p != "." {
			places = append(places, r.p)
		}
	}
	if len(includes) > 0 {
		bases := places
		if len(bases) == 0 {
			bases = []string{""}
		}
		var np []string
		for _, p := range bases {
			for _, g := range includes {
				np = append(np, strings.TrimLeft(filepath.Join(p, "*"+strings.TrimLeft(g, "*")), "/"))
			}
		}
		places = np
	}
	pattern := strings.Join(pats, "|")
	if strings.Contains(pattern, "@map") {
		if m := tagRx.FindStringSubmatch(pattern); m != nil {
			return []string{m[1]}
		}
		if len(places) > 0 {
			return places
		}
		return []string{"."}
	}
	allMd := true
	for _, p := range places {
		if !strings.HasSuffix(p, ".md") {
			allMd = false
		}
	}
	if headingPat.MatchString(pattern) && allMd {
		return places
	}
	plain := words[0] == "grep" && !flags["E"] && !flags["P"]
	var alternatives []string
	for _, p := range pats {
		if plain {
			alternatives = append(alternatives, regexp.MustCompile(`\\\||\|`).Split(p, -1)...)
		} else {
			alternatives = append(alternatives, strings.Split(p, "|")...)
		}
	}
	var names []string
	allNames := len(alternatives) > 0
	for _, a := range alternatives {
		n := nameStrip.ReplaceAllString(a, "")
		names = append(names, n)
		if !nameOK.MatchString(n) {
			allNames = false
		}
	}
	if allNames && !flags["v"] && !flags["F"] {
		out := unique(names)
		if len(places) > 0 {
			out = append(out, "--in", strings.Join(places, ","))
		}
		return out
	}
	var rx string
	switch {
	case flags["F"]:
		rx = regexp.QuoteMeta(pattern)
	case flags["E"] || flags["P"] || words[0] == "egrep" || words[0] == "rg" || words[0] == "ag" || words[0] == "ack":
		rx = pattern
	default:
		rx = basicRx.ReplaceAllStringFunc(pattern, func(m string) string {
			if strings.HasPrefix(m, `\`) {
				return m[1:]
			}
			return `\` + m
		})
	}
	if flags["w"] {
		rx = `\b(?:` + rx + `)\b`
	}
	if flags["i"] {
		rx = "(?i)" + rx
	}
	out := []string{rx}
	if len(places) > 0 {
		out = append(out, "--in", strings.Join(places, ","))
	}
	return out
}

func unique(xs []string) []string {
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

var inplaceRx = regexp.MustCompile(`^-\w*i\S*$`)
var countRx = regexp.MustCompile(`^-n(\+?\d+)?$|^-(\d+)$`)
var sedRange = regexp.MustCompile(`^(\d+)(?:,(\d+|\$))?p$`)
var sedNamed = regexp.MustCompile(`/\^?\s*(?:(?:export|async|pub)\s+)*(?:function|def|fn|func|class|const)\s+([A-Za-z_$][\w$]*)`)
var digitsRx = regexp.MustCompile(`^\d+$`)

func countLines(rel string) int {
	b, err := os.ReadFile(filepath.Join(ROOT, rel))
	if err != nil || len(b) == 0 {
		return 0
	}
	n := strings.Count(string(b), "\n")
	if !strings.HasSuffix(string(b), "\n") {
		n++
	}
	return n
}

func ReadQuestion(words []string, base string) []string {
	tool, args := words[0], words[1:]
	if tool == "sed" {
		for _, a := range args {
			if strings.HasPrefix(a, "-i") || a == "--in-place" {
				return nil
			}
		}
	}
	if tool == "perl" || tool == "ruby" {
		for _, a := range args {
			if inplaceRx.MatchString(a) {
				return nil
			}
		}
	}
	script := ""
	hasScript := false
	var files []string
	switch tool {
	case "sed":
		var rest []string
		for _, a := range args {
			if !strings.HasPrefix(a, "-") {
				rest = append(rest, a)
			}
		}
		if len(rest) > 0 {
			script, hasScript = rest[0], true
			files = rest[1:]
		}
	case "awk":
		var rest []string
		for _, a := range args {
			if !strings.HasPrefix(a, "-") {
				rest = append(rest, a)
			}
		}
		if len(rest) > 1 {
			files = rest[1:]
		}
	default:
		for k, a := range args {
			if strings.HasPrefix(a, "-") {
				continue
			}
			if k > 0 && (args[k-1] == "-n" || args[k-1] == "-c" || args[k-1] == "-f" || args[k-1] == "-d") {
				continue
			}
			files = append(files, a)
		}
	}
	n, fromStart, noN := 10, false, false
	for k, a := range args {
		if strings.HasPrefix(a, "-c") {
			noN = true
			continue
		}
		if m := countRx.FindStringSubmatch(a); m != nil {
			v := m[1]
			if v == "" {
				v = m[2]
			}
			if v == "" {
				if k+1 < len(args) {
					v = args[k+1]
				} else {
					v = "10"
				}
			}
			d := strings.TrimPrefix(v, "+")
			if digitsRx.MatchString(d) {
				fmt.Sscanf(d, "%d", &n)
			} else {
				n = 10
			}
			fromStart = strings.HasPrefix(v, "+")
		}
	}
	_ = hasScript
	type rel struct {
		p  string
		ok bool
	}
	var rels []rel
	for _, f := range files {
		r, ok := Inside(f, base)
		if ok && wildRx.MatchString(f) {
			for _, x := range expand(r) {
				rels = append(rels, rel{x, true})
			}
		} else {
			rels = append(rels, rel{r, ok})
		}
	}
	anyMapped := false
	for _, r := range rels {
		if Mapped(r.p, r.ok, false) {
			anyMapped = true
		}
	}
	if len(files) == 0 || !anyMapped {
		return nil
	}
	var out []string
	for _, r := range rels {
		if !Mapped(r.p, r.ok, false) {
			continue
		}
		count := countLines(r.p)
		m := sedRange.FindStringSubmatch(script)
		named := sedNamed.FindStringSubmatch(script)
		switch {
		case m != nil:
			end := m[1]
			if m[2] != "" && m[2] != "$" {
				end = m[2]
			} else if m[2] != "" {
				end = fmt.Sprint(count)
			}
			out = append(out, fmt.Sprintf("%s:%s-%s", r.p, m[1], end))
		case named != nil:
			out = append(out, named[1], "--in", r.p)
		case tool == "head" && !noN && n > 0:
			lim := n
			if count < lim {
				lim = count
			}
			out = append(out, fmt.Sprintf("%s:1-%d", r.p, lim))
		case tool == "tail" && !noN && n > 0:
			start := count - n + 1
			if fromStart {
				start = n
			}
			if start < 1 {
				start = 1
			}
			out = append(out, fmt.Sprintf("%s:%d-%d", r.p, start, count))
		default:
			out = append(out, r.p)
		}
	}
	return out
}

func ListQuestion(words []string, base string) []string {
	var args []string
	for _, a := range words[1:] {
		if !strings.HasPrefix(a, "-") {
			args = append(args, a)
		}
	}
	if words[0] == "find" {
		for _, a := range words {
			switch a {
			case "-newer", "-mtime", "-mmin", "-size", "-exec", "-delete", "-empty", "-perm":
				return nil
			}
		}
		pattern := ""
		for k, a := range words {
			if (a == "-name" || a == "-iname") && k+1 < len(words) && pattern == "" {
				pattern = words[k+1]
			}
		}
		root := "."
		for _, a := range words[1:] {
			if !strings.HasPrefix(a, "-") && a != pattern {
				root = a
				break
			}
		}
		rel, ok := Inside(root, base)
		if !Mapped(rel, ok, true) || (rel == "." && pattern == "") {
			return nil
		}
		if pattern != "" {
			dir := rel
			if rel == "." {
				dir = ""
			}
			return []string{filepath.Join(dir, "*"+strings.TrimLeft(pattern, "*"))}
		}
		return []string{rel}
	}
	var out []string
	for _, a := range args {
		rel, ok := Inside(a, base)
		if Mapped(rel, ok, true) && rel != "." {
			out = append(out, rel)
		}
	}
	return out
}

// @end map.guard.commands

// @map map.guard.commands.scripts: a script that opens a file of the code only to print it: python -c, node -e, a heredoc fed to them, a scratch script run by name
var readArg = regexp.MustCompile("\\b(?:open|readFileSync|readFile|read_text|read_bytes|Path)\\s*\\(\\s*(?:['\"`]([^'\"`\\n]+)['\"`]|([A-Za-z_$][\\w$]*)\\s*[,)])")
var namedVar = regexp.MustCompile("\\b([A-Za-z_$][\\w$]*)\\s*=\\s*['\"`]([^'\"`\\n]+)['\"`]")
var writesOther = regexp.MustCompile(`write_text\(|write_bytes\(|writeFileSync\(|writeFile\(|appendFileSync\(|open\([^)\n]*,\s*['"][wax+]`)
var shows = regexp.MustCompile(`\bprint\(|console\.(?:log|dir|table)\(|(?:process|sys)\.stdout\.write\(`)
var inlineRx = regexp.MustCompile(`\b(?:python3?\s+-c|node\s+(?:-e|--eval|-p|--print))\s+(['"])`)
var fileScript = regexp.MustCompile(`\b(?:python3?|node)\s+(?:--?[\w=-]+\s+)*[^\s|;&-][^\s|;&]*\.(?:py|mjs|cjs|js)\b`)
var pathLiteral = regexp.MustCompile("['\"`]([^'\"`\\s]+\\.(?:js|mjs|cjs|ts|css|html|py|rb|go|rs|java|sh|md|json|yaml|yml|toml|txt))['\"`]")
var loopRx = regexp.MustCompile(`\bfor\s*\(?\s*(?:const\s+|let\s+|var\s+)?(\w+)\s+(?:in|of)\s+[\[(]([^\])]*)[\])]`)
var loadedRx = regexp.MustCompile(`\b(\w+)\s*=\s*(?:json\.load|JSON\.parse)\(`)
var envRx = regexp.MustCompile(`(?:^|[;&\s])([A-Za-z_]\w*)=([^\s;&|]+)`)
var varRx = regexp.MustCompile(`\$\{?(\w+)\}?`)
var pyNode = regexp.MustCompile(`\b(?:python3?|node)\b`)
var catTo = regexp.MustCompile(`\bcat\s*>>?\s*(\S+)`)

var dataExt = []string{".json", ".yaml", ".yml", ".toml"}

func writes(text string) bool {
	if writesOther.MatchString(text) {
		return true
	}
	pos := 0
	for {
		i := strings.Index(text[pos:], ".write(")
		if i < 0 {
			return false
		}
		i += pos
		before := text[:i]
		if !(strings.HasSuffix(before, "stdout") || strings.HasSuffix(before, "stderr")) {
			return true
		}
		pos = i + 7
	}
}

func inlineScripts(line string) []string {
	var out []string
	for _, loc := range inlineRx.FindAllStringSubmatchIndex(line, -1) {
		q := line[loc[2]:loc[3]]
		i := loc[1]
		for {
			j := strings.Index(line[i:], q)
			if j < 0 {
				break
			}
			j += i
			if j > 0 && line[j-1] != '\\' {
				out = append(out, line[loc[1]:j])
				break
			}
			i = j + 1
		}
	}
	return out
}

func scripts(line, cwd string) []string {
	env := map[string]string{}
	for _, m := range envRx.FindAllStringSubmatch(line, -1) {
		env[m[1]] = m[2]
	}
	expand_ := func(p string) string {
		p = strings.Trim(p, `'"`)
		return varRx.ReplaceAllStringFunc(p, func(m string) string {
			name := varRx.FindStringSubmatch(m)[1]
			if v, ok := env[name]; ok {
				return v
			}
			return m
		})
	}
	out := inlineScripts(line)
	for _, h := range heredocs(line) {
		if pyNode.MatchString(h.head) && !fileScript.MatchString(h.head) {
			out = append(out, h.body)
		} else if to := catTo.FindStringSubmatch(h.head); to != nil {
			target := expand_(to[1])
			if _, ok := Inside(target, cwd); strings.Contains(target, "$") || !ok {
				out = append(out, h.body)
			}
		}
	}
	for _, c := range Commands(line, cwd) {
		b := filepath.Base(c.words[0])
		if (b == "node" || b == "python" || b == "python3") && len(c.words) > 1 && !strings.HasPrefix(c.words[1], "-") {
			name := expand_(c.words[1])
			f := expanduser(name)
			if !filepath.IsAbs(f) {
				f = filepath.Join(c.base, f)
			}
			if _, ok := Inside(name, c.base); !ok {
				if st, err := os.Stat(f); err == nil && st.Mode().IsRegular() && st.Size() < 300000 {
					if b, err := os.ReadFile(f); err == nil {
						out = append(out, string(b))
					}
				}
			}
		}
	}
	return out
}

func ScriptQuestion(line, cwd string) []string {
	var out []string
	for _, text := range scripts(line, cwd) {
		if !shows.MatchString(text) || writes(text) {
			continue
		}
		names := map[string]string{}
		for _, m := range namedVar.FindAllStringSubmatch(text, -1) {
			names[m[1]] = m[2]
		}
		var paths []string
		for _, m := range readArg.FindAllStringSubmatch(text, -1) {
			literal, v := m[1], m[2]
			if literal != "" {
				paths = append(paths, literal)
			} else if nv, ok := names[v]; ok {
				paths = append(paths, nv)
			} else {
				for _, l := range loopRx.FindAllStringSubmatch(text, -1) {
					if l[1] == v {
						for _, p := range pathLiteral.FindAllStringSubmatch(l[2], -1) {
							paths = append(paths, p[1])
						}
					}
				}
			}
		}
		dumped := false
		for _, m := range loadedRx.FindAllStringSubmatch(text, -1) {
			v := regexp.QuoteMeta(m[1])
			if regexp.MustCompile(`(?:json\.dumps|JSON\.stringify)\(\s*` + v + `\b|(?:print|console\.log)\(\s*` + v + `\s*\)`).MatchString(text) {
				dumped = true
			}
		}
		for _, p := range paths {
			rel, ok := Inside(p, cwd)
			isData := false
			for _, d := range dataExt {
				if strings.HasSuffix(rel, d) {
					isData = true
				}
			}
			if Mapped(rel, ok, false) && (!isData || dumped) {
				out = append(out, rel)
			}
		}
	}
	return unique(out)
}

// @end map.guard.commands.scripts

// @map map.guard.decide: each agent's input read into one shape, the ask that replaces the call, and the answer in the agent's format
func question(words []string, base string) []string {
	tool := filepath.Base(words[0])
	switch {
	case tool == "git" && len(words) > 1 && words[1] == "grep":
		return GrepQuestion(append([]string{"grep", "-r"}, words[2:]...), base)
	case tool == "xargs" && len(words) > 1 && SEARCH[filepath.Base(words[1])]:
		return GrepQuestion(append(append([]string{}, words[1:]...), "-r", "."), base)
	case SEARCH[tool]:
		return GrepQuestion(append([]string{tool}, words[1:]...), base)
	case READ[tool]:
		return ReadQuestion(append([]string{tool}, words[1:]...), base)
	case LIST[tool]:
		return ListQuestion(append([]string{tool}, words[1:]...), base)
	}
	return nil
}

func ShellQuestion(line, cwd string) string {
	first := strings.SplitN(line, "\n", 2)[0]
	if strings.Contains(line, "map.py") || strings.Contains(line, "map.mjs") || (strings.HasPrefix(ASK, "map ") && strings.Contains(" "+first+" ", " map ")) {
		return ""
	}
	asked := ScriptQuestion(line, cwd)
	var filtered []string
	parts := Commands(line, cwd)
	for k, c := range parts {
		if c.piped || len(c.words) == 0 {
			continue
		}
		redirect := false
		for _, w := range c.words {
			if w == ">" || w == ">>" || w == "&>" {
				redirect = true
			}
		}
		if redirect {
			continue
		}
		var q []string
		var after *command
		if k+1 < len(parts) {
			after = &parts[k+1]
		}
		if c.words[0] == "find" && after != nil && after.piped && len(after.words) > 1 && after.words[0] == "xargs" && SEARCH[filepath.Base(after.words[1])] {
			pattern := "*"
			for j, a := range c.words {
				if (a == "-name" || a == "-iname") && j+1 < len(c.words) && pattern == "*" {
					pattern = c.words[j+1]
				}
			}
			root := "."
			for _, a := range c.words[1:] {
				if !strings.HasPrefix(a, "-") {
					root = a
					break
				}
			}
			q = GrepQuestion(append(append([]string{}, after.words[1:]...), "-r", root, "--include="+pattern), c.base)
		} else {
			q = question(c.words, c.base)
		}
		if len(q) == 0 {
			continue
		}
		var pipe []string
		for _, w := range parts[k+1:] {
			if !w.piped || !FILTERS[filepath.Base(w.words[0])] {
				break
			}
			pipe = append(pipe, Quote(w.words))
		}
		if len(pipe) > 0 {
			filtered = append(filtered, ASK+Quote(q)+" | "+strings.Join(pipe, " | "))
		} else {
			asked = append(asked, q...)
		}
	}
	var all []string
	if len(asked) > 0 {
		all = append(all, ASK+Quote(asked))
	}
	all = append(all, filtered...)
	return strings.Join(all, "; ")
}

func readQuestionTool(filePath, cwd string, offset, limit any) string {
	rel, ok := Inside(filePath, cwd)
	if !Mapped(rel, ok, false) || truthy(limit) || truthy(offset) {
		return ""
	}
	return ASK + Quote([]string{rel})
}

func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case float64:
		return x != 0
	case string:
		return x != ""
	}
	return true
}

func str(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

func normalise(agent string, data map[string]any) (string, map[string]any, string) {
	cwd := str(data["cwd"])
	if cwd == "" {
		if roots, ok := data["workspace_roots"].([]any); ok && len(roots) > 0 {
			cwd = str(roots[0])
		}
	}
	if cwd == "" {
		cwd = ROOT
	}
	_, hasTool := data["tool_name"]
	switch agent {
	case "cursor":
		if _, ok := data["command"]; ok && !hasTool {
			return "shell", map[string]any{"command": data["command"]}, cwd
		}
		if _, ok := data["file_path"]; ok && !hasTool {
			return "read", map[string]any{"file_path": data["file_path"]}, cwd
		}
		name := strings.ToLower(str(data["tool_name"]))
		given, _ := data["tool_input"].(map[string]any)
		if given == nil {
			given = map[string]any{}
		}
		if wd := str(given["working_directory"]); wd != "" {
			cwd = wd
		}
		kind := ""
		switch name {
		case "shell", "bash", "terminal":
			kind = "shell"
		case "read", "read_file":
			kind = "read"
		}
		return kind, given, cwd
	case "copilot":
		name := strings.ToLower(str(data["toolName"]))
		if name == "" {
			name = strings.ToLower(str(data["tool_name"]))
		}
		var given map[string]any
		raw, hasArgs := data["toolArgs"]
		if !hasArgs {
			raw = data["tool_input"]
		}
		switch x := raw.(type) {
		case string:
			if json.Unmarshal([]byte(x), &given) != nil || given == nil {
				given = map[string]any{"command": x}
			}
		case map[string]any:
			given = x
		}
		if given == nil {
			given = map[string]any{}
		}
		kind := map[string]string{"bash": "shell", "powershell": "shell", "view": "read", "grep": "grep", "glob": "glob"}[name]
		return kind, given, cwd
	case "gemini":
		name := strings.ToLower(str(data["tool_name"]))
		given, _ := data["tool_input"].(map[string]any)
		if given == nil {
			given = map[string]any{}
		}
		kind := ""
		switch {
		case strings.Contains(name, "shell"):
			kind = "shell"
		case name == "read_file" || name == "read_many_files":
			kind = "read"
		case strings.Contains(name, "grep") || strings.Contains(name, "search_file"):
			kind = "grep"
		case name == "glob":
			kind = "glob"
		case name == "list_directory":
			kind = "list"
		}
		return kind, given, cwd
	}
	given, _ := data["tool_input"].(map[string]any)
	if given == nil {
		given = map[string]any{}
	}
	kind := map[string]string{"Bash": "shell", "Read": "read", "Grep": "grep", "Glob": "glob"}[str(data["tool_name"])]
	return kind, given, cwd
}

// either is a when it is set (Python's a or b), else b.
func either(a, b any) any {
	if truthy(a) {
		return a
	}
	return b
}

// folderOf: the folder a search, a glob or a listing names (path, or Gemini's dir_path), the working folder by default.
func folderOf(given map[string]any) string {
	if p := str(given["path"]); p != "" {
		return p
	}
	if p := str(given["dir_path"]); p != "" {
		return p
	}
	return "."
}

// Replacement: the map's question for this call, or "" when the call may go ahead.
func Replacement(agent string, data map[string]any) string {
	kind, given, cwd := normalise(agent, data)
	switch kind {
	case "shell":
		cmd := str(given["command"])
		if cmd == "" {
			cmd = str(given["cmd"])
		}
		return ShellQuestion(cmd, cwd)
	case "read":
		p := str(given["file_path"])
		if p == "" {
			p = str(given["absolute_path"])
		}
		if p == "" {
			p = str(given["path"])
		}
		if p == "" {
			if paths, ok := given["paths"].([]any); ok && len(paths) > 0 {
				p = str(paths[0])
			}
		}
		// a range is offset and limit, or Gemini's start_line and end_line
		return readQuestionTool(p, cwd, either(given["offset"], given["start_line"]), either(given["limit"], given["end_line"]))
	case "grep":
		if str(given["output_mode"]) == "count" {
			return ""
		}
		words := []string{"rg"}
		if truthy(given["-i"]) || truthy(given["case_insensitive"]) {
			words = append(words, "-i")
		}
		words = append(words, "-e", str(given["pattern"]))
		words = append(words, folderOf(given))
		if g := str(given["glob"]); g != "" {
			words = append(words, "--glob", g)
		}
		if g := str(given["include"]); g != "" {
			words = append(words, "--glob", g)
		}
		q := GrepQuestion(words, cwd)
		if len(q) == 0 {
			return ""
		}
		return ASK + Quote(q)
	case "glob":
		rel, ok := Inside(folderOf(given), cwd)
		if !Mapped(rel, ok, true) {
			return ""
		}
		dir := rel
		if !ok || rel == "." {
			dir = ""
		}
		return ASK + Quote([]string{filepath.Join(dir, str(given["pattern"]))})
	case "list":
		rel, ok := Inside(folderOf(given), cwd)
		if Mapped(rel, ok, true) && rel != "." {
			return ASK + Quote([]string{rel})
		}
	}
	return ""
}

func Detect(data map[string]any) string {
	_, hasTool := data["tool_name"]
	_, hasCmd := data["command"]
	_, hasFile := data["file_path"]
	if _, ok := data["cursor_version"]; ok || (hasCmd && !hasTool) || (hasFile && !hasTool) {
		return "cursor"
	}
	if _, ok := data["toolName"]; ok {
		return "copilot"
	}
	switch str(data["tool_name"]) {
	case "bash", "powershell", "view", "grep", "glob", "create", "edit":
		return "copilot"
	}
	if str(data["hook_event_name"]) == "BeforeTool" {
		return "gemini"
	}
	return "claude"
}

func Answer(agent, asked string) map[string]any {
	reason := REASON + asked
	switch agent {
	case "cursor":
		return map[string]any{"permission": "deny", "user_message": "map-guard: read it through the map (ask). " + asked, "agent_message": reason}
	case "copilot":
		return map[string]any{"permissionDecision": "deny", "permissionDecisionReason": reason}
	case "gemini":
		return map[string]any{"decision": "deny", "reason": reason}
	}
	return map[string]any{"hookSpecificOutput": map[string]any{"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}
}

// JSON writes a value without HTML escaping, with Python's indent when asked.
func JSON(v any, indent string) string {
	var b strings.Builder
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	if indent != "" {
		enc.SetIndent("", indent)
	}
	enc.Encode(v)
	return strings.TrimRight(b.String(), "\n")
}

type setting struct {
	path string
	make func(me string) map[string]any
}

var settings = map[string]setting{
	"claude": {".claude/settings.json", func(me string) map[string]any {
		return map[string]any{"hooks": map[string]any{"PreToolUse": []any{map[string]any{"matcher": "Bash|Read|Grep|Glob", "hooks": []any{map[string]any{"type": "command", "command": `"$CLAUDE_PROJECT_DIR/` + me + `"`}}}}}}
	}},
	"codex": {".codex/hooks.json", func(me string) map[string]any {
		return map[string]any{"hooks": map[string]any{"PreToolUse": []any{map[string]any{"matcher": "Bash", "hooks": []any{map[string]any{"type": "command", "command": `"$(git rev-parse --show-toplevel)/` + me + `" --agent codex`, "statusMessage": "map-guard"}}}}}}
	}},
	"cursor": {".cursor/hooks.json", func(me string) map[string]any {
		return map[string]any{"version": 1, "hooks": map[string]any{"beforeShellExecution": []any{map[string]any{"command": me + " --agent cursor"}}, "beforeReadFile": []any{map[string]any{"command": me + " --agent cursor"}}}}
	}},
	"copilot": {".github/hooks/map-guard.json", func(me string) map[string]any {
		return map[string]any{"version": 1, "hooks": map[string]any{"preToolUse": []any{map[string]any{"type": "command", "bash": me + " --agent copilot", "cwd": ".", "timeoutSec": 10}}}}
	}},
	"gemini": {".gemini/settings.json", func(me string) map[string]any {
		return map[string]any{"hooks": map[string]any{"BeforeTool": []any{map[string]any{"matcher": "run_shell_command|read_file|read_many_files|grep_search|glob|list_directory", "hooks": []any{map[string]any{"name": "map-guard", "type": "command", "command": `"$GEMINI_PROJECT_DIR/` + me + `" --agent gemini`, "timeout": 5000}}}}}}
	}},
}

func merge(old, nu any) any {
	om, ok1 := old.(map[string]any)
	nm, ok2 := nu.(map[string]any)
	if ok1 && ok2 {
		out := map[string]any{}
		for k, v := range om {
			out[k] = v
		}
		for k, v := range nm {
			if ov, ok := om[k]; ok {
				out[k] = merge(ov, v)
			} else {
				out[k] = v
			}
		}
		return out
	}
	oa, ok1 := old.([]any)
	na, ok2 := nu.([]any)
	if ok1 && ok2 {
		out := append([]any{}, oa...)
		for _, x := range na {
			dup := false
			for _, y := range oa {
				if JSON(x, "") == JSON(y, "") {
					dup = true
				}
			}
			if !dup {
				out = append(out, x)
			}
		}
		return out
	}
	return nu
}

func Install(agent string) {
	s, ok := settings[agent]
	if !ok {
		fmt.Fprintln(os.Stderr, "install <agent>: one of claude, codex, cursor, copilot, gemini")
		os.Exit(1)
	}
	exe, _ := os.Executable()
	exe, _ = filepath.EvalSymlinks(exe)
	root, err := filepath.EvalSymlinks(ROOT) // links resolved on both sides, as the program's path is
	if err != nil {
		root = ROOT
	}
	me, err := filepath.Rel(root, exe)
	if err != nil {
		me = exe
	}
	me = filepath.ToSlash(me)
	full := filepath.Join(ROOT, s.path)
	var old any = map[string]any{}
	if b, err := os.ReadFile(full); err == nil {
		var v any
		if json.Unmarshal(b, &v) == nil && v != nil {
			old = v
		}
	}
	os.MkdirAll(filepath.Dir(full), 0o755)
	os.WriteFile(full, []byte(JSON(merge(old, s.make(me)), "  ")+"\n"), 0o644)
	msg := fmt.Sprintf("%s: the map guard installed for %s (%s).", s.path, agent, me)
	if agent == "codex" {
		msg += " Codex runs project hooks once the .codex folder is trusted."
	}
	fmt.Println(msg)
}

// Main is what cmd/map-guard runs: stdin in, the decision out.
func Main(argv []string) {
	Setup()
	if len(argv) == 2 && argv[0] == "install" {
		Install(argv[1])
		return
	}
	if len(argv) == 2 && argv[0] == "try" {
		cwd, _ := os.Getwd()
		if asked := ShellQuestion(argv[1], cwd); asked != "" {
			fmt.Println(asked)
		} else {
			fmt.Println("goes ahead")
		}
		return
	}
	agent := ""
	for i, a := range argv {
		if a == "--agent" && i+1 < len(argv) {
			agent = argv[i+1]
		}
	}
	var data map[string]any
	dec := json.NewDecoder(os.Stdin)
	if err := dec.Decode(&data); err != nil || data == nil {
		return
	}
	if agent == "" {
		agent = Detect(data)
	}
	if asked := Replacement(agent, data); asked != "" {
		fmt.Println(JSON(Answer(agent, asked), ""))
	}
}

var _ = utf8.RuneLen

// @end map.guard.decide
