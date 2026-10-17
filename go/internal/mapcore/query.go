// @map map.query.find: find by words or by an identifier, where, gaps, history from git, deps and impact from imports, tests
package mapcore

import (
	"fmt"
	"os/exec"
	"regexp"
	"sort"
	"strings"
)

var identifierRx = regexp.MustCompile(`[a-z][A-Z]|[A-Za-z0-9]-[A-Za-z0-9]|_|^[#.][A-Za-z]|^--`)

func Identifier(w string) bool { return identifierRx.MatchString(w) }

const SHOWN = 15

func hasWord(text, w string) bool {
	for _, h := range LowerWords(text) {
		if strings.HasPrefix(h, w) {
			return true
		}
	}
	return false
}

func countWords(text string, words []string) int {
	n := 0
	for _, w := range words {
		if hasWord(text, w) {
			n++
		}
	}
	return n
}

func Find(args []string) {
	blocks, _, _ := Everything()
	var raw []string
	for _, a := range args {
		raw = append(raw, strings.Fields(a)...)
	}
	var words []string
	for _, x := range raw {
		if !Identifier(x) || len(raw) == 1 {
			words = append(words, strings.ToLower(x))
		}
	}
	said := false
	anyId := false
	for _, w := range raw {
		if Identifier(w) {
			anyId = true
		}
	}
	if len(raw) == 1 || anyId {
		repo := NewRepo(blocks)
		for _, w := range raw {
			if len(raw) == 1 || Identifier(w) {
				ds := Declarations(repo, strings.TrimLeft(w, "#."))
				if len(ds) > 5 {
					ds = ds[:5]
				}
				for _, d := range ds {
					where := repo.Where(d.Path, d.First, 0)
					if where == "" {
						where = d.Path
					}
					Printf("%s: %s, declared in %s  %s:%d-%d", w, d.What, where, d.Path, d.First, d.Last)
					said = true
				}
			}
		}
	}
	var hits []*Block
	if len(words) > 0 {
		for _, b := range blocks {
			ok := true
			for _, w := range words {
				if !hasWord(b.ID+" "+b.Purpose+" "+b.Path, w) {
					ok = false
					break
				}
			}
			if ok {
				hits = append(hits, b)
			}
		}
	}
	sort.SliceStable(hits, func(i, j int) bool {
		a, b := hits[i], hits[j]
		ka := []int{-countWords(a.ID, words), bool2int(IsTest(a.Path)), -countWords(a.Purpose, words)}
		kb := []int{-countWords(b.ID, words), bool2int(IsTest(b.Path)), -countWords(b.Purpose, words)}
		for k := range ka {
			if ka[k] != kb[k] {
				return ka[k] < kb[k]
			}
		}
		if a.Path != b.Path {
			return a.Path < b.Path
		}
		return a.First < b.First
	})
	if said && len(raw) == 1 {
		var kept []*Block
		for _, b := range hits {
			if hasWord(b.ID, words[0]) {
				kept = append(kept, b)
			}
		}
		hits = kept
	}
	shown := hits
	if len(shown) > SHOWN {
		shown = shown[:SHOWN]
	}
	for _, b := range shown {
		purpose := b.Purpose
		if r := []rune(purpose); len(r) > 120 {
			cutAt := -1
			for i := 118; i >= 0; i-- {
				if r[i] == ' ' {
					cutAt = i
					break
				}
			}
			if cutAt < 0 {
				cutAt = 0
			}
			purpose = string(r[:cutAt]) + "…"
		}
		Printf("%s %s:%d-%d (%d lines)  %s", PadR(b.ID, 44), b.Path, b.First, b.Last, b.Lines, purpose)
	}
	if len(hits) > SHOWN {
		Printf("… %d more: add a word to narrow them", len(hits)-SHOWN)
	}
	if len(hits) == 0 && !said {
		Print("No block matches. Try fewer words, or the code's text: " + CMD + " ask '<text>'")
	}
}

func bool2int(b bool) int {
	if b {
		return 1
	}
	return 0
}

func Matching(id string, blocks []*Block) []*Block {
	var out []*Block
	for _, b := range blocks {
		if b.ID == id || strings.HasPrefix(b.ID, id+".") {
			out = append(out, b)
		}
	}
	return out
}

func Where(id string) {
	blocks, _, _ := Everything()
	hits := Matching(id, blocks)
	for _, b := range hits {
		Printf("%s %s:%d-%d (%d lines)", PadR(b.ID, 44), b.Path, b.First, b.Last, b.Lines)
	}
	if len(hits) == 0 {
		Die("No block " + id + ". Search with: " + CMD + " find <words>")
	}
}

func Gaps(paths []string) {
	every := Files()
	chosen := every
	if len(paths) > 0 {
		chosen = nil
		for _, f := range every {
			for _, p := range paths {
				if f == p || strings.HasPrefix(f, strings.TrimRight(p, "/")+"/") {
					chosen = append(chosen, f)
					break
				}
			}
		}
	}
	untagged, printed := 0, false
	for _, p := range chosen {
		f := FactsOf(p)
		var big []*Block
		for _, b := range f.Blocks {
			if b.Own > LARGEST {
				big = append(big, b)
			}
		}
		elsewhere := map[string]bool{}
		for _, b := range f.Blocks {
			a := strings.Split(b.ID, ".")[0]
			if a != AreaOf(p) {
				elsewhere[a] = true
			}
		}
		if len(f.Blocks) == 0 {
			untagged++
			printed = true
			var decls []string
			for _, d := range f.Decls {
				if d.Kind == "function" || d.Kind == "class" || d.Kind == "method" {
					decls = append(decls, d.Name)
				}
			}
			line := fmt.Sprintf("%s: no tags (%d lines; area %s", p, len(f.Outside), AreaOf(p))
			if len(decls) > 0 {
				shown := decls
				if len(shown) > 6 {
					shown = shown[:6]
				}
				line += "; declares " + strings.Join(shown, ", ")
				if len(decls) > 6 {
					line += " …"
				}
			}
			Print(line + ")")
		} else if len(f.Outside) > UNTAGGED || len(big) > 0 || len(f.Problems) > 0 || len(elsewhere) > 0 {
			printed = true
			line := fmt.Sprintf("%s: %d blocks, %d lines outside", p, len(f.Blocks), len(f.Outside))
			if len(f.Outside) > 0 {
				line += fmt.Sprintf(" (from line %d)", f.Outside[0])
			}
			Print(line)
			if len(elsewhere) > 0 {
				Print("  note: blocks of " + strings.Join(SortedKeys(elsewhere), ", ") + " live in this file")
			}
			for _, b := range big {
				Printf("  split %s (lines %d-%d, %s characters of its own)", b.ID, b.First, b.Last, Commas(b.Own))
			}
			for _, pr := range f.problems() {
				Printf("  line %d: %s", pr.Line, pr.Text)
			}
		}
	}
	SaveCache()
	if untagged > 0 {
		Printf("%d of %d files carry no tag: docs/TAGGING.md says how to tag them with an agent", untagged, len(chosen))
	} else if !printed {
		Printf("All %d code files are tagged, no block to split, no problem.", len(chosen))
	}
}

func Git(args ...string) string {
	b, err := exec.Command("git", append([]string{"-C", ROOT}, args...)...).Output()
	if err != nil && b == nil {
		return ""
	}
	return string(b)
}

func History(what string) {
	blocks, _, _ := Everything()
	var hits []*Block
	for _, b := range blocks {
		if b.ID == what {
			hits = append(hits, b)
		}
	}
	if len(hits) == 0 {
		hits = Matching(what, blocks)
		if len(hits) > 3 {
			hits = hits[:3]
		}
	}
	if len(hits) == 0 && IsFile(what) {
		hits = []*Block{{ID: what, Path: what, First: 0}}
	}
	if len(hits) == 0 {
		Die("No block or file " + what + ". Search with: " + CMD + " find <words>")
	}
	for _, b := range hits {
		var raw string
		if b.First == 0 {
			raw = Git("log", "-n", "12", "--format=%h %ad %s", "--date=short", "--", b.Path)
		} else {
			raw = Git("log", "-s", "-n", "12", "--format=%h %ad %s", "--date=short", fmt.Sprintf("-L%d,%d:%s", b.First, b.Last, b.Path))
		}
		var lines []string
		for _, l := range strings.Split(raw, "\n") {
			if strings.TrimSpace(l) != "" {
				lines = append(lines, l)
			}
		}
		head := b.ID + "  " + b.Path
		if b.First != 0 {
			head += fmt.Sprintf(":%d-%d", b.First, b.Last)
		}
		head += fmt.Sprintf(": %d commits", len(lines))
		if len(lines) > 0 {
			head += ", latest first"
		} else {
			head += " (not in git, or no history yet)"
		}
		Print(head)
		for _, l := range lines {
			Print("  " + l)
		}
	}
}

func Deps(what string) {
	blocks, _, _ := Everything()
	g := NewGraph(blocks)
	paths := map[string]bool{}
	for _, b := range Matching(what, blocks) {
		paths[b.Path] = true
	}
	if len(paths) == 0 {
		if _, ok := g.FileEdges[what]; ok || IsFile(what) {
			paths[what] = true
		}
	}
	if len(paths) == 0 {
		Die("No block or file " + what + ".")
	}
	for _, p := range SortedKeys(paths) {
		ts := SortedKeys(g.FileEdges[p])
		line := fmt.Sprintf("%s imports %d files of the repository", p, len(ts))
		if len(ts) > 0 {
			line += ":"
		}
		Print(line)
		for _, t := range ts {
			Printf("  %s  %s", t, g.Main[t])
		}
	}
}

type reachMap struct {
	Order []string
	Why   map[string]string
}

func (r *reachMap) set(k, v string) {
	if _, ok := r.Why[k]; !ok {
		r.Order = append(r.Order, k)
	}
	r.Why[k] = v
}

// Reaching: the test files that import these files (one step, then one more) or name one of them or of the names.
func Reaching(g *Graph, paths []string, names map[string]bool) *reachMap {
	ps := map[string]bool{}
	for _, p := range paths {
		ps[p] = true
	}
	direct := map[string]bool{}
	for _, p := range paths {
		for s := range g.Importers[p] {
			if !ps[s] {
				direct[s] = true
			}
		}
	}
	second := map[string]bool{}
	for p := range direct {
		for s := range g.Importers[p] {
			if !ps[s] && !direct[s] {
				second[s] = true
			}
		}
	}
	found := &reachMap{Why: map[string]string{}}
	tests := TestFiles()
	for _, t := range tests {
		switch {
		case ps[t]:
			found.set(t, "the test itself")
		case direct[t]:
			var both []string
			for x := range g.FileEdges[t] {
				if ps[x] {
					both = append(both, x)
				}
			}
			sort.Strings(both)
			if len(both) > 2 {
				both = both[:2]
			}
			found.set(t, "imports "+strings.Join(both, ", "))
		case second[t]:
			found.set(t, "imports what imports it")
		}
	}
	shortNames := map[string]bool{}
	for _, p := range paths {
		n := p[strings.LastIndex(p, "/")+1:]
		if len(n) > 6 {
			shortNames[n] = true
		}
	}
	for n := range names {
		shortNames[n] = true
	}
	for _, t := range tests {
		if _, ok := found.Why[t]; ok {
			continue
		}
		text := ReadFile(t)
		hit := false
		for _, p := range paths {
			if strings.Contains(text, p) {
				hit = true
				break
			}
		}
		if !hit {
			for n := range shortNames {
				if Bounded(text, n, ".", "-") {
					hit = true
					break
				}
			}
		}
		if hit {
			found.set(t, "names it")
		}
	}
	return found
}

func Impact(what string) {
	blocks, _, _ := Everything()
	g := NewGraph(blocks)
	mine := map[string]bool{}
	for _, b := range Matching(what, blocks) {
		mine[b.Path] = true
	}
	if len(mine) == 0 && IsFile(what) {
		mine[what] = true
	}
	if len(mine) == 0 {
		Die("No block or file " + what + ".")
	}
	direct := map[string]bool{}
	for p := range mine {
		for s := range g.Importers[p] {
			if !mine[s] {
				direct[s] = true
			}
		}
	}
	second := map[string]bool{}
	for p := range direct {
		for s := range g.Importers[p] {
			if !mine[s] && !direct[s] {
				second[s] = true
			}
		}
	}
	line := fmt.Sprintf("%d files import %s directly", len(direct), what)
	if len(direct) > 0 {
		line += ":"
	} else {
		line += "."
	}
	Print(line)
	for _, p := range SortedKeys(direct) {
		Printf("  %s  %s", p, g.Main[p])
	}
	if len(second) > 0 {
		keys := SortedKeys(second)
		shown := keys
		if len(shown) > 12 {
			shown = shown[:12]
		}
		s := fmt.Sprintf("%d more import those: %s", len(second), strings.Join(shown, ", "))
		if len(keys) > 12 {
			s += " …"
		}
		Print(s)
	}
	names := map[string]bool{}
	for _, b := range Matching(what, blocks) {
		names[Component(b.ID)] = true
	}
	tests := SortedKeys(Reaching(g, SortedKeys(mine), names).toSet())
	if len(tests) > 0 {
		Printf("Tests that reach it (%d): %s", len(tests), strings.Join(tests, " "))
	} else {
		Print("Tests that reach it (0): none import or name it; run the suite")
	}
}

func (r *reachMap) toSet() map[string]bool {
	m := map[string]bool{}
	for k := range r.Why {
		m[k] = true
	}
	return m
}

func Changed() []string {
	var out []string
	for _, e := range strings.Split(Git("status", "--porcelain=v1", "-z", "--untracked-files=all"), "\x00") {
		if len(e) > 3 {
			out = append(out, strings.SplitN(e[3:], "\x00", 2)[0])
		}
	}
	return out
}

func Tests(args []string) {
	paths := args
	if len(args) == 0 || (len(args) == 1 && args[0] == "--changed") {
		paths = Changed()
	}
	if len(paths) == 0 {
		Print("Nothing changed: no test to run.")
		return
	}
	blocks, _, _ := Everything()
	g := NewGraph(blocks)
	chosen := &reachMap{Why: map[string]string{}}
	sorted := append([]string{}, paths...)
	sort.Strings(sorted)
	for _, p := range sorted {
		ids := map[string]bool{}
		for _, b := range g.ByFile[p] {
			ids[Component(b.ID)] = true
		}
		found := Reaching(g, []string{p}, ids)
		for _, t := range found.Order {
			if _, ok := chosen.Why[t]; !ok {
				chosen.set(t, found.Why[t])
			}
		}
		plural := "s"
		if len(found.Order) == 1 {
			plural = ""
		}
		Printf("  %s: %d test file%s", p, len(found.Order), plural)
	}
	if len(chosen.Order) > 0 {
		keys := SortedKeys(chosen.toSet())
		Print("Run: " + strings.Join(keys, " "))
		for _, t := range keys {
			Printf("  %s  (%s)", t, chosen.Why[t])
		}
	} else {
		Print("No test file imports or names these files.")
	}
}
// @end map.query.find
