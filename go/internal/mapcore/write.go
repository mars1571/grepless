// @map map.core.write: map.yaml, the central map of the areas, and map/<area>.yaml, each area's components; build and check
package mapcore

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

type Comp struct {
	Files, Parts, Needs, By, Docs map[string]bool
	Declares                      []string
	Blocks, Lines                 int
	Tests                         map[string]string
	What                          string
}

type Comps struct {
	Order []string
	M     map[string]*Comp
}

func (c *Comps) get(name string) *Comp { return c.M[name] }

func header(name string, blocks []*Block, perFile map[string]int) string {
	var mine []*Block
	for _, b := range blocks {
		if Component(b.ID) == name {
			mine = append(mine, b)
		}
	}
	if len(mine) == 0 {
		return ""
	}
	first := mine[0]
	for _, b := range mine {
		if b.Path < first.Path || (b.Path == first.Path && b.First < first.First) {
			first = b
		}
	}
	n := 0
	for _, b := range mine {
		if b.Path == first.Path {
			n++
		}
	}
	if perFile[first.Path] == n {
		return first.Purpose
	}
	return ""
}

var idLike = regexp.MustCompile(`[a-z][a-z0-9-]*\.[a-z0-9-]+`)

// IdsIn: the id-like words of a text (shop.cart), each bounded: no letter, digit or dot before, none or a hyphen after.
func IdsIn(text string) map[string]bool {
	out := map[string]bool{}
	for _, loc := range idLike.FindAllStringIndex(text, -1) {
		okBefore, okAfter := true, true
		if loc[0] > 0 {
			r := []rune(text[loc[0]-1 : loc[0]])
			if len(r) == 0 || isAlnumRune(lastRune(text[:loc[0]])) || strings.ContainsRune("_.", lastRune(text[:loc[0]])) {
				okBefore = false
			}
		}
		if loc[1] < len(text) {
			r := firstRune(text[loc[1]:])
			if isAlnumRune(r) || strings.ContainsRune("_-", r) {
				okAfter = false
			}
		}
		if okBefore && okAfter {
			out[text[loc[0]:loc[1]]] = true
		}
	}
	return out
}

func lastRune(s string) rune {
	r := []rune(s)
	if len(r) == 0 {
		return 0
	}
	return r[len(r)-1]
}
func firstRune(s string) rune {
	for _, r := range s {
		return r
	}
	return 0
}

func docsNaming(comps *Comps) map[string]map[string]bool {
	var paths []string
	for _, p := range RepoFiles() {
		if DOCS[strings.ToLower(Suffix(p))] && SizeOf(p) < LARGE {
			paths = append(paths, p)
		}
	}
	names := map[string]int{}
	allFiles := map[string]bool{}
	for _, c := range comps.M {
		for f := range c.Files {
			names[f[strings.LastIndex(f, "/")+1:]]++
			allFiles[f] = true
		}
	}
	found := map[string]map[string]bool{}
	for _, p := range paths {
		text := ReadFile(p)
		said := map[string]bool{}
		for id := range IdsIn(text) {
			if _, ok := comps.M[id]; ok {
				said[id] = true
			}
		}
		hit := map[string]bool{}
		for f := range allFiles {
			base := f[strings.LastIndex(f, "/")+1:]
			if strings.Contains(text, f) || (names[base] == 1 && strings.Contains(text, "`"+base+"`")) {
				hit[f] = true
			}
		}
		for _, name := range comps.Order {
			for f := range comps.M[name].Files {
				if hit[f] {
					said[name] = true
				}
			}
		}
		found[p] = said
	}
	return found
}

func TestFiles() []string {
	var out []string
	for _, p := range RepoFiles() {
		if IsTest(p) && (Forms(p) != nil || TEXT[strings.ToLower(Suffix(p))]) {
			out = append(out, p)
		}
	}
	return out
}

func testsReaching(g *Graph, comps *Comps) map[string]map[string]string {
	out := map[string]map[string]string{}
	for _, name := range comps.Order {
		out[name] = map[string]string{}
	}
	filesOf := map[string]map[string]bool{}
	for _, name := range comps.Order {
		for f := range comps.M[name].Files {
			if filesOf[f] == nil {
				filesOf[f] = map[string]bool{}
			}
			filesOf[f][name] = true
		}
	}
	for _, t := range TestFiles() {
		for _, target := range SortedKeys(g.FileEdges[t]) {
			for _, name := range SortedKeys(filesOf[target]) {
				out[name][t] = "imports " + target
			}
		}
		text := ReadFile(t)
		for _, name := range comps.Order {
			if _, ok := out[name][t]; ok {
				continue
			}
			c := comps.M[name]
			hit := false
			for f := range c.Files {
				if f != t && strings.Contains(text, f) {
					hit = true
					break
				}
			}
			if hit || (strings.Contains(text, name) && Bounded(text, name, ".", "-")) {
				out[name][t] = "names it"
			}
		}
	}
	return out
}

// Components: every component: what it is, its parts, files, declarations, needs and what needs it, tests and docs.
func Components(blocks []*Block, g *Graph) *Comps {
	purpose := map[string]string{}
	byPath := append([]*Block{}, blocks...)
	sort.SliceStable(byPath, func(i, j int) bool { return byPath[i].Path < byPath[j].Path })
	for _, b := range byPath {
		if _, ok := purpose[b.ID]; !ok {
			purpose[b.ID] = b.Purpose
		}
	}
	comps := &Comps{M: map[string]*Comp{}}
	for _, b := range blocks {
		name := Component(b.ID)
		c, ok := comps.M[name]
		if !ok {
			c = &Comp{Files: map[string]bool{}, Parts: map[string]bool{}, Needs: map[string]bool{}, By: map[string]bool{}, Docs: map[string]bool{}, Tests: map[string]string{}}
			comps.M[name] = c
			comps.Order = append(comps.Order, name)
		}
		c.Files[b.Path] = true
		c.Blocks++
		c.Lines += b.Lines
		if parts := strings.Split(b.ID, "."); len(parts) > 2 {
			c.Parts[parts[2]] = true
		}
	}
	perFile := map[string]int{}
	for _, b := range blocks {
		perFile[b.Path]++
	}
	firstOf := map[string]string{}
	ordered := append([]*Block{}, blocks...)
	sort.SliceStable(ordered, func(i, j int) bool {
		if ordered[i].Path != ordered[j].Path {
			return ordered[i].Path < ordered[j].Path
		}
		return ordered[i].First < ordered[j].First
	})
	for _, b := range ordered {
		if _, ok := firstOf[Component(b.ID)]; !ok {
			firstOf[Component(b.ID)] = b.Purpose
		}
	}
	for _, name := range comps.Order {
		c := comps.M[name]
		c.What = purpose[name]
		if c.What == "" {
			c.What = header(name, blocks, perFile)
		}
		if c.What == "" {
			c.What = purpose[name+".api"]
		}
		if c.What == "" {
			c.What = firstOf[name]
		}
	}
	for _, e := range g.EdgeOrder {
		s, d := e[0], e[1]
		if _, ok := comps.M[s]; ok {
			if _, ok := comps.M[d]; ok {
				comps.M[s].Needs[d] = true
				comps.M[d].By[s] = true
			}
		}
	}
	for _, p := range Files() {
		for _, d := range FactsOf(p).Decls {
			if d.Kind == "function" || d.Kind == "class" || d.Kind == "method" {
				if b := g.At(p, d.First); b != "" {
					comps.M[Component(b)].Declares = append(comps.M[Component(b)].Declares, d.Name)
				}
			}
		}
	}
	for name, found := range testsReaching(g, comps) {
		comps.M[name].Tests = found
	}
	for doc, named := range docsNaming(comps) {
		for c := range named {
			comps.M[c].Docs[doc] = true
		}
	}
	return comps
}

type areaList struct {
	Order []string
	M     map[string][]string
}

func AreasOf(comps *Comps) areaList {
	out := areaList{M: map[string][]string{}}
	names := append([]string{}, comps.Order...)
	sort.Strings(names)
	for _, name := range names {
		a := strings.Split(name, ".")[0]
		if _, ok := out.M[a]; !ok {
			out.Order = append(out.Order, a)
		}
		out.M[a] = append(out.M[a], name)
	}
	return out
}

type kv struct {
	k string
	v int
}

func countsLine(m map[string]int) string {
	var items []kv
	for k, v := range m {
		items = append(items, kv{k, v})
	}
	sort.Slice(items, func(i, j int) bool {
		if items[i].v != items[j].v {
			return items[i].v > items[j].v
		}
		return items[i].k < items[j].k
	})
	var parts []string
	for _, it := range items {
		parts = append(parts, fmt.Sprintf("%s: %d", it.k, it.v))
	}
	return "{" + strings.Join(parts, ", ") + "}"
}

func sortedCountsLine(m map[string]int) string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var parts []string
	for _, k := range keys {
		parts = append(parts, fmt.Sprintf("%s: %d", k, m[k]))
	}
	return strings.Join(parts, ", ")
}

func Central(comps *Comps, untagged []string) string {
	name := CFG.Name
	if name == "" {
		name = filepath.Base(ROOT)
	}
	lines := []string{
		"# The map of " + name + ": the areas, what each needs from the others (read from imports), and where each one's map is.",
		"# Generated by `" + CMD + " build`; never edit it. `" + CMD + " check` fails when it is out of date.",
		"# An area's components, what each needs and what needs it: map/<area>.yaml.",
		"# Reading and finding: `" + CMD + " brief <words>`, then `" + CMD + " ask <questions>` (AGENTS.md, \"Finding code\").",
		"version: 1", "", "areas:", "  # needs: how many of its components import a component of that area; needed_by: the other way"}
	al := AreasOf(comps)
	count := func(area string, mine []string, by bool) string {
		n := map[string]int{}
		for _, c := range mine {
			src := comps.M[c].Needs
			if by {
				src = comps.M[c].By
			}
			for o := range src {
				a := strings.Split(o, ".")[0]
				if a != area {
					n[a]++
				}
			}
		}
		return countsLine(n)
	}
	for _, area := range al.Order {
		mine := al.M[area]
		files := map[string]bool{}
		nb := 0
		for _, c := range mine {
			for f := range comps.M[c].Files {
				files[f] = true
			}
			nb += comps.M[c].Blocks
		}
		holds := ""
		if h := CFG.Holds.Str(area); h != "" {
			holds = "holds: " + Jstr(h) + ", "
		}
		lines = append(lines, fmt.Sprintf("  %s: {%scomponents: %d, files: %d, blocks: %d, map: map/%s.yaml, needs: %s, needed_by: %s}",
			area, holds, len(mine), len(files), nb, area, count(area, mine, false), count(area, mine, true)))
	}
	if len(untagged) > 0 {
		lines = append(lines, "", "untagged:", "  # code files that carry no tag yet, by folder ("+CMD+" gaps lists them)")
		groups := map[string]int{}
		for _, p := range untagged {
			k := "."
			if i := strings.LastIndex(p, "/"); i >= 0 {
				k = p[:i] + "/"
			}
			groups[k]++
		}
		keys := make([]string, 0, len(groups))
		for k := range groups {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			lines = append(lines, fmt.Sprintf("  %s: %d", Jstr(k), groups[k]))
		}
	}
	lines = append(lines, "", "other:", "  # files without code to read, by folder; each kind described in map.json (describe)")
	all := map[string]bool{"map.yaml": true}
	for _, p := range RepoFiles() {
		all[p] = true
	}
	for _, a := range al.Order {
		all["map/"+a+".yaml"] = true
	}
	groups := map[string][]string{}
	for _, p := range SortedKeys(all) {
		if Forms(p) == nil || Described(p) != nil {
			k := "."
			if i := strings.Index(p, "/"); i >= 0 {
				k = p[:i] + "/"
			}
			groups[k] = append(groups[k], p)
		}
	}
	gkeys := make([]string, 0, len(groups))
	for k := range groups {
		gkeys = append(gkeys, k)
	}
	sort.Strings(gkeys)
	for _, folder := range gkeys {
		paths := groups[folder]
		var names []string
		kinds := map[string]int{}
		for _, p := range paths {
			if folder != "." {
				names = append(names, p[strings.Index(p, "/")+1:])
			} else {
				names = append(names, p)
			}
			if d := Described(p); d != nil {
				kinds[d[1]]++
			} else {
				k := strings.TrimPrefix(Suffix(p), ".")
				if k == "" {
					k = "file"
				}
				kinds[k]++
			}
		}
		if len(names) <= 8 || folder == "." {
			var q []string
			for _, n := range names {
				q = append(q, Jstr(n))
			}
			lines = append(lines, fmt.Sprintf("  %s: [%s]", Jstr(folder), strings.Join(q, ", ")))
		} else {
			lines = append(lines, fmt.Sprintf("  %s: {files: %d, %s}", Jstr(folder), len(paths), sortedCountsLine(kinds)))
		}
	}
	return strings.Join(lines, "\n") + "\n"
}

func li(m map[string]bool) string { return "[" + strings.Join(SortedKeys(m), ", ") + "]" }

func Zone(area string, comps *Comps) string {
	holds := CFG.Holds.Str(area)
	head := "# The " + area + " area of the code map."
	if holds != "" {
		head = "# The " + area + " area of the code map: " + holds + "."
	}
	lines := []string{head,
		"# One line per component: what it is, its parts (" + CMD + " ask <component>.<part>), its files, what it",
		"# declares, the components it needs (imports) and those that need it, the tests that reach it (by folder)",
		"# and the docs that name it.",
		"# Generated by `" + CMD + " build`; never edit it. All the areas: map.yaml.", "", area + ":"}
	for _, name := range AreasOf(comps).M[area] {
		c := comps.M[name]
		var parts []string
		if c.What != "" {
			parts = append(parts, "what: "+Jstr(c.What))
		}
		if len(c.Parts) > 0 {
			parts = append(parts, "parts: "+li(c.Parts))
		}
		var fq []string
		for _, f := range SortedKeys(c.Files) {
			fq = append(fq, Jstr(f))
		}
		parts = append(parts, "files: ["+strings.Join(fq, ", ")+"]")
		if len(c.Declares) > 0 {
			seen := Unique(c.Declares)
			shown := seen
			if len(shown) > 8 {
				shown = shown[:8]
			}
			s := "declares: [" + strings.Join(shown, ", ")
			if len(seen) > 8 {
				s += fmt.Sprintf(", … %d more]", len(seen)-8)
			} else {
				s += "]"
			}
			parts = append(parts, s)
		}
		if len(c.Needs) > 0 {
			parts = append(parts, "needs: "+li(c.Needs))
		}
		if len(c.By) > 0 {
			parts = append(parts, "needed_by: "+li(c.By))
		}
		if len(c.Tests) > 0 {
			folders := map[string]int{}
			for t := range c.Tests {
				k := "."
				if i := strings.Index(t, "/"); i >= 0 {
					k = t[:i]
				}
				folders[k]++
			}
			parts = append(parts, "tests: {"+sortedCountsLine(folders)+"}")
		}
		if len(c.Docs) > 0 {
			parts = append(parts, "docs: "+li(c.Docs))
		}
		lines = append(lines, "  "+name+": {"+strings.Join(parts, ", ")+"}")
	}
	return strings.Join(lines, "\n") + "\n"
}

type written struct {
	paths []string
	texts map[string]string
}

func Written(comps *Comps, untagged []string) written {
	w := written{texts: map[string]string{}}
	w.paths = append(w.paths, MAP)
	w.texts[MAP] = Central(comps, untagged)
	for _, area := range AreasOf(comps).Order {
		p := filepath.Join(ZONES, area+".yaml")
		w.paths = append(w.paths, p)
		w.texts[p] = Zone(area, comps)
	}
	return w
}

func Build() []Problem {
	blocks, problems, untagged := Everything()
	comps := Components(blocks, NewGraph(blocks))
	w := Written(comps, untagged)
	os.MkdirAll(ZONES, 0o755)
	for _, p := range w.paths {
		old, err := os.ReadFile(p)
		if err != nil || lf(string(old)) != w.texts[p] {
			os.WriteFile(p, []byte(w.texts[p]), 0o644)
		}
	}
	if entries, err := os.ReadDir(ZONES); err == nil {
		for _, e := range entries {
			if strings.HasSuffix(e.Name(), ".yaml") {
				if _, ok := w.texts[filepath.Join(ZONES, e.Name())]; !ok {
					os.Remove(filepath.Join(ZONES, e.Name()))
				}
			}
		}
	}
	SaveCache()
	files := map[string]bool{}
	for _, b := range blocks {
		files[b.Path] = true
	}
	Printf("%d blocks in %d files, %d components, %d areas; %d files without tags; %d problems", len(blocks), len(files), len(comps.Order), len(AreasOf(comps).Order), len(untagged), len(problems))
	return problems
}

func Problems() ([]Problem, int, int) {
	blocks, found, untagged := Everything()
	if CFG.Strict {
		for _, p := range untagged {
			found = append(found, Problem{p, 0, "no blocks: tag this file"})
		}
	}
	comps := Components(blocks, NewGraph(blocks))
	w := Written(comps, untagged)
	for _, p := range w.paths {
		old, err := os.ReadFile(p)
		if err != nil || lf(string(old)) != w.texts[p] {
			rel, _ := filepath.Rel(ROOT, p)
			found = append(found, Problem{filepath.ToSlash(rel), 0, "out of date: run " + CMD + " build"})
		}
	}
	if IsDir("map") {
		entries, _ := os.ReadDir(ZONES)
		var names []string
		for _, e := range entries {
			if strings.HasSuffix(e.Name(), ".yaml") {
				names = append(names, e.Name())
			}
		}
		sort.Strings(names)
		al := AreasOf(comps)
		for _, n := range names {
			if _, ok := al.M[strings.TrimSuffix(n, ".yaml")]; !ok {
				found = append(found, Problem{"map/" + n, 0, "no such area: run " + CMD + " build"})
			}
		}
	}
	found = append(found, RecipeProblems(blocks)...)
	SaveCache()
	return found, len(blocks), len(untagged)
}

// @end map.core.write
