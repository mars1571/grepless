// @map map.code.imports: what each file imports, by language, resolved to the repository's own files
package mapcore

import (
	"regexp"
	"sort"
	"strings"
)

var IMPORT = map[string][]*regexp.Regexp{}
var IMPORT_LANG = map[string]string{}

func init() {
	for lang, rxs := range map[string][]string{
		"py":   {`^\s*from\s+([\w.]+)\s+import\b`, `^\s*import\s+([\w.]+(?:\s*,\s*[\w.]+)*)`},
		"js":   {`\bfrom\s+['"]([^'"]+)['"]`, `\brequire\(\s*['"]([^'"]+)['"]\s*\)`, `\bimport\(\s*['"]([^'"]+)['"]\s*\)`, `^\s*import\s+['"]([^'"]+)['"]`},
		"go":   {`^\s*import\s+(?:\w+\s+)?"([^"]+)"`, `^\s+(?:\w+\s+)?"([\w./-]+)"\s*$`},
		"rust": {`^\s*(?:pub\s+)?use\s+((?:crate|super|self)::[\w:]+)`, `^\s*(?:pub\s+)?mod\s+(\w+)\s*;`},
		"jvm":  {`^\s*import\s+(?:static\s+)?([\w.]+)`, `^\s*using\s+([\w.]+)\s*;`},
		"ruby": {`\brequire_relative\s+['"]([^'"]+)['"]`, `\brequire\s+['"]([^'"]+)['"]`},
		"php":  {`\b(?:require|include)(?:_once)?\s*\(?\s*(?:__DIR__\s*\.\s*)?['"]([^'"]+)['"]`, `^\s*use\s+([\w\\]+)`},
		"c":    {`^\s*#\s*include\s+"([^"]+)"`},
		"sh":   {`^\s*(?:source|\.)\s+([^\s;|&]+)`},
		"css":  {`@import\s+(?:url\()?['"]([^'"]+)['"]`, `@use\s+['"]([^'"]+)['"]`},
		"html": {`<script[^>]+src=["']([^"']+)["']`, `<link[^>]+href=["']([^"']+\.css)["']`},
	} {
		for _, r := range rxs {
			IMPORT[lang] = append(IMPORT[lang], regexp.MustCompile(r))
		}
	}
	for k, v := range LANG {
		IMPORT_LANG[k] = v
	}
	for k, v := range map[string]string{".css": "css", ".scss": "css", ".less": "css", ".html": "html", ".htm": "html", ".vue": "js", ".svelte": "js", ".astro": "js"} {
		IMPORT_LANG[k] = v
	}
}

var goImportOpen = regexp.MustCompile(`^\s*import\s*\(`)
var goImportLine = regexp.MustCompile(`^\s*import\b`)
var commaSplit = regexp.MustCompile(`\s*,\s*`)

// ImportsIn: the imports a file writes, as written, with their lines.
func ImportsIn(p, text string) []Import {
	lang := IMPORT_LANG[strings.ToLower(Suffix(p))]
	rs, ok := IMPORT[lang]
	if !ok {
		return nil
	}
	var out []Import
	inBlock := false
	for k, line := range strings.Split(text, "\n") {
		if lang == "go" {
			if goImportOpen.MatchString(line) {
				inBlock = true
				continue
			}
			if inBlock && strings.TrimSpace(line) == ")" {
				inBlock = false
				continue
			}
			if !inBlock && !goImportLine.MatchString(line) {
				continue
			}
		}
		for _, rx := range rs {
			for _, m := range rx.FindAllStringSubmatch(line, -1) {
				for _, one := range commaSplit.Split(m[1], -1) {
					out = append(out, Import{k + 1, strings.TrimSpace(one)})
				}
			}
		}
	}
	return out
}

// Normpath: a/./b/../c → a/c.
func Normpath(p string) string {
	var out []string
	for _, seg := range strings.Split(p, "/") {
		switch seg {
		case "", ".":
		case "..":
			if len(out) > 0 && out[len(out)-1] != ".." {
				out = out[:len(out)-1]
			} else {
				out = append(out, seg)
			}
		default:
			out = append(out, seg)
		}
	}
	if len(out) == 0 {
		return "."
	}
	return strings.Join(out, "/")
}

type Resolver struct {
	Paths    map[string]bool
	BySuffix map[string][]string
	Gomod    string
}

func NewResolver(paths []string) *Resolver {
	r := &Resolver{Paths: map[string]bool{}, BySuffix: map[string][]string{}}
	for _, p := range paths {
		r.Paths[p] = true
		parts := strings.Split(p, "/")
		max := len(parts)
		if max > 4 {
			max = 4
		}
		for k := 1; k <= max; k++ {
			key := strings.Join(parts[len(parts)-k:], "/")
			r.BySuffix[key] = append(r.BySuffix[key], p)
		}
	}
	if IsFile("go.mod") {
		if m := regexp.MustCompile(`(?m)^module\s+(\S+)`).FindStringSubmatch(ReadFile("go.mod")); m != nil {
			r.Gomod = m[1]
		}
	}
	return r
}

func (r *Resolver) file(p string) (string, bool) {
	q := Normpath(p)
	return q, r.Paths[q]
}

func candidates(base string, exts []string) []string {
	var out []string
	for _, e := range exts {
		out = append(out, base+e)
	}
	for _, e := range exts {
		out = append(out, base+"/index"+e, base+"/__init__"+e, base+"/mod"+e)
	}
	return out
}

var extsOf = map[string][]string{"js": {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".mts", ".cts", ".vue", ".svelte"}, "py": {".py"}, "ruby": {".rb"},
	"rust": {".rs"}, "css": {".css", ".scss", ".less"}, "go": {".go"}, "jvm": {".java", ".kt", ".scala", ".cs"}, "php": {".php"},
	"c": {".h", ".hpp", ".c", ".cc", ".cpp"}, "sh": {"", ".sh"}, "html": {""}}

func (r *Resolver) Resolve(p, what string) map[string]bool {
	folder := "."
	if i := strings.LastIndex(p, "/"); i >= 0 {
		folder = p[:i]
	}
	lang := IMPORT_LANG[strings.ToLower(Suffix(p))]
	exts, ok := extsOf[lang]
	if !ok {
		exts = []string{""}
	}
	found := map[string]bool{}
	relLang := lang == "c" || lang == "css" || lang == "html" || lang == "sh" || lang == "php" || lang == "ruby"
	first := strings.SplitN(what, "/", 2)[0]
	switch {
	case strings.HasPrefix(what, "./") || strings.HasPrefix(what, "../") || strings.HasPrefix(what, "/") || (relLang && strings.Contains(what, "/")) ||
		(lang == "js" && !strings.HasPrefix(what, ".") && strings.Contains(what, "/") && (first == "src" || first == "lib" || first == "app")):
		base := folder + "/" + what
		if strings.HasPrefix(what, "/") {
			base = strings.TrimLeft(what, "/")
		}
		for _, c := range append([]string{base}, candidates(base, exts)...) {
			if f, ok := r.file(c); ok {
				found[f] = true
				break
			}
		}
	case lang == "py":
		dots := len(what) - len(strings.TrimLeft(what, "."))
		name := strings.TrimLeft(what, ".")
		var bases []string
		if dots > 0 {
			up := folder
			for k := 0; k < dots-1; k++ {
				if i := strings.LastIndex(up, "/"); i >= 0 {
					up = up[:i]
				} else {
					up = "."
				}
			}
			bases = []string{up}
		} else {
			bases = []string{".", folder}
			for _, root := range CFG.Roots {
				if IsDir(root) {
					bases = append(bases, root)
				}
			}
		}
		rel := strings.ReplaceAll(name, ".", "/")
		for _, b := range bases {
			base := b
			if rel != "" {
				base = b + "/" + rel
			}
			for _, c := range candidates(base, []string{".py"}) {
				if f, ok := r.file(c); ok {
					found[f] = true
					break
				}
			}
			if len(found) > 0 {
				break
			}
		}
		if len(found) == 0 && rel != "" {
			for _, c := range append(append([]string{}, r.BySuffix[rel+".py"]...), r.BySuffix[rel+"/__init__.py"]...) {
				found[c] = true
			}
		}
	case lang == "go" && r.Gomod != "" && strings.HasPrefix(what, r.Gomod):
		rel := strings.Trim(what[len(r.Gomod):], "/")
		if rel == "" {
			rel = "."
		}
		for q := range r.Paths {
			if !strings.HasSuffix(q, ".go") {
				continue
			}
			dir := "."
			if i := strings.LastIndex(q, "/"); i >= 0 {
				dir = q[:i]
			}
			if dir == rel {
				found[q] = true
			}
		}
	case lang == "rust":
		w := strings.ReplaceAll(strings.ReplaceAll(strings.ReplaceAll(what, "crate::", ""), "self::", ""), "super::", "")
		var parts []string
		for _, x := range strings.Split(w, "::") {
			if x != "" && x != "crate" {
				parts = append(parts, x)
			}
		}
		for k := len(parts); k > 0; k-- {
			for _, root := range []string{"src", folder} {
				for _, c := range candidates(root+"/"+strings.Join(parts[:k], "/"), []string{".rs"}) {
					if f, ok := r.file(c); ok {
						found[f] = true
					}
				}
			}
			if len(found) > 0 {
				break
			}
		}
	case lang == "jvm":
		parts := strings.Split(what, ".")
		for k := len(parts); k > 1; k-- {
			head := parts[:k]
			tail := head
			if len(tail) > 4 {
				tail = tail[len(tail)-4:]
			}
			for _, e := range exts {
				for _, c := range r.BySuffix[strings.Join(tail, "/")+e] {
					if strings.HasSuffix(c, strings.Join(head, "/")+e) {
						found[c] = true
					}
				}
			}
			if len(found) > 0 {
				break
			}
		}
	case lang == "php" && strings.Contains(what, `\`):
		parts := strings.Split(strings.Trim(what, `\`), `\`)
		last2 := parts
		if len(last2) > 2 {
			last2 = last2[len(last2)-2:]
		}
		for _, c := range append(append([]string{}, r.BySuffix[strings.Join(last2, "/")+".php"]...), r.BySuffix[parts[len(parts)-1]+".php"]...) {
			found[c] = true
		}
	case lang == "ruby":
		for _, c := range candidates("lib/"+what, []string{".rb"}) {
			if f, ok := r.file(c); ok {
				found[f] = true
			}
		}
	}
	return found
}

type Graph struct {
	Blocks    []*Block
	ByFile    map[string][]*Block
	Purpose   map[string]string
	Main      map[string]string
	FileEdges map[string]map[string]bool
	Edges     map[[2]string]int
	EdgeOrder [][2]string
	Importers map[string]map[string]bool
}

func NewGraph(blocks []*Block) *Graph {
	g := &Graph{Blocks: blocks, ByFile: map[string][]*Block{}, Purpose: map[string]string{}, Main: map[string]string{},
		FileEdges: map[string]map[string]bool{}, Edges: map[[2]string]int{}, Importers: map[string]map[string]bool{}}
	for _, b := range blocks {
		g.ByFile[b.Path] = append(g.ByFile[b.Path], b)
	}
	byPath := append([]*Block{}, blocks...)
	sort.SliceStable(byPath, func(i, j int) bool { return byPath[i].Path < byPath[j].Path })
	for _, b := range byPath {
		if _, ok := g.Purpose[b.ID]; !ok {
			g.Purpose[b.ID] = b.Purpose
		}
	}
	for p, bs := range g.ByFile {
		counts := map[string]int{}
		var order []string
		for _, b := range bs {
			c := Component(b.ID)
			if _, ok := counts[c]; !ok {
				order = append(order, c)
			}
			counts[c] += b.Lines
		}
		best := order[0]
		for _, c := range order {
			if counts[c] > counts[best] {
				best = c
			}
		}
		g.Main[p] = best
	}
	var paths []string
	for _, p := range RepoFiles() {
		if TEXT[strings.ToLower(Suffix(p))] || Forms(p) != nil {
			paths = append(paths, p)
		}
	}
	r := NewResolver(paths)
	for _, p := range Files() {
		for _, imp := range FactsOf(p).Imports {
			for _, target := range SortedKeys(r.Resolve(p, imp.What)) {
				if target == p {
					continue
				}
				if g.FileEdges[p] == nil {
					g.FileEdges[p] = map[string]bool{}
				}
				g.FileEdges[p][target] = true
				src := g.At(p, imp.Line)
				if src == "" {
					src = g.Main[p]
				}
				dst := g.Main[target]
				if src != "" && dst != "" && Component(src) != dst {
					key := [2]string{Component(src), dst}
					if _, ok := g.Edges[key]; !ok {
						g.EdgeOrder = append(g.EdgeOrder, key)
					}
					g.Edges[key]++
				}
			}
		}
	}
	for p, ts := range g.FileEdges {
		for t := range ts {
			if g.Importers[t] == nil {
				g.Importers[t] = map[string]bool{}
			}
			g.Importers[t][p] = true
		}
	}
	return g
}

// At: the innermost block of a file holding a line, or "".
func (g *Graph) At(p string, line int) string {
	var best *Block
	for _, b := range g.ByFile[p] {
		if b.First <= line && line <= b.Last {
			if best == nil || b.First > best.First || (b.First == best.First && b.Last < best.Last) {
				best = b
			}
		}
	}
	if best == nil {
		return ""
	}
	return best.ID
}

// @end map.code.imports
