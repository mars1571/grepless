// @map map.ask.repo: what ask reads (the tagged code and the repository's text), and the block or section holding a line
package mapcore

import (
	"bufio"
	"bytes"
	"fmt"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

const (
	MANY  = 120
	SMALL = 150
	LONG  = 80
	CUT   = 240
	FEW   = 12
)

// Flags of the call: --json prints one JSON document, --literal searches every question as plain text.
var (
	JSONMode    bool
	LiteralMode bool
	record      = map[string][]any{}
)

// Rec keeps one structured fact of the answer being built (only with --json).
func Rec(kind string, v any) {
	if JSONMode {
		record[kind] = append(record[kind], v)
	}
}

func recList(kind string) []any {
	if l := record[kind]; l != nil {
		return l
	}
	return []any{}
}

func blockJSON(b *Block) *OMap {
	return Obj("id", b.ID, "file", b.Path, "first", b.First, "last", b.Last, "purpose", b.Purpose)
}

// PrintJSON writes one compact JSON document and a newline.
func PrintJSON(doc any) { Print(Jcompact(doc)) }

type Section struct {
	First, Last, Level int
	Title              string
}

type DeclAt struct {
	Path        string
	First, Last int
	What, Line  string
}

type Repo struct {
	Blocks   []*Block
	Files    []string
	ByFile   map[string][]*Block
	text     map[string][]string
	sections map[string][]Section
	decls    map[string][]DeclAt
	declsOK  bool
}

func NewRepo(blocks []*Block) *Repo {
	if blocks == nil {
		blocks, _, _ = Everything()
	}
	r := &Repo{Blocks: blocks, ByFile: map[string][]*Block{}, text: map[string][]string{}, sections: map[string][]Section{}}
	for _, p := range RepoFiles() {
		if (TEXT[strings.ToLower(Suffix(p))] || Forms(p) != nil) && !BINARY.MatchString(p) {
			r.Files = append(r.Files, p)
		}
	}
	for _, b := range blocks {
		r.ByFile[b.Path] = append(r.ByFile[b.Path], b)
	}
	return r
}

func (r *Repo) Lines(p string) []string {
	if l, ok := r.text[p]; ok {
		return l
	}
	lines := strings.Split(ReadFile(p), "\n")
	if len(lines) > 1 && lines[len(lines)-1] == "" {
		lines = lines[:len(lines)-1]
	}
	r.text[p] = lines
	return lines
}

func (r *Repo) Holder(p string, n int) *Block {
	var best *Block
	for _, b := range r.ByFile[p] {
		if b.First <= n && n <= b.Last {
			if best == nil || b.First > best.First || (b.First == best.First && b.Last < best.Last) {
				best = b
			}
		}
	}
	return best
}

func (r *Repo) Sections(p string) []Section {
	if s, ok := r.sections[p]; ok {
		return s
	}
	type head struct {
		line, level int
		title       string
	}
	var heads []head
	fence := false
	for k, line := range r.Lines(p) {
		if strings.HasPrefix(line, "```") {
			fence = !fence
		} else if !fence {
			if m := headingRx.FindStringSubmatch(line); m != nil {
				heads = append(heads, head{k + 1, len(m[1]), strings.TrimSpace(m[2])})
			}
		}
	}
	var out []Section
	for k, h := range heads {
		last := len(r.Lines(p))
		for _, nx := range heads[k+1:] {
			if nx.level <= h.level {
				last = nx.line - 1
				break
			}
		}
		out = append(out, Section{h.line, last, h.level, h.title})
	}
	r.sections[p] = out
	return out
}

func (r *Repo) SectionAt(p string, n int) *Section {
	var best *Section
	secs := r.Sections(p)
	for i := range secs {
		s := &secs[i]
		if s.First <= n && n <= s.Last && (best == nil || s.First > best.First) {
			best = s
		}
	}
	return best
}

func (r *Repo) Decls() map[string][]DeclAt {
	if r.declsOK {
		return r.decls
	}
	r.decls = map[string][]DeclAt{}
	for _, p := range Files() {
		for _, d := range FactsOf(p).Decls {
			if d.Kind != "heading" {
				r.decls[d.Name] = append(r.decls[d.Name], DeclAt{p, d.First, d.Last, d.Kind + " " + d.Name, d.What})
			}
		}
	}
	r.declsOK = true
	return r.decls
}

func (r *Repo) Where(p string, a, b int) string {
	if DOCS[strings.ToLower(Suffix(p))] {
		if s := r.SectionAt(p, a); s != nil {
			return strings.Repeat("#", s.Level) + " " + s.Title
		}
		return ""
	}
	if b == 0 {
		b = a
	}
	var ids []string
	seen := map[string]bool{}
	for n := a; n <= b; n++ {
		if h := r.Holder(p, n); h != nil && !seen[h.ID] {
			seen[h.ID] = true
			ids = append(ids, h.ID)
		}
	}
	shown := ids
	if len(shown) > 4 {
		shown = shown[:4]
	}
	s := strings.Join(shown, ", ")
	if len(ids) > 4 {
		s += fmt.Sprintf(" (+%d)", len(ids)-4)
	}
	return s
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

func Relative(q string) (string, bool) {
	r := ROOT
	var under bool
	if runtime.GOOS == "windows" { // a path is written with `\` or `/`, the drive letter in either case, or as Git Bash's /c/...
		r = strings.ReplaceAll(r, `\`, "/")
		if m, ok := msysPath(q); ok {
			q = m
		}
		q = strings.ReplaceAll(q, `\`, "/")
		under = len(q) > len(r) && q[len(r)] == '/' && strings.EqualFold(q[:len(r)], r)
	} else {
		under = strings.HasPrefix(q, r+"/")
	}
	p := q
	if under {
		p = q[len(r)+1:]
	}
	p = strings.TrimPrefix(p, "./")
	p = strings.TrimRight(p, "/")
	if p == "" {
		p = "."
	}
	if Exists(p) && !strings.HasPrefix(p, "..") {
		return p, true
	}
	return "", false
}

func Within(p string, places []string) bool {
	if len(places) == 0 {
		return true
	}
	for _, q := range places {
		if p == q || strings.HasPrefix(p, strings.TrimRight(q, "/")+"/") || Fnmatch(p, q) {
			return true
		}
	}
	return false
}

func put(lines []string, a, b int) {
	for i := a; i <= b; i++ {
		Printf("%d\t%s", i, lines[i-1])
	}
}

var wordRx = regexp.MustCompile(`^[A-Za-z_$][\w$]*$`)
var commentLead = regexp.MustCompile(`^\s*(#|//|\*)`)

// Declarations: where word is declared, as the files' shapes show it; else the values assigned to it.
func Declarations(repo *Repo, word string) []DeclAt {
	out := append([]DeclAt{}, repo.Decls()[word]...)
	if len(out) == 0 && wordRx.MatchString(word) {
		rx := regexp.MustCompile(`(?:\b(?:const|let|var|val|final|static|export)\s+|^\s*)` + regexp.QuoteMeta(word) + `\s*[:=]`)
		for _, p := range Files() {
			lines := repo.Lines(p)
			if !strings.Contains(strings.Join(lines, "\n"), word) {
				continue
			}
			for k, line := range lines {
				if len(out) >= 6 || commentLead.MatchString(line) {
					continue
				}
				loc := rx.FindStringIndex(line)
				if loc != nil && !(loc[1] < len(line) && (line[loc[1]] == '=' || line[loc[1]] == '>')) {
					out = append(out, DeclAt{p, k + 1, k + 1, "value " + word, cut(strings.TrimSpace(line), 120)})
				}
			}
		}
	}
	return out
}

// @end map.ask.repo

// @map map.ask.answer: each kind of question answered whole, and the command reading a call's questions
type Hit struct {
	Path string
	Line int
	Text string
}

type skipRange struct {
	path string
	a, b int
}

func skipped(skip []skipRange, p string, n int) bool {
	for _, s := range skip {
		if s.path == p && s.a <= n && n <= s.b {
			return true
		}
	}
	return false
}

func Search(repo *Repo, rx *regexp.Regexp, places []string, skip []skipRange) []Hit {
	var hits []Hit
	for _, p := range repo.Files {
		if !Within(p, places) || SizeOf(p) > LARGE {
			continue
		}
		lines := repo.Lines(p)
		if !rx.MatchString(strings.Join(lines, "\n")) {
			continue
		}
		for k, line := range lines {
			if rx.MatchString(line) && !skipped(skip, p, k+1) {
				hits = append(hits, Hit{p, k + 1, line})
			}
		}
	}
	return hits
}

func SearchWord(repo *Repo, word string, places []string, skip []skipRange, hyphen bool) []Hit {
	edge := ""
	if hyphen {
		edge = "-"
	}
	var hits []Hit
	for _, p := range repo.Files {
		if !Within(p, places) || SizeOf(p) > LARGE {
			continue
		}
		lines := repo.Lines(p)
		if !strings.Contains(strings.Join(lines, "\n"), word) {
			continue
		}
		for k, line := range lines {
			if strings.Contains(line, word) && Bounded(line, word, edge, edge) && !skipped(skip, p, k+1) {
				hits = append(hits, Hit{p, k + 1, line})
			}
		}
	}
	return hits
}

func ShowHits(repo *Repo, hits []Hit, every, numbers bool) {
	type place struct {
		label string
		found []Hit
	}
	var order []string
	places := map[string]*place{}
	for _, h := range hits {
		var key, label string
		var block any
		if b := repo.Holder(h.Path, h.Line); b != nil {
			block = b.ID
		}
		Rec("hits", Obj("file", h.Path, "line", h.Line, "text", h.Text, "block", block))
		if b := repo.Holder(h.Path, h.Line); b != nil {
			key = fmt.Sprintf("%s\x00%s\x00%d", h.Path, b.ID, b.First)
			label = fmt.Sprintf("%s  %s:%d-%d  %s", b.ID, h.Path, b.First, b.Last, Short(b.Purpose, 110))
		} else if s := (*Section)(nil); DOCS[strings.ToLower(Suffix(h.Path))] && func() bool { s = repo.SectionAt(h.Path, h.Line); return s != nil }() {
			key = fmt.Sprintf("%s\x00%d", h.Path, s.First)
			label = fmt.Sprintf("%s:%d-%d  %s %s", h.Path, s.First, s.Last, strings.Repeat("#", s.Level), s.Title)
		} else {
			key, label = h.Path, h.Path
		}
		pl, ok := places[key]
		if !ok {
			pl = &place{label: label}
			places[key] = pl
			order = append(order, key)
		}
		pl.found = append(pl.found, h)
	}
	if len(hits) > MANY && !every {
		Printf("  %d lines in %d places; the places (their lines: --all, or --in <file, folder or glob>)", len(hits), len(places))
		shown := order
		if len(shown) > 60 {
			shown = shown[:60]
		}
		for _, k := range shown {
			Printf("    %s  (%d lines)", places[k].label, len(places[k].found))
		}
		if len(order) > 60 {
			Printf("    … %d more places", len(order)-60)
		}
		return
	}
	for _, k := range order {
		pl := places[k]
		if numbers {
			var ns []string
			for _, h := range pl.found {
				ns = append(ns, fmt.Sprint(h.Line))
			}
			Printf("    %s: %s", pl.label, strings.Join(ns, ", "))
			continue
		}
		Print("  " + pl.label)
		for _, h := range pl.found {
			line := h.Text
			if r := []rune(line); len(r) > CUT {
				line = string(r[:CUT]) + fmt.Sprintf(" …(+%d)", len(r)-CUT)
			}
			Printf("%d\t%s", h.Line, line)
		}
	}
}

func answerLines(repo *Repo, p string, a, b int, ranged bool) {
	lines := repo.Lines(p)
	label := ""
	if held := repo.Holder(p, a); !ranged && held != nil {
		Rec("blocks", blockJSON(held))
	}
	if !ranged {
		h := repo.Holder(p, a)
		var s *Section
		if DOCS[strings.ToLower(Suffix(p))] {
			s = repo.SectionAt(p, a)
		}
		switch {
		case h != nil:
			a, b, label = h.First, h.Last, h.ID+": "+h.Purpose
		case s != nil:
			a, b, label = s.First, s.Last, strings.Repeat("#", s.Level)+" "+s.Title
		default:
			b = a + 15
			if a-15 > 1 {
				a = a - 15
			} else {
				a = 1
			}
		}
	} else {
		label = repo.Where(p, a, b)
	}
	if a < 1 {
		a = 1
	}
	if b > len(lines) {
		b = len(lines)
	}
	line := fmt.Sprintf("  %s:%d-%d", p, a, b)
	if label != "" {
		line += "  " + label
	}
	Print(line)
	put(lines, a, b)
}

func pyType(v any) string {
	switch x := v.(type) {
	case nil:
		return "NoneType"
	case bool:
		return "bool"
	case int64, int:
		return "int"
	case float64:
		return "float"
	case string:
		return "str"
	case []any:
		return "list"
	case *OMap:
		_ = x
		return "dict"
	}
	return "object"
}

// @map map.ask.answer.file: a file answered whole, by its outline, its sections, its keys or its declarations
func answerFile(repo *Repo, p string) {
	lines := repo.Lines(p)
	suffix := strings.ToLower(Suffix(p))
	switch {
	case SizeOf(p) > LARGE:
		Printf("  %s: %d lines, %s bytes: data, not printed (ask %s:<first>-<last>)", p, len(lines), Commas(SizeOf(p)), p)
	case len(lines) <= SMALL:
		Printf("  %s: %d lines, whole", p, len(lines))
		put(lines, 1, len(lines))
	case DOCS[suffix] && len(repo.Sections(p)) > 0:
		Printf("  %s: %d lines; its sections (one: ask %s#<words of its heading>)", p, len(lines), p)
		for _, s := range repo.Sections(p) {
			Printf("%s-%s%s%s %s", PadL(fmt.Sprint(s.First), 6), PadR(fmt.Sprint(s.Last), 6), strings.Repeat("  ", s.Level-1), strings.Repeat("#", s.Level), s.Title)
		}
	case suffix == ".json":
		data, err := ParseJSON(strings.Join(lines, "\n"))
		if m, ok := data.(*OMap); err == nil && ok {
			Printf("  %s: %d lines; its keys (one: ask %s#<key>)", p, len(lines), p)
			for _, k := range m.Keys {
				v := m.Vals[k]
				sub := ""
				if sm, ok := v.(*OMap); ok {
					keys := sm.Keys
					more := ""
					if len(keys) > 8 {
						keys = keys[:8]
						more = ", …"
					}
					sub = " {" + strings.Join(keys, ", ") + more + "}"
				}
				Printf("    %s: %s, %s characters%s", k, pyType(v), Commas(utf8.RuneCountInString(Jdump(v, 0, 0))), sub)
			}
		} else if arr, ok := data.([]any); err == nil && ok {
			Printf("  %s: %d lines; its keys (one: ask %s#<key>)", p, len(lines), p)
			for i, v := range arr {
				sub := ""
				if sm, ok := v.(*OMap); ok {
					keys := sm.Keys
					more := ""
					if len(keys) > 8 {
						keys = keys[:8]
						more = ", …"
					}
					sub = " {" + strings.Join(keys, ", ") + more + "}"
				}
				Printf("    %d: %s, %s characters%s", i, pyType(v), Commas(utf8.RuneCountInString(Jdump(v, 0, 0))), sub)
			}
		} else {
			Printf("  %s: %d lines; the first %d (more: ask %s:<first>-<last>)", p, len(lines), SMALL, p)
			put(lines, 1, SMALL)
		}
	case len(repo.ByFile[p]) > 0:
		named := map[string][]string{}
		if Forms(p) != nil {
			for _, d := range FactsOf(p).Decls {
				if d.Kind == "function" || d.Kind == "class" || d.Kind == "method" {
					if h := repo.Holder(p, d.First); h != nil {
						named[h.ID] = append(named[h.ID], d.Name)
					}
				}
			}
		}
		Printf("  %s: %d lines; its blocks (one: ask <id>, or %s:<first>-<last>)", p, len(lines), p)
		bs := append([]*Block{}, repo.ByFile[p]...)
		sort.SliceStable(bs, func(i, j int) bool {
			if bs[i].First != bs[j].First {
				return bs[i].First < bs[j].First
			}
			return bs[i].Last > bs[j].Last
		})
		var outer []int
		for _, b := range bs {
			for len(outer) > 0 && outer[len(outer)-1] < b.First {
				outer = outer[:len(outer)-1]
			}
			Rec("blocks", blockJSON(b))
			line := fmt.Sprintf("%s-%s%s%s  %s", PadL(fmt.Sprint(b.First), 6), PadR(fmt.Sprint(b.Last), 6), strings.Repeat("  ", len(outer)), b.ID, Short(b.Purpose, 110))
			if ns := named[b.ID]; len(ns) > 0 {
				shown := ns
				more := ""
				if len(shown) > 8 {
					shown = shown[:8]
					more = " …"
				}
				line += "  [" + strings.Join(shown, ", ") + more + "]"
			}
			Print(line)
			outer = append(outer, b.Last)
		}
	case Forms(p) != nil && hasCodeDecls(FactsOf(p).Decls):
		decls := FactsOf(p).Decls
		Printf("  %s: %d lines, no tags yet; what it declares (one: ask <name>, or %s:<first>-<last>)", p, len(lines), p)
		shown := decls
		if len(shown) > 80 {
			shown = shown[:80]
		}
		for _, d := range shown {
			Printf("%s-%s%s %s  %s", PadL(fmt.Sprint(d.First), 6), PadR(fmt.Sprint(d.Last), 6), d.Kind, d.Name, Short(d.What, 90))
		}
		if len(decls) > 80 {
			Printf("    … %d more", len(decls)-80)
		}
	default:
		Printf("  %s: %d lines; the first %d (more: ask %s:<first>-<last>)", p, len(lines), SMALL, p)
		put(lines, 1, SMALL)
	}
}

func hasCodeDecls(ds []Decl) bool {
	for _, d := range ds {
		if d.Kind != "heading" {
			return true
		}
	}
	return false
}

// @end map.ask.answer.file

func answerFiles(repo *Repo, paths []string, about string) {
	Printf("  %s: %d files", about, len(paths))
	for _, p := range paths {
		what := ""
		var first *Block
		for _, b := range repo.ByFile[p] {
			if first == nil || b.First < first.First {
				first = b
			}
		}
		if first != nil {
			what = Short(first.Purpose, 90)
		} else if DOCS[strings.ToLower(Suffix(p))] {
			if secs := repo.Sections(p); len(secs) > 0 {
				what = secs[0].Title
			}
		}
		Rec("files", Obj("file", p, "lines", len(repo.Lines(p)), "what", what))
		Printf("    %s  (%d lines)  %s", p, len(repo.Lines(p)), what)
	}
}

func answerFolder(repo *Repo, p string) {
	base := ""
	if p != "." {
		base = strings.TrimRight(p, "/") + "/"
	}
	var here []string
	folders := map[string]int{}
	for _, x := range repo.Files {
		if !strings.HasPrefix(x, base) {
			continue
		}
		rest := x[len(base):]
		if i := strings.Index(rest, "/"); i >= 0 {
			folders[rest[:i]]++
		} else {
			here = append(here, x)
		}
	}
	answerFiles(repo, here, p)
	for _, f := range sortedIntKeys(folders) {
		Printf("    %s%s/  (%d files)", base, f, folders[f])
	}
}

func sortedIntKeys(m map[string]int) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func wordsMatch(text string, ws []string) bool {
	toks := LowerWords(text)
	for _, w := range ws {
		ok := false
		for _, t := range toks {
			if strings.HasPrefix(t, w) {
				ok = true
				break
			}
		}
		if !ok {
			return false
		}
	}
	return true
}

func answerPart(repo *Repo, p, words string) bool {
	ws := LowerWords(words)
	if strings.HasSuffix(p, ".json") {
		data, err := ParseJSON(strings.Join(repo.Lines(p), "\n"))
		if err != nil {
			return false
		}
		for _, k := range strings.Split(words, ".") {
			switch v := data.(type) {
			case []any:
				i := 0
				if _, err := fmt.Sscanf(k, "%d", &i); err != nil || i < 0 || i >= len(v) || fmt.Sprint(i) != k {
					return false
				}
				data = v[i]
			case *OMap:
				nv, ok := v.Vals[k]
				if !ok {
					return false
				}
				data = nv
			default:
				return false
			}
		}
		Printf("  %s#%s", p, words)
		Print(Jdump(data, 1, 0))
		return true
	}
	if DOCS[strings.ToLower(Suffix(p))] {
		found := false
		for _, s := range repo.Sections(p) {
			if wordsMatch(s.Title, ws) {
				found = true
				Printf("  %s:%d-%d  %s %s", p, s.First, s.Last, strings.Repeat("#", s.Level), s.Title)
				put(repo.Lines(p), s.First, s.Last)
			}
		}
		return found
	}
	found := false
	for _, b := range repo.ByFile[p] {
		if wordsMatch(b.ID+" "+b.Purpose, ws) {
			found = true
			Rec("blocks", blockJSON(b))
			Printf("  %s:%d-%d  %s: %s", p, b.First, b.Last, b.ID, b.Purpose)
			put(repo.Lines(p), b.First, b.Last)
		}
	}
	return found
}

func answerBlock(repo *Repo, q string) {
	var exact, inside []*Block
	for _, b := range repo.Blocks {
		if b.ID == q {
			exact = append(exact, b)
		} else if strings.HasPrefix(b.ID, q+".") {
			inside = append(inside, b)
		}
	}
	switch {
	case len(exact) > 0:
		for _, b := range exact {
			var nested []*Block
			for _, x := range repo.ByFile[b.Path] {
				if x != b && b.First <= x.First && x.Last <= b.Last {
					nested = append(nested, x)
				}
			}
			Rec("blocks", blockJSON(b))
			Printf("  %s:%d-%d  %s: %s", b.Path, b.First, b.Last, b.ID, b.Purpose)
			if b.Last-b.First+1 > SMALL && len(nested) > 0 {
				Printf("  %d lines; the blocks inside it (one: ask <id>, or %s:<first>-<last>)", b.Last-b.First+1, b.Path)
				for _, x := range nested {
					Rec("blocks", blockJSON(x))
					Printf("%s-%s%s  %s", PadL(fmt.Sprint(x.First), 6), PadR(fmt.Sprint(x.Last), 6), x.ID, Short(x.Purpose, 110))
				}
			} else {
				put(repo.Lines(b.Path), b.First, b.Last)
			}
		}
	case len(inside) <= 60:
		Printf("  %d blocks under %s (one: ask <id>)", len(inside), q)
		for _, b := range inside {
			Rec("blocks", blockJSON(b))
			Printf("    %s %s:%d-%d  %s", PadR(b.ID, 44), b.Path, b.First, b.Last, Short(b.Purpose, 110))
		}
	default:
		var order []string
		parts := map[string][]*Block{}
		depth := len(strings.Split(q, ".")) + 1
		for _, b := range inside {
			segs := strings.Split(b.ID, ".")
			if len(segs) > depth {
				segs = segs[:depth]
			}
			k := strings.Join(segs, ".")
			if _, ok := parts[k]; !ok {
				order = append(order, k)
			}
			parts[k] = append(parts[k], b)
		}
		Printf("  %d blocks under %s, in %d parts (one: ask <id>)", len(inside), q, len(parts))
		for _, k := range order {
			bs := parts[k]
			paths := map[string]bool{}
			for _, b := range bs {
				paths[b.Path] = true
			}
			joined := strings.Join(SortedKeys(paths), ", ")
			if r := []rune(joined); len(r) > 80 {
				joined = string(r[:80])
			}
			Printf("    %s %s blocks  %s  %s", PadR(k, 40), PadL(fmt.Sprint(len(bs)), 3), joined, Short(bs[0].Purpose, 70))
		}
	}
}

// @map map.ask.answer.name: an identifier answered by its declarations and the lines naming it, and any other text searched as a pattern or, with --literal, as it is
func answerName(repo *Repo, q string, places []string, every bool) bool {
	word := q
	if !strings.HasPrefix(q, "--") {
		word = strings.TrimLeft(q, "#.")
	}
	var decls []DeclAt
	if wordRx.MatchString(word) {
		decls = Declarations(repo, word)
	}
	if len(decls) > 3 {
		Printf("  declared in %d places (the code of one: ask <file>:<first>-<last>)", len(decls))
	}
	for _, d := range decls {
		where := repo.Where(d.Path, d.First, 0)
		if where == "" {
			where = d.Path
		}
		Rec("declarations", Obj("what", d.What, "file", d.Path, "first", d.First, "last", d.Last))
		Printf("  %s: %s:%d-%d  in %s", d.What, d.Path, d.First, d.Last, where)
		if len(decls) <= 3 && d.Last-d.First < LONG {
			put(repo.Lines(d.Path), d.First, d.Last)
		} else if len(decls) <= 3 {
			put(repo.Lines(d.Path), d.First, d.First+11)
			Printf("  … %d more lines: ask %s:%d-%d", d.Last-d.First-11, d.Path, d.First+12, d.Last)
		}
	}
	first := firstRune(word)
	hyphen := strings.Contains(word, "-") || strings.HasPrefix(q, "--") || !isAlnumRune(first)
	var skip []skipRange
	for _, d := range decls {
		skip = append(skip, skipRange{d.Path, d.First, d.Last})
	}
	hits := SearchWord(repo, word, places, skip, hyphen)
	if len(hits) > 0 {
		if len(decls) > 0 {
			Printf("  named on %d other lines", len(hits))
		} else {
			Printf("  on %d lines", len(hits))
		}
		ShowHits(repo, hits, every, len(hits) > FEW && !every)
	}
	return len(decls) > 0 || len(hits) > 0
}

var declaredRx = regexp.MustCompile(`^\^?\s*(?:(?:export|async|static|pub|public|private)\s+)*(?:function\*?|def|fn|func|class|const|let|var|val)\s+([A-Za-z_$][\w$]*)\b.*$|^(?:global\.|window\.|\.)?([A-Za-z_$][\w$]*)\s*(?:\\?\(|=)\s*$`)
var altSplit = regexp.MustCompile(`\\\||\|`)

func NamesIn(q string) []string {
	var out []string
	for _, alt := range altSplit.Split(q, -1) {
		m := declaredRx.FindStringSubmatch(strings.TrimSpace(alt))
		if m == nil {
			return nil
		}
		if m[1] != "" {
			out = append(out, m[1])
		} else {
			out = append(out, m[2])
		}
	}
	return Unique(out)
}

func unescapedPipe(q string) bool {
	r := []rune(q)
	for i, c := range r {
		if c == '|' && (i == 0 || r[i-1] != '\\') {
			return true
		}
	}
	return false
}

func answerText(repo *Repo, q string, places []string, every bool) bool {
	if !LiteralMode && strings.Contains(q, `\|`) && !unescapedPipe(q) {
		q = strings.ReplaceAll(q, `\|`, "|")
	}
	rx := regexp.MustCompile(regexp.QuoteMeta(q))
	if !LiteralMode {
		if parsed, err := regexp.Compile(q); err == nil {
			rx = parsed
		}
	}
	hits := Search(repo, rx, places, nil)
	if len(hits) > 0 {
		ShowHits(repo, hits, every, false)
		return true
	}
	if !LiteralMode && strings.Contains(strings.TrimSpace(q), " ") {
		Print("  no line holds it; the blocks whose id, purpose or file have these words:")
		Find(strings.Fields(q))
		return true
	}
	return false
}

// @end map.ask.answer.name

var lineQ = regexp.MustCompile(`^(.+?):(\d+)(?:-(\d+))?$`)
var globQ = regexp.MustCompile(`[*?]`)
var regexQ = regexp.MustCompile(`[\\|()+^$]`)

func Ask(args []string) {
	every := false
	for _, a := range args {
		if a == "--all" {
			every = true
		}
	}
	type question struct {
		q      string
		places []string
	}
	var questions []question
	var waiting []string
	budget := CFG.Limits["answer"]
	for i := 0; i < len(args); i++ {
		if args[i] == "--budget" && i+1 < len(args) && allDigits(args[i+1]) {
			budget, _ = strconv.Atoi(args[i+1])
			i++
			continue
		}
		if args[i] == "--in" && i+1 < len(args) {
			var places []string
			for _, x := range strings.Split(args[i+1], ",") {
				if x == "" {
					continue
				}
				if rel, ok := Relative(x); ok {
					places = append(places, rel)
				} else {
					places = append(places, strings.TrimLeft(x, "./"))
				}
			}
			for _, q := range waiting {
				questions = append(questions, question{q, places})
			}
			waiting = nil
			i++
			continue
		}
		switch args[i] {
		case "--json":
			JSONMode = true
		case "--literal", "-F":
			LiteralMode = true
		case "--all":
		default:
			waiting = append(waiting, args[i])
		}
	}
	for _, q := range waiting {
		questions = append(questions, question{q, nil})
	}
	if len(questions) == 0 {
		Die(Usage())
	}
	repo := NewRepo(nil)
	ids := map[string]bool{}
	for _, b := range repo.Blocks {
		ids[b.ID] = true
	}
	var answers []asked
	var docs []any
	for _, qu := range questions {
		saved := out
		var buf bytes.Buffer
		out = bufio.NewWriterSize(&buf, 1<<16)
		record = map[string][]any{}
		answer(repo, ids, qu.q, qu.places, every)
		out.Flush()
		out = saved
		answers = append(answers, asked{qu.q, buf.String()})
		if JSONMode {
			docs = append(docs, Obj("question", qu.q, "blocks", recList("blocks"), "declarations", recList("declarations"),
				"files", recList("files"), "hits", recList("hits"),
				"found", !strings.Contains(buf.String(), "nothing in the code or the docs holds it"), "text", buf.String()))
		}
	}
	if JSONMode {
		PrintJSON(Obj("questions", docs))
		SaveCache()
		return
	}
	for _, t := range fit(answers, budget) {
		out.WriteString(t)
	}
	SaveCache()
}

type asked struct{ q, text string }

// answer: one question of a call, answered whole.
func answer(repo *Repo, ids map[string]bool, q string, places []string, every bool) {
	Print("== " + q)
	if LiteralMode {
		if !answerText(repo, q, places, every) {
			Print("  nothing in the code or the docs holds it")
		}
		return
	}
	if m := lineQ.FindStringSubmatch(q); m != nil {
		if p, ok := Relative(m[1]); ok && IsFile(p) {
			a, b := 0, 0
			fmt.Sscanf(m[2], "%d", &a)
			if m[3] != "" {
				fmt.Sscanf(m[3], "%d", &b)
				answerLines(repo, p, a, b, true)
			} else {
				answerLines(repo, p, a, 0, false)
			}
			return
		}
	}
	if i := strings.Index(q, "#"); i >= 0 {
		head, part := q[:i], q[i+1:]
		if part != "" && head != "" {
			if p, ok := Relative(head); ok && IsFile(p) {
				if !answerPart(repo, p, part) {
					Printf("  nothing in %s is called \"%s\"; its outline:", p, part)
					answerFile(repo, p)
				}
				return
			}
		}
	}
	p, ok := Relative(q)
	switch {
	case ok && IsFile(p):
		answerFile(repo, p)
	case ok && IsDir(p):
		answerFolder(repo, p)
	case globQ.MatchString(q) && strings.Contains(q, "/") && !regexQ.MatchString(q):
		pat := strings.TrimLeft(q, "./")
		var paths []string
		for _, x := range repo.Files {
			if Fnmatch(x, pat) {
				paths = append(paths, x)
			}
		}
		answerFiles(repo, paths, q)
	case len(NamesIn(q)) > 0:
		ns := NamesIn(q)
		for _, name := range ns {
			if len(ns) > 1 {
				Printf("  %s:", name)
			} else {
				Printf("  the name %s", name)
			}
			if !answerName(repo, name, places, every) {
				Print("  nothing in the code or the docs holds it")
			}
		}
	case ids[q] || prefixOf(ids, q+"."):
		answerBlock(repo, q)
	case (Identifier(q) || wordRx.MatchString(q)) && answerName(repo, q, places, every):
	case !answerText(repo, q, places, every):
		Print("  nothing in the code or the docs holds it")
	}
}

// @map map.ask.answer.fit: a call's answers kept within its budget of characters: the longest leave their code out, and say so
var codeLine = regexp.MustCompile(`^\d+\t`)

// fit: a call's answers within its budget of characters: while they run over it, the longest answer (the first of
// equals) keeps its places and leaves out its lines of code, and says so. One question is always answered whole.
func fit(answers []asked, budget int) []string {
	texts := make([]string, len(answers))
	total := 0
	for k, a := range answers {
		texts[k] = a.text
		total += utf8.RuneCountInString(a.text)
	}
	if budget <= 0 || len(texts) < 2 {
		return texts
	}
	order := make([]int, len(texts))
	for k := range order {
		order[k] = k
	}
	sort.SliceStable(order, func(i, j int) bool {
		return utf8.RuneCountInString(texts[order[i]]) > utf8.RuneCountInString(texts[order[j]])
	})
	for _, k := range order {
		if total <= budget {
			break
		}
		lines := strings.Split(strings.TrimRight(texts[k], "\n"), "\n")
		var kept []string
		for _, x := range lines {
			if !codeLine.MatchString(x) {
				kept = append(kept, x)
			}
		}
		if len(kept) == len(lines) {
			continue
		}
		short := strings.Join(append(kept, fmt.Sprintf("  \u2026 %d lines of code left out to keep this call under %s characters: ask %s in a call of its own", len(lines)-len(kept), Commas(budget), answers[k].q)), "\n") + "\n"
		total += utf8.RuneCountInString(short) - utf8.RuneCountInString(texts[k])
		texts[k] = short
	}
	return texts
}

// @end map.ask.answer.fit

func allDigits(s string) bool {
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

func prefixOf(ids map[string]bool, prefix string) bool {
	for id := range ids {
		if strings.HasPrefix(id, prefix) {
			return true
		}
	}
	return false
}

// @end map.ask.answer
