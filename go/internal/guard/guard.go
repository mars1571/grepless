// @map map.guard.scope: what the map reads (the code and the docs of the repository), how a command's paths resolve, and the agents' hook formats
// Package guard is the Go version of python/map-guard.py: the same refusals, the same asks, the same five agents.
package guard

import (
	"encoding/json"
	"fmt"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"
)

var ROOT string
var CFG map[string]any
var ASK string
var skipped []string
var SUBAGENTS = "deny" // a subagent's read line: run in its place ("translate"), or denied with its ask
var TEXT = map[string]bool{}
var NAMED = set("Makefile GNUmakefile Dockerfile Containerfile Rakefile Gemfile Justfile Vagrantfile CMakeLists.txt Jenkinsfile")
var SKIP = set("node_modules dist build out target vendor venv .venv __pycache__ .git .hg .svn .tox .mypy_cache .pytest_cache .cache coverage .idea .vscode bower_components .next .nuxt .terraform Pods DerivedData map")
var SEARCH = set("grep egrep fgrep rg ag ack")
var READ = set("cat sed head tail awk nl less more bat cut sort uniq strings xxd od perl ruby")
var FILE_FILTERS = map[string]string{"cut": "bcdf", "sort": "ktTS", "uniq": "fsw"} // filters that read a file given to them: the flags that take a value
var LIST = set("ls find tree fd")
var FILTERS = set("head tail cut grep egrep sort uniq wc sed awk tr column")
var KEPT = set("head tail cut grep egrep sort uniq wc tr column") // filters a line run in its place keeps: none runs a command or writes
var QUIET = set("echo printf true : wc")                          // steps a line run in its place keeps as they are

const REASON_LINE = "This repository's code and docs are read and located through its map, every question of a round in one call " +
	"(AGENTS.md, \"Finding code\"); it answers what this would, by block, with the code. None of this command ran: send this line instead, its reads already through the map. Run instead:\n  "

const NOTE = "map-guard ran this line through the map, each read of the code or the docs as its ask (AGENTS.md, \"Finding code\"; " +
	"next time, ask every question of a round in one call):\n  "

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
	if g, ok := CFG["guard"].(map[string]any); ok && g["subagents"] == "translate" {
		SUBAGENTS = "translate"
	}
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
	return rootForm(cwd)
}

// rootForm: the root in the form realpath gives the paths under it. On Windows that is the canonical one (the drive
// letter's case, long names), so Rel finds the paths inside it; elsewhere the root stays as found, like Python's.
func rootForm(p string) string {
	if runtime.GOOS == "windows" {
		return realpath(p)
	}
	return p
}

var msysRx = regexp.MustCompile(`(?s)^(?:/cygdrive)?/([A-Za-z])(/.*)?$`)

// msysPath: a Git Bash drive path (/c/Users/x, /cygdrive/c/x) as Windows names it (C:/Users/x); false on other
// systems and for any other path.
func msysPath(p string) (string, bool) {
	if runtime.GOOS != "windows" {
		return "", false
	}
	m := msysRx.FindStringSubmatch(p)
	if m == nil {
		return "", false
	}
	tail := m[2]
	if tail == "" {
		tail = "/"
	}
	return strings.ToUpper(m[1]) + ":" + tail, true
}

// expanduser: os.path.expanduser; on Windows $HOME (else the profile) for a leading ~, and Git Bash's drive paths as
// Windows names them.
func expanduser(p string) string {
	if runtime.GOOS != "windows" {
		if strings.HasPrefix(p, "~") {
			home, _ := os.UserHomeDir()
			return filepath.Join(home, p[1:])
		}
		return p
	}
	if strings.HasPrefix(p, "~") {
		home := os.Getenv("HOME")
		if home == "" {
			home = os.Getenv("USERPROFILE")
		}
		if home != "" {
			return filepath.Join(home, strings.TrimLeft(p[1:], "/"))
		}
	}
	if m, ok := msysPath(p); ok {
		return m
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
	full := realpath(joinPath(base, p))
	rel, err := filepath.Rel(ROOT, full)
	if err != nil || strings.HasPrefix(rel, "..") {
		return "", false
	}
	if runtime.GOOS == "windows" {
		rel = filepath.ToSlash(rel) // agents write `/` on Windows too
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
	parts := strings.Split(rel, "/")
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
			if rel == q || strings.HasPrefix(rel, q+"/") || Fnmatch(rel, q) {
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
	if rel == "map.yaml" || strings.Split(rel, "/")[0] == "map" {
		return false
	}
	st, err := os.Stat(filepath.Join(ROOT, rel))
	if err != nil {
		return false
	}
	if st.IsDir() {
		return folderOk && !ignored(rel) && holdsMapped(rel)
	}
	return isText(rel) && !ignored(rel)
}

// @map map.guard.scope.folder: whether a folder holds a file the map reads (one that holds none is never sent to an ask), and the walk of a folder's files a Glob shares
const folderSeen = 50000 // files looked at in a folder; past them it is taken to hold one

var holdsCache = map[string]bool{}

// holdsMapped: whether a folder holds a file the map reads, below the folders it leaves out; one that holds none is not
// sent to an ask, which would answer nothing. Memoized per process.
func holdsMapped(rel string) bool {
	if v, ok := holdsCache[rel]; ok {
		return v
	}
	found, capped := walkFiles(rel, folderSeen, func(sub string) bool { return isText(sub) && !ignored(sub) })
	holdsCache[rel] = found || capped
	return found || capped
}

// walkFiles: the files under a folder of the repository (rel, from the root), depth first, the folders in order, those
// the map leaves out (SKIP, ignored) and the links to folders not entered. visit gets each file's path and stops the walk
// by returning true; the walk also stops once a folder's files bring the count past limit. It reports which of the two.
func walkFiles(rel string, limit int, visit func(sub string) bool) (found, capped bool) {
	seen := 0
	var walk func(here string) bool
	walk = func(here string) bool {
		dir := ROOT
		if here != "." {
			dir = filepath.Join(ROOT, filepath.FromSlash(here))
		}
		entries, err := os.ReadDir(dir)
		if err != nil {
			return false
		}
		var dirs []string
		for _, e := range entries {
			n := e.Name()
			if e.Type()&(os.ModeSymlink|os.ModeIrregular) != 0 {
				if st, err := os.Stat(filepath.Join(dir, n)); err == nil && st.IsDir() {
					continue // a link to a folder: listed among the folders, not entered
				}
			}
			sub := n
			if here != "." {
				sub = here + "/" + n
			}
			if e.IsDir() {
				if !SKIP[n] && !ignored(sub) {
					dirs = append(dirs, n)
				}
				continue
			}
			seen++
			if visit(sub) {
				return true
			}
		}
		if seen > limit {
			capped = true
			return false
		}
		sort.Strings(dirs)
		for _, d := range dirs {
			sub := d
			if here != "." {
				sub = here + "/" + d
			}
			if walk(sub) {
				return true
			}
			if capped {
				break
			}
		}
		return false
	}
	found = walk(path.Clean(rel))
	return found, capped
}

// @end map.guard.scope.folder

var safeRx = regexp.MustCompile(`^[A-Za-z0-9@%+=:,./_-]+$`)

// rootWord: the root as a word of the shell line: on Windows with `/`, which bash reads as it is.
func rootWord() string {
	if runtime.GOOS == "windows" {
		return quoteWord(strings.ReplaceAll(ROOT, `\`, "/"))
	}
	return quoteWord(ROOT)
}

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

var quietRx = regexp.MustCompile(`&>\s*/dev/null|\d?>&\d|\d?>\s*/dev/null`) // stderr or all output thrown away: no word of the command
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
					base = joinPath(base, words[1])
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
// @map map.guard.commands.questions: the ask for each kind of read: grep and git grep, cat, sed, head and tail, ls and find
var tagRx = regexp.MustCompile(`@map\s+([\w.-]+)`)
var headingPat = regexp.MustCompile(`^\^#+.*$`)
var basicRx = regexp.MustCompile(`\\([|(){}+?])|([|(){}+?])`)

// grepParts: (patterns, paths, includes, flags) of a grep-like search. The word after `--` is no option even when it starts
// with `-`: it is the pattern (unless -e gave it) or a place; the words after it are read as before, so `src --include=*.py` still filters.
func grepParts(words []string) (pats, paths, includes []string, flags map[string]bool) {
	flags = map[string]bool{}
	ended, literal := false, false
	for i := 1; i < len(words); i++ {
		a := words[i]
		switch {
		case literal:
			paths, literal = append(paths, a), false
		case a == "--" && !ended:
			ended, literal = true, true
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
	return
}

func GrepQuestion(words []string, base string) []string {
	return grepQuestion(words, base, false)
}

// grepQuestion: the ask for a grep-like search over the code or the docs, or nil when it searches elsewhere. git: `git grep`,
// whose pathspecs with a wildcard and no `/` ('*.rs') match at any depth (they are includes, as grep's --include) and whose
// magic pathspecs (':!tests') are left out.
func grepQuestion(words []string, base string, git bool) []string {
	pats, paths, includes, flags := grepParts(words)
	if git {
		var kept []string
		for _, p := range paths {
			bare := wildRx.MatchString(p) && !strings.Contains(p, "/")
			if bare && !strings.HasPrefix(p, ":") {
				includes = append(includes, p)
			}
			if !strings.HasPrefix(p, ":") && !bare {
				kept = append(kept, p)
			}
		}
		paths = kept
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
		if Mapped(r.p, r.ok, true) || mappedGlob(r.p, r.ok) {
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
				np = append(np, strings.TrimLeft(path.Join(p, "*"+strings.TrimLeft(g, "*")), "/"))
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

// mappedGlob: whether a path with a wildcard in a folder of it (src/**/*.rs) names a place the map reads: the folder before the
// first wildcard segment is one (Mapped answers for a wildcard in the last segment only).
func mappedGlob(rel string, ok bool) bool {
	if !ok || !wildRx.MatchString(rel) {
		return false
	}
	parts := strings.Split(rel, "/")
	k := 0
	for i, seg := range parts {
		if wildRx.MatchString(seg) {
			k = i
			break
		}
	}
	return k < len(parts)-1 && (k == 0 || Mapped(strings.Join(parts[:k], "/"), true, true))
}

// gitGrep: (grep's words, the folder) for `git [-C dir] [--no-pager] [-c k=v] grep ...`, else ok false.
func gitGrep(words []string, base string) ([]string, string, bool) {
	i := 1
	for i < len(words) && strings.HasPrefix(words[i], "-") {
		switch {
		case words[i] == "-C" && i+1 < len(words):
			base, i = joinPath(base, words[i+1]), i+2
		case (words[i] == "-c" || words[i] == "--git-dir" || words[i] == "--work-tree" || words[i] == "--namespace") && i+1 < len(words):
			i += 2
		default:
			i++
		}
	}
	if i < len(words) && words[i] == "grep" {
		return append([]string{"grep", "-r"}, words[i+1:]...), base, true
	}
	return nil, base, false
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

// fileFilter: (the filter's words without its files, the files) of cut, sort or uniq; false when it writes (sort -o, uniq's output).
func fileFilter(words []string) (keep, files []string, ok bool) {
	tool, skip := filepath.Base(words[0]), false
	keep = []string{words[0]}
	for _, a := range words[1:] {
		switch {
		case skip:
			keep = append(keep, a)
			skip = false
		case strings.HasPrefix(a, "--") && len(a) > 2:
			if strings.HasPrefix(a, "--output") {
				return nil, nil, false
			}
			keep = append(keep, a)
		case strings.HasPrefix(a, "-") && len(a) > 1:
			if tool == "sort" && strings.Contains(a[1:], "o") {
				return nil, nil, false
			}
			keep = append(keep, a)
			skip = len(a) == 2 && strings.IndexByte(FILE_FILTERS[tool], a[1]) >= 0
		default:
			files = append(files, a)
		}
	}
	if tool == "uniq" && len(files) > 1 {
		return nil, nil, false
	}
	return keep, files, true
}

// readFiles: (script, files) of a read: sed's script (awk's program is passed over), and the files it names.
func readFiles(words []string) (script string, hasScript bool, files []string) {
	tool, args := words[0], words[1:]
	if FILE_FILTERS[tool] != "" {
		_, files, _ = fileFilter(words)
		return
	}
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
	return
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
	script, hasScript, files := readFiles(words)
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
			return []string{path.Join(dir, "*"+strings.TrimLeft(pattern, "*"))}
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

// @end map.guard.commands.questions
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
			f := joinPath(c.base, name)
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

// @map map.guard.commands.rewrite: a line that edits a file, whose reads check the edit; a line of reads only, run through the map in its place
var simpleSed = regexp.MustCompile(`^(?:(?:\d+|\$)(?:,(?:\d+|\$))?p|\d+q)$`)                                // sed -n 5,20p: a range of lines, nothing that runs or writes
var simpleAwk = regexp.MustCompile(`^NR\s*(?:>=|<=|==|<|>)\s*\d+(?:\s*&&\s*NR\s*(?:>=|<=|==|<|>)\s*\d+)?$`) // awk 'NR>=5 && NR<=20'
var syntax = set("for in case select done fi esac do then else elif if while until { } ! function")
var segmentRx = regexp.MustCompile(`(?s)^(\s*)((?:(?:do|then|else|elif|if|while|until|!|\{|time)\s+)*)(.*?)(\s*)$`)
var assignRx = regexp.MustCompile(`^[A-Za-z_]\w*=.*$`)
var redirWordRx = regexp.MustCompile(`^[<>&]+$`)
var gitRead = set("status log diff show rev-parse branch")
var gitBranchFlags = set("--list --all --remotes --verbose --show-current --no-color --color --ignore-case --merged --no-merged --contains --no-contains --points-at --sort --format --abbrev --column --no-column")
var gitBranchValues = set("--merged --no-merged --contains --no-contains --points-at --sort --format --abbrev")
var branchListRx = regexp.MustCompile(`^-[a-z]*l[a-z]*$`)
var branchShortRx = regexp.MustCompile(`^-[arvli]+$`)
var dateIsoRx = regexp.MustCompile(`^(?:-I\w*|--iso-8601(=\w+)?)$`)

// lineWrites: whether the line changes a file of the repository: sed -i, perl -i, a redirection or tee into it, patch,
// git apply, a script that writes.
func lineWrites(line, cwd string) bool {
	for _, c := range Commands(line, cwd) {
		words := c.words
		tool := filepath.Base(words[0])
		var targets []string
		for k := 0; k < len(words)-1; k++ {
			if words[k] == ">" || words[k] == ">>" || words[k] == "&>" {
				targets = append(targets, words[k+1])
			}
		}
		if tool == "tee" {
			targets = append(targets, words[1:]...)
		}
		for _, t := range targets {
			if _, ok := Inside(t, c.base); ok && !strings.Contains(t, "$") && !strings.HasPrefix(t, "-") {
				return true
			}
		}
		if tool == "patch" || (tool == "git" && len(words) > 1 && words[1] == "apply") {
			return true
		}
		if tool == "sed" {
			for _, a := range words[1:] {
				if strings.HasPrefix(a, "-i") || a == "--in-place" {
					return true
				}
			}
		}
		if tool == "perl" || tool == "ruby" {
			for _, a := range words[1:] {
				if inplaceRx.MatchString(a) {
					return true
				}
			}
		}
	}
	for _, text := range scripts(line, cwd) {
		if writes(text) {
			return true
		}
	}
	return false
}

// isMap: whether a command runs the map itself (the command of map.json, any of its commands).
func isMap(words []string) bool {
	head := strings.Fields(ASK)
	head = head[:len(head)-1]
	if len(words) < len(head) {
		return false
	}
	for k, h := range head {
		if words[k] != h {
			return false
		}
	}
	return true
}

// whole: whether the map answers all a read names: no file or folder of it would be left out of its ask.
func whole(words []string, base string) bool {
	tool := filepath.Base(words[0])
	git := false
	if tool == "git" {
		if gw, gb, ok := gitGrep(words, base); ok {
			git, words, base, tool = true, gw, gb, "grep"
		}
	}
	rest := append([]string{tool}, words[1:]...)
	switch {
	case SEARCH[tool]:
		_, paths, _, _ := grepParts(rest)
		for _, p := range paths {
			if git && (strings.HasPrefix(p, ":") || (wildRx.MatchString(p) && !strings.Contains(p, "/"))) {
				continue
			}
			r, ok := Inside(p, base)
			if !Mapped(r, ok, true) && !mappedGlob(r, ok) {
				return false
			}
		}
		return true
	case READ[tool]:
		_, _, files := readFiles(rest)
		for _, f := range files {
			r, ok := Inside(f, base)
			if !Mapped(r, ok, false) {
				return false
			}
		}
		return true
	case tool == "ls" || tool == "tree":
		for _, a := range words[1:] {
			if strings.HasPrefix(a, "-") {
				continue
			}
			r, ok := Inside(a, base)
			if !Mapped(r, ok, true) {
				return false
			}
		}
		return true
	}
	return tool == "find"
}

type segment struct{ sep, text string }

// splitLine: the line cut at each ; && || | |& & newline ( ) outside quotes, every text exactly as written; false when it
// holds a heredoc, a $( ) or backticks that run (the line cannot be rebuilt).
func splitLine(line string) ([]segment, bool) {
	if len(heredocs(line)) > 0 {
		return nil, false
	}
	var out []segment
	var buf []byte
	sep := ""
	var quote byte
	i, n := 0, len(line)
	lastIs := func(chars string) bool { return len(buf) > 0 && strings.IndexByte(chars, buf[len(buf)-1]) >= 0 }
	for i < n {
		c := line[i]
		hasNxt := i+1 < n
		var nxt byte
		if hasNxt {
			nxt = line[i+1]
		}
		switch {
		case quote == '\'':
			if c == '\'' {
				quote = 0
			}
		case c == '\\' && hasNxt:
			buf = append(buf, line[i:i+2]...)
			i += 2
			continue
		case c == '`' || strings.HasPrefix(line[i:], "$("):
			return nil, false
		case quote == '"':
			if c == '"' {
				quote = 0
			}
		case c == '\'' || c == '"':
			quote = c
		case c == '#' && (len(buf) == 0 || lastIs(" \t\n\r\f\v")):
			j := strings.IndexByte(line[i:], '\n')
			if j < 0 {
				j = n
			} else {
				j += i
			}
			buf = append(buf, line[i:j]...)
			i = j
			continue
		default:
			op := ""
			switch {
			case c == '\n':
				op = "\n"
			case strings.HasPrefix(line[i:], ";;"):
				op = ";;"
			case c == ';':
				op = ";"
			case strings.HasPrefix(line[i:], "||"):
				op = "||"
			case strings.HasPrefix(line[i:], "|&"):
				op = "|&"
			case c == '|':
				op = "|"
			case c == '(':
				op = "("
			case c == ')':
				op = ")"
			case c != '&' || lastIs("<>") || (hasNxt && nxt == '>'):
			case hasNxt && nxt == '&':
				op = "&&"
			default:
				op = "&"
			}
			if op != "" {
				out = append(out, segment{sep, string(buf)})
				sep, buf, i = op, nil, i+len(op)
				continue
			}
		}
		buf = append(buf, c)
		i++
	}
	out = append(out, segment{sep, string(buf)})
	return out, true
}

// step: one segment of a line: sep, lead, prefix (do, then, if ...), core, trail (the text around it, kept as written),
// words (redirections to /dev/null left out), kind (syntax, cd or cmd), piped (a pipe feeds it), base (the folder it runs
// in, cd and ( ) followed) and redirected; drop and text are set by rebuild.
type step struct {
	sep, lead, prefix, core, trail string
	words                          []string
	kind                           string
	piped                          bool
	base                           string
	redirected                     bool
	drop                           string
	text                           string
	hasText                        bool
}

func (s step) written() string {
	if s.hasText {
		return s.text
	}
	return s.lead + s.prefix + s.core + s.trail
}

// joinPath: os.path.join(base, expanduser(p)): an absolute p replaces base. On Windows a path rooted without a drive
// (`/tmp/x`) stays on the drive of base, as in Python and Rust, and does not land under base.
func joinPath(base, p string) string {
	p = expanduser(p)
	if filepath.IsAbs(p) {
		return p
	}
	if runtime.GOOS == "windows" && p != "" && os.IsPathSeparator(p[0]) {
		return filepath.Clean(filepath.VolumeName(base) + p)
	}
	return filepath.Join(base, p)
}

// steps: the line as a list of steps; false when the line cannot be rebuilt or a folder is unknown.
func steps(line, cwd string) ([]step, bool) {
	segs, ok := splitLine(line)
	if !ok {
		return nil, false
	}
	var out []step
	base, known := cwd, true
	var stack []string
	for k, sg := range segs {
		if sg.sep == "(" {
			stack = append(stack, base)
		} else if sg.sep == ")" && len(stack) > 0 {
			base = stack[len(stack)-1]
			stack = stack[:len(stack)-1]
		}
		m := segmentRx.FindStringSubmatch(sg.text)
		lead, prefix, core, trail := m[1], m[2], m[3], m[4]
		words := ShellWords(quietRx.ReplaceAllString(core, " "))
		hasName := false
		for _, w := range words {
			if !assignRx.MatchString(w) {
				hasName = true
			}
		}
		piped := k > 0 && (sg.sep == "|" || sg.sep == "|&")
		kind := "cmd"
		if !hasName || len(words) == 0 || syntax[words[0]] {
			kind = "syntax"
		} else if words[0] == "cd" && !piped {
			kind = "cd"
		}
		redirected := false
		for _, w := range words {
			if redirWordRx.MatchString(w) {
				redirected = true
			}
		}
		out = append(out, step{sep: sg.sep, lead: lead, prefix: prefix, core: core, trail: trail, words: words, kind: kind,
			piped: piped, base: base, redirected: redirected})
		if kind == "cd" {
			if len(words) != 2 || strings.Contains(words[1], "$") || words[1] == "-" {
				known = false
			} else {
				base = filepath.Clean(joinPath(base, words[1]))
			}
		}
		if !known && k+1 < len(segs) {
			return nil, false
		}
	}
	return out, true
}

// anchored: the text run in the folder it was written for: as it is at the root, else in a (cd root && ...) of its own.
func anchored(base, text string) string {
	if realpath(base) == realpath(ROOT) {
		return text
	}
	return "(cd " + rootWord() + " && " + text + ")"
}

// @map map.guard.commands.rewrite.readonly: the steps that only read and touch nothing outside the repository (git's read-only forms, which, --version, date, counts, filters), and the reads safe to keep as written
// gitReadOnly: whether a git command only reads this repository: status, log, diff, show, rev-parse, branch (listing).
func gitReadOnly(words []string, base string) bool {
	args, i := words[1:], 0
	for i < len(args) && strings.HasPrefix(args[i], "-") {
		if args[i] == "-C" && i+1 < len(args) {
			base, i = joinPath(base, args[i+1]), i+2
		} else if args[i] == "--no-pager" || args[i] == "--no-optional-locks" {
			i++
		} else {
			return false
		}
	}
	if _, ok := Inside(".", base); !ok || i >= len(args) || !gitRead[args[i]] {
		return false
	}
	sub, rest := args[i], args[i+1:]
	if sub == "branch" {
		listing := false
		for _, a := range rest {
			if a == "-l" || a == "--list" || branchListRx.MatchString(a) {
				listing = true
			}
		}
		for k, a := range rest {
			if strings.HasPrefix(a, "--") {
				if !gitBranchFlags[strings.SplitN(a, "=", 2)[0]] {
					return false
				}
			} else if strings.HasPrefix(a, "-") {
				if !branchShortRx.MatchString(a) {
					return false
				}
			} else if !(listing || (k > 0 && gitBranchValues[rest[k-1]])) {
				return false // a name with no listing flag makes a branch
			}
		}
		return true
	}
	for _, a := range rest {
		if a == "-O" || a == "--open-files-in-pager" || a == "--no-index" || a == "--ext-diff" || a == "--output" ||
			strings.HasPrefix(a, "-O") || strings.HasPrefix(a, "--output=") {
			return false
		}
	}
	return true
}

func dateReadOnly(args []string) bool {
	for _, a := range args {
		if !(strings.HasPrefix(a, "+") || a == "-u" || a == "--utc" || a == "--universal" || a == "-R" || a == "--rfc-email" || dateIsoRx.MatchString(a)) {
			return false
		}
	}
	return true
}

func insideAll(operands []string, base string) bool {
	for _, a := range operands {
		if _, ok := Inside(a, base); !ok {
			return false
		}
	}
	return true
}

// flagsAndOperands: the words that start with - and the ones that do not.
func flagsAndOperands(args []string) (flags map[string]bool, operands []string) {
	flags = map[string]bool{}
	for _, a := range args {
		if strings.HasPrefix(a, "-") {
			flags[a] = true
		} else {
			operands = append(operands, a)
		}
	}
	return
}

// safeHead: whether a read of the repository stays safe as it was written: a search that only counts, cat, head, tail, ls ...,
// sed with a range, awk with NR conditions; every file in the repository and nothing that runs a command or writes.
func safeHead(words []string, base string) bool {
	tool, args := filepath.Base(words[0]), words[1:]
	flags, operands := flagsAndOperands(args)
	switch {
	case SEARCH[tool]:
		_, paths, _, _ := grepParts(words)
		for _, a := range args {
			if h := strings.SplitN(a, "=", 2)[0]; h == "--pre" || h == "--hostname-bin" {
				return false
			}
		}
		if len(paths) == 0 {
			paths = []string{"."}
		}
		return insideAll(paths, base)
	case tool == "cat" || tool == "head" || tool == "tail" || tool == "nl" || tool == "ls" || tool == "tree":
		return insideAll(operands, base)
	case FILE_FILTERS[tool] != "":
		_, _, ok := fileFilter(words)
		return ok && insideAll(operands, base)
	case tool == "find":
		for _, a := range args {
			if a == "-exec" || a == "-execdir" || a == "-ok" || a == "-okdir" || a == "-delete" || strings.HasPrefix(a, "-fprint") || strings.HasPrefix(a, "-fls") {
				return false
			}
		}
		first := []string{"."}
		if len(operands) > 0 {
			first = operands[:1]
		}
		return insideAll(first, base)
	case tool == "sed":
		for f := range flags {
			if f != "-n" && f != "-E" && f != "-r" {
				return false
			}
		}
		return len(operands) > 0 && simpleSed.MatchString(operands[0]) && insideAll(operands[1:], base)
	case tool == "awk":
		return len(flags) == 0 && len(operands) > 0 && simpleAwk.MatchString(operands[0]) && insideAll(operands[1:], base)
	}
	return false
}

// safeStep: whether a step that is no read of the map's may stay in a line Claude Code runs without asking: it only reads and
// touches nothing outside the repository.
func safeStep(words []string, base string) bool {
	tool, args := filepath.Base(words[0]), words[1:]
	if isMap(words) || tool == "echo" || tool == "printf" || tool == "true" || tool == ":" || tool == "pwd" {
		return true
	}
	if tool == "wc" {
		_, operands := flagsAndOperands(args)
		return insideAll(operands, base)
	}
	if tool == "date" {
		return dateReadOnly(args)
	}
	if tool == "which" {
		for _, a := range args {
			if strings.HasPrefix(a, "-") && a != "-a" && a != "-s" {
				return false
			}
		}
		return true
	}
	if words[0] == "command" {
		return len(words) > 2 && (words[1] == "-v" || words[1] == "-V")
	}
	if len(words) == 2 && args[0] == "--version" && !strings.Contains(words[0], "/") {
		return true
	}
	if tool == "git" {
		return gitReadOnly(words, base)
	}
	return SEARCH[tool] && safeHead(words, base) // grep -c file, grep -q ...: a count or a yes
}

// filterOk: whether a filter in a pipe is kept: head, tail, cut, grep, sort, uniq, wc, tr, column, or sed -n with a range.
func filterOk(words []string) bool {
	if KEPT[filepath.Base(words[0])] {
		return true
	}
	if filepath.Base(words[0]) != "sed" {
		return false
	}
	flags, operands := flagsAndOperands(words[1:])
	for f := range flags {
		if f != "-n" {
			return false
		}
	}
	return len(operands) == 1 && simpleSed.MatchString(operands[0])
}

// @end map.guard.commands.rewrite.readonly

// chainRead: what a pipeline's first command is: "read" (with its ask, the steps left after it and whether xargs ran it) for a
// read the map answers, "count" for one that only counts, "step" for anything else, "syntax" for a loop's keywords, an
// assignment or a cd.
func chainRead(chain []step) (kind, ask string, left []step, xargs bool) {
	first := chain[0]
	words, base := first.words, first.base
	if first.kind != "cmd" {
		return "syntax", "", nil, false
	}
	if first.redirected {
		return "step", "", nil, false
	}
	if filepath.Base(words[0]) == "find" && len(chain) > 1 && len(chain[1].words) > 1 && chain[1].words[0] == "xargs" && SEARCH[filepath.Base(chain[1].words[1])] {
		pattern := "*"
		for j, a := range words {
			if (a == "-name" || a == "-iname") && j+1 < len(words) {
				pattern = words[j+1]
				break
			}
		}
		root := "."
		for _, a := range words[1:] {
			if !strings.HasPrefix(a, "-") {
				root = a
				break
			}
		}
		q := GrepQuestion(append(append([]string{}, chain[1].words[1:]...), "-r", root, "--include="+pattern), base)
		if len(q) > 0 {
			return "read", ASK + Quote(q), chain[2:], true
		}
		return "step", "", nil, false
	}
	q := question(words, base)
	if len(q) == 0 {
		return "step", "", nil, false
	}
	var run [][]string
	for _, s := range chain[1:] {
		if len(s.words) == 0 || !FILTERS[filepath.Base(s.words[0])] {
			break
		}
		run = append(run, s.words)
	}
	if counts(run) {
		return "count", "", nil, false
	}
	q, kept := folded(words, base, run)
	own := ""
	if FILE_FILTERS[filepath.Base(words[0])] != "" {
		if keep, _, ok := fileFilter(words); ok {
			own = " | " + Quote(keep)
		}
	}
	for k, s := range chain[1:] {
		if k >= len(run) {
			left = append(left, s)
		} else if kept[k] {
			left = append(left, s)
		}
	}
	return "read", ASK + Quote(q) + own, left, false
}

// folded: (the question, which of the filters its output feeds are kept) for a read. `head` and `tail` are dropped: the ask's
// lines are its answer, and a cut of them leaves its header and none of the code. A `cat` that feeds a search is that search
// over its files (`cat f | grep x` becomes `grep x f`), one that feeds `head` or `tail` is the range of its files.
func folded(words []string, base string, run [][]string) ([]string, map[int]bool) {
	var q []string
	from := 0
	if filepath.Base(words[0]) == "cat" && len(run) > 0 {
		_, _, files := readFiles(words)
		first := run[0]
		if len(files) > 0 && SEARCH[filepath.Base(first[0])] && func() bool { _, p, _, _ := grepParts(first); return len(p) == 0 }() {
			q = question(append(append([]string{}, first...), files...), base)
		} else if len(files) > 0 && filepath.Base(first[0]) == "head" || len(files) > 0 && filepath.Base(first[0]) == "tail" {
			if _, _, ff := readFiles(first); len(ff) == 0 {
				q = ReadQuestion(append(append([]string{}, first...), files...), base)
			}
		}
		if len(q) > 0 {
			from = 1
		}
	}
	if len(q) == 0 {
		q = question(words, base)
	}
	kept := map[int]bool{}
	for k := from; k < len(run); k++ {
		if b := filepath.Base(run[k][0]); b != "head" && b != "tail" {
			kept[k] = true
		}
	}
	return q, kept
}

// built: the line rebuilt: its text, whether a read was replaced, ok (every step only reads) and pure (reads and their
// filters only).
type built struct {
	text               string
	replaced, ok, pure bool
}

// rebuild: the line with each read of the code or the docs as its ask, every other step as written: in place (Claude Code:
// from the root, cd steps dropped, steps outside the root in a (cd ...) of their own) or to send again (each ask in a
// (cd root && ...) when the line is not at the root). nil when the line cannot be rebuilt.
func rebuild(line, cwd string, inPlace bool) *built {
	st, ok := steps(line, cwd)
	if !ok || len(ScriptQuestion(line, cwd)) > 0 {
		return nil
	}
	var out []step
	replaced, allOk, pure := false, true, true
	for k := 0; k < len(st); {
		j := k + 1
		for j < len(st) && st[j].piped {
			j++
		}
		chain, first := st[k:j], st[k]
		kind, ask, left, xargs := chainRead(chain)
		rest := chain[1:]
		if kind == "read" {
			rest = left
		}
		for _, s := range rest {
			allOk = allOk && len(s.words) > 0 && filterOk(s.words) && !s.redirected
			pure = pure && len(s.words) > 0 && FILTERS[filepath.Base(s.words[0])]
		}
		switch kind {
		case "syntax":
			if first.kind == "cd" && inPlace {
				first.drop = "transfer"
			}
			out = append(out, first)
		case "read":
			replaced = true
			allOk = allOk && !xargs && whole(first.words, first.base) // xargs could run anything
			trail := first.trail
			if inPlace {
				first.text = first.lead + first.prefix + ask + trail
			} else {
				first.text = first.lead + first.prefix + anchored(first.base, ask) + trail
			}
			first.hasText = true
			out = append(out, first)
			if xargs {
				own := chain[1]
				own.drop = "own"
				out = append(out, own)
			}
		default:
			pure = false
			words := first.words
			good := false
			if !first.redirected {
				if kind == "count" {
					good = safeHead(words, first.base) && whole(words, first.base)
				} else {
					good = safeStep(words, first.base)
				}
			}
			allOk = allOk && good
			text := first.lead + first.prefix + first.core + first.trail
			if inPlace && realpath(first.base) != realpath(ROOT) {
				text = first.lead + first.prefix + "(cd " + quoteWord(first.base) + " && " + strings.TrimSpace(first.core) + ")" + first.trail
			}
			first.text, first.hasText = text, true
			out = append(out, first)
		}
		out = append(out, rest...)
		k = j
	}
	var b strings.Builder
	carry, carried := "", false
	for _, s := range out {
		sep := s.sep
		if carried {
			sep = carry
		}
		if s.drop == "transfer" {
			carry, carried = s.sep, true
			continue
		}
		carried = false
		if s.drop == "own" {
			continue
		}
		b.WriteString(sep + s.written())
	}
	return &built{b.String(), replaced, allOk, pure}
}

// rewrite: the line run through the map in its place, from the root: each read of the code or the docs as its ask, every other
// step as written, in order; "" when a step does more than read, or a filter could run a command.
func rewrite(line, cwd string) string {
	b := rebuild(line, cwd, true)
	if b == nil || !b.replaced || !b.ok {
		return ""
	}
	return "(cd " + rootWord() + " && " + strings.TrimSpace(b.text) + ")"
}

// resend: the whole line to send again when it is refused and mixed (reads beside other steps): each read as its ask, every
// other step exactly as written, the same separators; "" when it is reads only (the refusal names their asks) or cannot be rebuilt.
func resend(line, cwd string) string {
	b := rebuild(line, cwd, false)
	if b != nil && b.replaced && !b.pure {
		return b.text
	}
	return ""
}

// @end map.guard.commands.rewrite

// @map map.guard.commands.powershell: a PowerShell line into its statements, and Select-String, Get-Content and Get-ChildItem (with their aliases) as the bash read each equals, so one rule answers both shells
var psAlias = map[string]string{"select-string": "select-string", "sls": "select-string", "get-content": "get-content", "gc": "get-content", "cat": "get-content",
	"type": "get-content", "get-childitem": "get-childitem", "gci": "get-childitem", "ls": "get-childitem", "dir": "get-childitem"}

// psValued and psSwitches: a cmdlet's parameters that take a value, and its switches (a prefix that names one only is read as it).
var psValued = map[string]map[string]bool{
	"select-string": set("pattern path literalpath include exclude context encoding inputobject culture"),
	"get-content":   set("path literalpath totalcount head first tail last readcount encoding delimiter filter include exclude stream"),
	"get-childitem": set("path literalpath filter include exclude depth attributes"),
}
var psSwitches = map[string]map[string]bool{
	"select-string": set("simplematch casesensitive notmatch allmatches list quiet raw noemphasis"),
	"get-content":   set("raw wait force asbytestream"),
	"get-childitem": set("recurse r name force file directory hidden readonly system followsymlink ad af"),
}
var psCD = set("cd chdir set-location sl push-location pushd")
var psWrites = set("set-content add-content out-file tee-object tee remove-item copy-item move-item new-item clear-content rename-item set-item sc ac ri rm del erase rd rmdir cp copy mv move ni rni patch")
var psIdentity = set("out-string out-host format-list format-table fl ft more") // stages that only show what they are fed
var psFileRead = regexp.MustCompile(`(?i)\[(?:System\.)?IO\.File\]::(?:ReadAllText|ReadAllLines|ReadLines|OpenText)\(\s*(?:'(.+?)'|"(.+?)")`)
var psFileWrite = regexp.MustCompile(`(?i)\[(?:System\.)?IO\.File\]::(?:Write|Append|Create|Open\b|Copy|Move|Delete|Replace)|\.Save\(|WriteAll`)
var psSafe = regexp.MustCompile(`^[A-Za-z0-9_./:=+-]+\n?$`)
var psQuiet = regexp.MustCompile(`(?i)^(?:(?:\d|\*)?>&\d|(?:\d|\*)?>>?\$?(?:null|nul))$`) // stderr or all output thrown away
var psRedir = regexp.MustCompile(`^(?:\d|\*)?>>?$`)
var psRedirText = regexp.MustCompile(`^(?:\d|\*)?>>?[^&]`)
var psParam = regexp.MustCompile(`^-([A-Za-z]+)(?::(.*))?$`)
var psCount = regexp.MustCompile(`(?i)^\.(?:count|length)$`)
var psPlainName = regexp.MustCompile(`^[\p{L}\p{N}_.-]+$`)
var psFirstLast = regexp.MustCompile(`(?i)^-(first|last)$`)
var psRegexy = regexp.MustCompile(`[|()+^$\[\]{}]`)

// psTok: a token of the PowerShell line; op: it is syntax (; | && || ( ) { } &).
type psTok struct {
	s  string
	op bool
}

// baseName: os.path.basename: what follows the last separator ("" for an empty path or one ending in a separator).
func baseName(p string) string {
	seps := "/"
	if runtime.GOOS == "windows" {
		seps = `/\`
	}
	return p[strings.LastIndexAny(p, seps)+1:]
}

// psQuoteWord: a word quoted for PowerShell: as it is when it is safe, else in single quotes (a quote doubled).
func psQuoteWord(w string) string {
	if psSafe.MatchString(w) {
		return w
	}
	return "'" + strings.ReplaceAll(w, "'", "''") + "'"
}

func psQuote(words []string) string {
	var out []string
	for _, w := range words {
		out = append(out, psQuoteWord(w))
	}
	return strings.Join(out, " ")
}

// psTokens: the words of a PowerShell line, quotes resolved (a doubled quote inside '...', "" and the backtick inside "...", the
// backtick outside), the syntax as op tokens (a newline is a `;`), a word starting with # a comment to the end of the line.
// A backslash is a letter.
func psTokens(line string) []psTok {
	var out []psTok
	var word []byte
	had := false
	i, n := 0, len(line)
	for i < n {
		c := line[i]
		if c == '\'' || c == '"' {
			had, i = true, i+1
			for i < n {
				if c == '"' && line[i] == '`' && i+1 < n {
					word = append(word, line[i+1])
					i += 2
				} else if line[i] == c {
					if !(i+1 < n && line[i+1] == c) {
						break
					}
					word = append(word, c)
					i += 2
				} else {
					word = append(word, line[i])
					i++
				}
			}
			i++
			continue
		}
		if c == '`' && i+1 < n {
			if line[i+1] != '\n' {
				word = append(word, line[i+1])
				had = true
			}
			i += 2
			continue
		}
		isOp := strings.IndexByte(";|(){}&", c) >= 0
		if c == ' ' || c == '\t' || c == '\r' || c == '\n' || (isOp && !(c == '&' && len(word) > 0 && word[len(word)-1] == '>')) || (c == '#' && !had) {
			if had {
				out = append(out, psTok{string(word), false})
				word, had = nil, false
			}
			switch {
			case c == '#':
				j := strings.IndexByte(line[i:], '\n')
				if j < 0 {
					i = n
				} else {
					i += j
				}
			case c == '\n':
				out = append(out, psTok{";", true})
				i++
			case isOp:
				op := string(c)
				if i+1 < n && (line[i:i+2] == "&&" || line[i:i+2] == "||") {
					op = line[i : i+2]
				}
				out = append(out, psTok{op, true})
				i += len(op)
			default:
				i++
			}
			continue
		}
		word = append(word, c)
		had = true
		i++
	}
	if had {
		out = append(out, psTok{string(word), false})
	}
	return out
}

// psStatements: ([statement], writes): each statement a list of pipeline stages, each stage a list of words (parentheses and braces
// are passed through, redirections to $null left out); writes: a redirection into a file, or a cmdlet or call that writes.
func psStatements(line string) ([][][]string, bool) {
	var statements [][][]string
	var stages [][]string
	var words []string
	writes_, skip := false, false
	tokens := psTokens(line)
	for k, t := range tokens {
		switch {
		case skip:
			skip = false
		case t.op:
			if t.s == "(" || t.s == ")" || t.s == "{" || t.s == "}" || (t.s == "&" && len(words) == 0) {
				continue // a group, or the call operator
			}
			if len(words) > 0 {
				stages = append(stages, words)
			}
			words = nil
			if t.s != "|" {
				if len(stages) > 0 {
					statements = append(statements, stages)
				}
				stages = nil
			}
		case psQuiet.MatchString(t.s):
			continue
		case psRedir.MatchString(t.s): // > target: the target is no word of the command
			nxt := ""
			if k+1 < len(tokens) && !tokens[k+1].op {
				nxt = tokens[k+1].s
			}
			low := strings.ToLower(nxt)
			writes_ = writes_ || (low != "$null" && low != "nul")
			skip = nxt != ""
		case psRedirText.MatchString(t.s):
			writes_ = true
		default:
			words = append(words, t.s)
		}
	}
	if len(words) > 0 {
		stages = append(stages, words)
	}
	if len(stages) > 0 {
		statements = append(statements, stages)
	}
	for _, stmt := range statements {
		for _, st := range stmt {
			if psWrites[strings.ToLower(baseName(st[0]))] {
				writes_ = true
			}
		}
	}
	return statements, writes_ || psFileWrite.MatchString(line)
}

// psPath: a PowerShell path as the rest of the guard reads it: with `/`.
func psPath(p string) string { return strings.ReplaceAll(p, `\`, "/") }

// psWord: a word of a posix command in a PowerShell line: a path with backslashes in `/` (a pattern with regex syntax stays as it is).
func psWord(w string) string {
	if strings.Contains(w, `\`) && !psRegexy.MatchString(w) {
		return psPath(w)
	}
	return w
}

func psCommand(words []string) string {
	if len(words) == 0 {
		return ""
	}
	return psAlias[strings.ToLower(baseName(words[0]))]
}

// psVal: a parameter's value: its text (str), or a switch (sw).
type psVal struct {
	s   string
	str bool
	sw  bool
}

func (v psVal) truthy() bool { return v.sw || (v.str && v.s != "") }

// psArgs: ({parameter: its value, or a switch}, [the words that are no parameter]) of a cmdlet's arguments.
func psArgs(canon string, words []string) (map[string]psVal, []string) {
	valued, switches := psValued[canon], psSwitches[canon]
	named, pos := map[string]psVal{}, []string{}
	for i := 1; i < len(words); {
		m := psParam.FindStringSubmatchIndex(words[i])
		key := ""
		if m != nil {
			key = strings.ToLower(words[i][m[2]:m[3]])
		}
		full := ""
		if key != "" {
			if valued[key] || switches[key] {
				full = key
			} else {
				var near []string
				for x := range valued {
					if strings.HasPrefix(x, key) {
						near = append(near, x)
					}
				}
				for x := range switches {
					if strings.HasPrefix(x, key) {
						near = append(near, x)
					}
				}
				if len(near) == 1 {
					full = near[0]
				}
			}
		}
		switch {
		case full != "" && valued[full]:
			if m[4] >= 0 { // -Path:value
				named[full] = psVal{s: words[i][m[4]:m[5]], str: true}
				i++
			} else {
				v := ""
				if i+1 < len(words) {
					v = words[i+1]
				}
				named[full] = psVal{s: v, str: true}
				i += 2
			}
		case m != nil:
			if full != "" {
				named[full] = psVal{sw: true}
			}
			i++
		default:
			pos = append(pos, words[i])
			i++
		}
	}
	return named, pos
}

// psList: the comma-separated paths of a parameter's value, with `/`.
func psList(value psVal) []string {
	var out []string
	if !value.str {
		return out
	}
	for _, v := range strings.Split(value.s, ",") {
		if v != "" {
			out = append(out, psPath(v))
		}
	}
	return out
}

func psIsDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}

// @map map.guard.commands.powershell.read: a PowerShell stage as the bash read it equals, the filters after it, the line's asks and the line run in its place
// psBash: the bash words that read what a PowerShell stage reads (Select-String as grep, Get-Content as cat, head or tail,
// Get-ChildItem as ls or find), a posix command's own words with their paths in `/`; nil when it is no read.
func psBash(words []string) []string {
	canon := psCommand(words)
	if canon == "" {
		if !psPlainName.MatchString(baseName(words[0])) {
			return nil
		}
		out := []string{words[0]}
		for _, w := range words[1:] {
			out = append(out, psWord(w))
		}
		return out
	}
	named, pos := psArgs(canon, words)
	// the path: Python's `path or literalpath or the first word that is no parameter`
	path := func() psVal {
		for _, k := range []string{"path", "literalpath"} {
			if v := named[k]; v.truthy() {
				return v
			}
		}
		if len(pos) > 0 {
			return psVal{s: pos[0], str: true}
		}
		return psVal{}
	}
	switch canon {
	case "select-string":
		pattern, hasPattern := "", false
		if v, ok := named["pattern"]; ok {
			pattern, hasPattern = v.s, true
		}
		if !hasPattern && len(pos) > 0 {
			pattern, hasPattern, pos = pos[0], true, pos[1:]
		}
		if !hasPattern || named["quiet"].truthy() {
			return nil
		}
		out := []string{"grep"}
		if !named["casesensitive"].truthy() {
			out = append(out, "-i")
		}
		if named["simplematch"].truthy() {
			out = append(out, "-F")
		}
		if named["notmatch"].truthy() {
			out = append(out, "-v")
		}
		out = append(out, "-e", pattern)
		for _, g := range psList(named["include"]) {
			out = append(out, "--include="+g)
		}
		return append(out, psList(path())...)
	case "get-content":
		files := psList(path())
		for _, t := range []struct {
			tool string
			keys []string
		}{{"head", []string{"totalcount", "head", "first"}}, {"tail", []string{"tail", "last"}}} {
			for _, k := range t.keys {
				if v, ok := named[k]; ok {
					if v.str && psIsDigits(v.s) {
						return append([]string{t.tool, "-n", v.s}, files...)
					}
					break
				}
			}
		}
		return append([]string{"cat"}, files...)
	}
	place := "."
	if l := psList(path()); len(l) > 0 {
		place = l[0]
	}
	glob := ""
	if f := named["filter"]; f.truthy() {
		glob = f.s
	} else if l := psList(named["include"]); len(l) > 0 {
		glob = l[0]
	}
	if named["directory"].truthy() || named["ad"].truthy() {
		return nil
	}
	if named["recurse"].truthy() || named["r"].truthy() || glob != "" {
		out := []string{"find", place}
		if glob != "" {
			out = append(out, "-name", glob)
		}
		return out
	}
	return []string{"ls", place}
}

// psFilter: a stage after the first as the bash filter it equals (no words, with ok, when it only shows what it is fed); ok false
// when it is anything else.
func psFilter(words []string) ([]string, bool) {
	name := strings.ToLower(baseName(words[0]))
	if psIdentity[name] {
		return nil, true
	}
	if name == "measure-object" || name == "measure" {
		return []string{"wc", "-l"}, true
	}
	if name == "select-string" || name == "sls" {
		b := psBash(words)
		return b, b != nil
	}
	if name == "select-object" || name == "select" {
		if len(words) == 3 && psFirstLast.MatchString(words[1]) && psIsDigits(words[2]) {
			tool := "tail"
			if strings.ToLower(words[1]) == "-first" {
				tool = "head"
			}
			return []string{tool, "-n", words[2]}, true
		}
		return nil, false
	}
	b := psBash(words)
	if len(b) > 0 && FILTERS[baseName(b[0])] {
		return b, true
	}
	return nil, false
}

// psRead: (question, exact) for a pipeline of PowerShell stages that reads the code or the docs; exact: nothing is left after the
// ask (a stage that is none of the equals above, or a filter the ask keeps, could not be run for it). found is false for a count
// or anything else.
func psRead(stages [][]string, base string) (q []string, exact, found bool) {
	for _, st := range stages {
		for _, w := range st {
			if psCount.MatchString(w) {
				return nil, false, false // (Get-Content f).Count: a count
			}
		}
	}
	first := psBash(stages[0])
	if len(first) == 0 {
		return nil, false, false
	}
	var filters [][]string
	exact = true
	for _, st := range stages[1:] {
		f, ok := psFilter(st)
		if !ok {
			exact = false
			break
		}
		if len(f) > 0 {
			filters = append(filters, f)
		}
	}
	if (first[0] == "find" || first[0] == "ls") && !exact {
		return nil, false, false // a listing computed over: names, dates, sizes
	}
	if counts(filters) {
		return nil, false, false
	}
	if first[0] == "find" && len(filters) > 0 && filters[0][0] == "grep" {
		if _, p, _, _ := grepParts(filters[0]); len(p) == 0 { // Select-String reads the files Get-ChildItem lists
			pattern := "*"
			for j, a := range first {
				if a == "-name" && j+1 < len(first) {
					pattern = first[j+1]
					break
				}
			}
			q = GrepQuestion(append(append([]string{}, filters[0]...), "-r", first[1], "--include="+pattern), base)
			if len(q) == 0 {
				return nil, false, false
			}
			ex := exact
			for _, f := range filters[1:] {
				if b := baseName(f[0]); b != "head" && b != "tail" {
					ex = false
				}
			}
			return q, ex, true
		}
	}
	q, kept := folded(first, base, filters)
	if len(q) == 0 {
		return nil, false, false
	}
	return q, exact && len(kept) == 0, true
}

// psPlan: (asks, pure, ok): each read of the code or the docs in a PowerShell line as the words of its ask, and whether the line is
// those reads only (a cd followed); ok is false when the line writes.
func psPlan(line, cwd string) ([][]string, bool, bool) {
	statements, writes_ := psStatements(line)
	if writes_ {
		return nil, false, false
	}
	base, pure := cwd, true
	var asks [][]string
	for _, stages := range statements {
		first := stages[0]
		if psCD[strings.ToLower(baseName(first[0]))] && len(first) == 2 && len(stages) == 1 && !strings.Contains(first[1], "$") {
			base = joinPath(base, psPath(first[1]))
			continue
		}
		if q, exact, found := psRead(stages, base); found {
			asks = append(asks, q)
			pure = pure && exact
		} else {
			pure = false
		}
	}
	for _, m := range psFileRead.FindAllStringSubmatch(line, -1) {
		lit := m[1]
		if lit == "" {
			lit = m[2]
		}
		rel, ok := Inside(psPath(lit), cwd)
		if Mapped(rel, ok, false) {
			asks = append(asks, []string{rel})
			pure = false
		}
	}
	return asks, pure, true
}

// psQuestion: the ask replacing a PowerShell line, or "" when it may go ahead.
func psQuestion(line, cwd string) string {
	asks, _, ok := psPlan(line, cwd)
	if !ok || len(asks) == 0 {
		return ""
	}
	var all []string
	for _, a := range asks {
		all = append(all, a...)
	}
	return ASK + psQuote(all)
}

// psRewrite: the PowerShell line run in its place, each read as its ask, from the root; "" when a step is more than a read.
func psRewrite(line, cwd string) string {
	asks, pure, ok := psPlan(line, cwd)
	if !ok || len(asks) == 0 || !pure {
		return ""
	}
	var parts []string
	for _, q := range asks {
		parts = append(parts, ASK+psQuote(q))
	}
	text := strings.Join(parts, "; ")
	if realpath(cwd) == realpath(ROOT) {
		return text
	}
	return "Push-Location -LiteralPath " + psQuoteWord(strings.ReplaceAll(ROOT, `\`, "/")) + "; try { " + text + " } finally { Pop-Location }"
}

// @end map.guard.commands.powershell.read
// @end map.guard.commands.powershell

// @map map.guard.decide: each agent's input read into one shape, the ask that replaces the call, and the answer in the agent's format
// @map map.guard.decide.question: the map question of a command and of a whole shell line, with the filters and counts that go with it
func question(words []string, base string) []string {
	tool := filepath.Base(words[0])
	switch {
	case tool == "git" && func() bool { _, _, ok := gitGrep(words, base); return ok }():
		gw, gb, _ := gitGrep(words, base)
		return grepQuestion(gw, gb, true)
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

// counts: whether a run of filters counts what it is fed: wc, or grep -c.
func counts(pipe [][]string) bool {
	for _, w := range pipe {
		tool := filepath.Base(w[0])
		if tool == "wc" {
			return true
		}
		if tool == "grep" || tool == "egrep" || tool == "fgrep" {
			_, _, _, flags := grepParts(w)
			if flags["c"] || flags["--count"] {
				return true
			}
		}
	}
	return false
}

func ShellQuestion(line, cwd string) string {
	first := strings.SplitN(line, "\n", 2)[0]
	if strings.Contains(line, "map.py") || strings.Contains(line, "map.mjs") || (strings.HasPrefix(ASK, "map ") && strings.Contains(" "+first+" ", " map ")) {
		return ""
	}
	if lineWrites(line, cwd) { // an edit: the reads beside it check it
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
		xargs := c.words[0] == "find" && after != nil && after.piped && len(after.words) > 1 && after.words[0] == "xargs" && SEARCH[filepath.Base(after.words[1])]
		if xargs {
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
		var pipe []command
		for _, w := range parts[k+1:] {
			if !w.piped || !FILTERS[filepath.Base(w.words[0])] {
				break
			}
			pipe = append(pipe, w)
		}
		var run [][]string
		for _, w := range pipe {
			run = append(run, w.words)
		}
		if counts(run) {
			continue // a count: nothing of the files is read
		}
		if !xargs {
			var kept map[int]bool
			q, kept = folded(c.words, c.base, run)
			var left []command
			for i, w := range pipe {
				if kept[i] {
					left = append(left, w)
				}
			}
			pipe = left
		}
		var qs []string
		if FILE_FILTERS[filepath.Base(c.words[0])] != "" { // cut -c1-9 file: the ask, then cut
			if keep, _, ok := fileFilter(c.words); ok {
				qs = append(qs, Quote(keep))
			}
		}
		for _, w := range pipe {
			qs = append(qs, Quote(w.words))
		}
		if len(qs) > 0 {
			filtered = append(filtered, ASK+Quote(q)+" | "+strings.Join(qs, " | "))
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

// @end map.guard.decide.question

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
		kind := map[string]string{"bash": "shell", "powershell": "powershell", "view": "read", "grep": "grep", "glob": "glob"}[name]
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
	kind := map[string]string{"Bash": "shell", "PowerShell": "powershell", "Read": "read", "Grep": "grep", "Glob": "glob"}[str(data["tool_name"])]
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

// @map map.guard.decide.glob: the ask for a Glob, only when the map holds a file the pattern names (never an ask that answers 0 files)
var globWild = regexp.MustCompile(`[*?[{]`)
var globStar = regexp.MustCompile(`[*?]`)
var globRegex = regexp.MustCompile(`[\\|()+^$]`)
var driveRx = regexp.MustCompile(`^[A-Za-z]:$`)

const globSeen = 50000 // files looked at for a match; past them the call goes ahead

// globQuestion: the ask for a Glob, or "" when it goes ahead, as a Grep, a Read or a shell line on the same place does.
// The pattern is split at its first wildcard segment (* ? [ {): the literal folder before it, under the tool's folder,
// must be a place the map reads (inside the repository, not ignored, not the map's own), and the pattern, matched as
// ask matches it (Fnmatch on the path less its leading . and /), must name a file the map reads there. A pattern with
// no wildcard is that file or folder.
func globQuestion(folder, pattern, cwd string) string {
	pat := expanduser(pattern)
	if runtime.GOOS == "windows" {
		pat = strings.ReplaceAll(pat, `\`, "/") // a Windows pattern may use either separator
	}
	parts := strings.Split(pat, "/")
	k := len(parts)
	for i, s := range parts {
		if globWild.MatchString(s) {
			k = i
			break
		}
	}
	lit := strings.Join(parts[:k], "/")
	if lit == "" && strings.HasPrefix(pat, "/") {
		lit = "/"
	}
	if driveRx.MatchString(lit) {
		lit += "/"
	}
	rel, ok := Inside(joinPath(folder, lit), cwd)
	if !ok {
		return ""
	}
	rest := strings.Join(parts[k:], "/")
	if rest == "" {
		if Mapped(rel, true, true) && rel != "." {
			return ASK + Quote([]string{rel})
		}
		return ""
	}
	q := rel + "/" + rest
	if rel == "." {
		q = rest
	}
	if !Mapped(rel, true, true) || !strings.Contains(q, "/") || !globStar.MatchString(q) || globRegex.MatchString(q) {
		return "" // ignored, or a pattern that ask does not read as a glob
	}
	want := strings.TrimLeft(q, "./")
	if found, _ := walkFiles(rel, globSeen, func(sub string) bool { return Fnmatch(sub, want) && Mapped(sub, true, false) }); found {
		return ASK + Quote([]string{q})
	}
	return ""
}

// @end map.guard.decide.glob

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
	case "powershell":
		cmd := str(given["command"])
		if cmd == "" {
			cmd = str(given["cmd"])
		}
		return psQuestion(cmd, cwd)
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
		return globQuestion(folderOf(given), str(given["pattern"]), cwd)
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

// subagent: whether the call comes from a subagent: Claude Code adds `agent_id` (and `agent_type`, also given to a session started
// with --agent) to the hook input of a subagent's tool calls.
func subagent(data map[string]any) bool {
	return truthy(data["agent_id"]) || truthy(data["agentId"])
}

// Decide: the hook's answer for this call, or nil when it goes ahead: in Claude Code a shell line of reads only runs
// through the map in its place; any other read of the code or the docs is refused with its ask.
func Decide(agent string, data map[string]any) map[string]any {
	asked := Replacement(agent, data)
	if asked == "" {
		return nil
	}
	kind, given, cwd := normalise(agent, data)
	line := ""
	runs := agent == "claude" && !(subagent(data) && SUBAGENTS == "deny") // a subagent is denied its read line, with the ask, to learn it
	if runs && kind == "shell" {
		line = rewrite(str(given["command"]), cwd)
	} else if runs && kind == "powershell" {
		line = psRewrite(str(given["command"]), cwd)
	}
	if line != "" {
		in := map[string]any{}
		for k, v := range given {
			in[k] = v
		}
		in["command"] = line
		return map[string]any{"hookSpecificOutput": map[string]any{"hookEventName": "PreToolUse", "permissionDecision": "allow",
			"permissionDecisionReason": "map-guard: read through the map", "updatedInput": in, "additionalContext": NOTE + line}}
	}
	again := ""
	if kind == "shell" {
		again = resend(str(given["command"]), cwd)
	}
	return Answer(agent, asked, again)
}

// Answer: the refusal: the asks, or, for a line of reads beside other steps, the whole line to send again.
func Answer(agent, asked, again string) map[string]any {
	reason := REASON + asked
	if again != "" {
		reason, asked = REASON_LINE+again, again
	}
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

// winExe: the guard's path with the `.exe` Windows gives the file back, for PowerShell, which needs the extension;
// the other hooks name it without it (Git Bash finds the .exe, and the same settings run on macOS and Linux).
func winExe(me string) string {
	if strings.HasSuffix(strings.ToLower(me), ".exe") {
		return me
	}
	return me + ".exe"
}

type setting struct {
	path string
	make func(me string) map[string]any
}

var settings = map[string]setting{
	"claude": {".claude/settings.json", func(me string) map[string]any {
		return map[string]any{"hooks": map[string]any{"PreToolUse": []any{map[string]any{"matcher": "Bash|PowerShell|Read|Grep|Glob", "hooks": []any{map[string]any{"type": "command", "command": `"$CLAUDE_PROJECT_DIR/` + me + `"`}}}}}}
	}},
	"codex": {".codex/hooks.json", func(me string) map[string]any {
		return map[string]any{"hooks": map[string]any{"PreToolUse": []any{map[string]any{"matcher": "Bash", "hooks": []any{map[string]any{"type": "command", "command": `"$(git rev-parse --show-toplevel)/` + me + `" --agent codex`, "statusMessage": "map-guard"}}}}}}
	}},
	"cursor": {".cursor/hooks.json", func(me string) map[string]any {
		return map[string]any{"version": 1, "hooks": map[string]any{"beforeShellExecution": []any{map[string]any{"command": me + " --agent cursor"}}, "beforeReadFile": []any{map[string]any{"command": me + " --agent cursor"}}}}
	}},
	"copilot": {".github/hooks/map-guard.json", func(me string) map[string]any {
		hook := map[string]any{"type": "command", "bash": me + " --agent copilot", "cwd": ".", "timeoutSec": 10}
		if runtime.GOOS == "windows" { // PowerShell runs the .exe itself, from the root (`./` unless the path is a full one)
			ps := winExe(me)
			if !filepath.IsAbs(ps) {
				ps = "./" + ps
			}
			hook["powershell"] = ps + " --agent copilot"
		}
		return map[string]any{"version": 1, "hooks": map[string]any{"preToolUse": []any{hook}}}
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
	if runtime.GOOS == "windows" && strings.HasSuffix(strings.ToLower(me), ".exe") {
		me = me[:len(me)-len(".exe")] // the hook command runs in bash, which finds map-guard.exe by this name
	}
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

// safeDecide: Decide, where a failure lets the call go ahead (as the reference's catch-all does).
func safeDecide(agent string, data map[string]any) (out map[string]any) {
	defer func() {
		if recover() != nil {
			out = nil
		}
	}()
	return Decide(agent, data)
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
			if line := rewrite(argv[1], cwd); line != "" {
				fmt.Println("Claude Code runs in its place: " + line)
			} else if again := resend(argv[1], cwd); again != "" {
				fmt.Println("Send instead: " + again)
			}
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
	if out := safeDecide(agent, data); out != nil {
		fmt.Println(JSON(out, ""))
	}
}

var _ = utf8.RuneLen

// @end map.guard.decide
