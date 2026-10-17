// @map map.brief.print: where a task starts: the components its words name, ranked, each with its parts, declarations, relations, tests, docs and commits
package mapcore

import (
	"fmt"
	"math"
	"sort"
	"strings"
)

var STOP = set("a an and are as at be by can do does for from has have how i in into is it its me my new of on or our should so that the their them then there these this to us was we what when where which who why will with add change changes make fix use using want need needs")

func WordsIn(args []string) []string {
	var out []string
	for _, w := range LowerWords(strings.Join(args, " ")) {
		if !STOP[w] && len(w) > 1 {
			out = append(out, w)
		}
	}
	return out
}

type scored struct {
	s float64
	b *Block
}

func round9(x float64) float64 { return math.Round(x*1e9) / 1e9 }

func hasIn(pool map[string]bool, w string) bool {
	for h := range pool {
		if strings.HasPrefix(h, w) || (len(w) > 3 && strings.HasSuffix(w, "s") && strings.HasPrefix(h, w[:len(w)-1])) {
			return true
		}
	}
	return false
}

func Ranked(blocks []*Block, g *Graph, words []string) []scored {
	names := map[string]map[string]bool{}
	for _, p := range Files() {
		for _, d := range FactsOf(p).Decls {
			if d.Kind == "heading" {
				continue
			}
			if b := g.At(p, d.First); b != "" {
				if names[b] == nil {
					names[b] = map[string]bool{}
				}
				for w := range WordsOf(d.Name) {
					names[b][w] = true
				}
			}
		}
	}
	type pools struct {
		b                  *Block
		id, purpose, other map[string]bool
	}
	var seenOrder []string
	seen := map[string]pools{}
	for _, b := range blocks {
		key := b.ID + "\x00" + b.Path
		other := map[string]bool{}
		for _, w := range LowerWords(b.Path) {
			other[w] = true
		}
		for w := range names[b.ID] {
			other[w] = true
		}
		purpose := map[string]bool{}
		for _, w := range LowerWords(b.Purpose) {
			purpose[w] = true
		}
		if _, ok := seen[key]; !ok {
			seenOrder = append(seenOrder, key)
		}
		seen[key] = pools{b, WordsOf(b.ID), purpose, other}
	}
	df := map[string]int{}
	for _, w := range words {
		n := 0
		for _, k := range seenOrder {
			p := seen[k]
			all := map[string]bool{}
			for x := range p.id {
				all[x] = true
			}
			for x := range p.purpose {
				all[x] = true
			}
			for x := range p.other {
				all[x] = true
			}
			if hasIn(all, w) {
				n++
			}
		}
		df[w] = n
	}
	var out []scored
	for _, k := range seenOrder {
		p := seen[k]
		s := 0.0
		for _, w := range words {
			weight := 0.0
			switch {
			case hasIn(p.id, w):
				weight = 3
			case hasIn(p.purpose, w):
				weight = 2
			case hasIn(p.other, w):
				weight = 1
			}
			s += weight * math.Log(1+float64(len(seen))/float64(1+df[w]))
		}
		if s != 0 {
			if IsTest(p.b.Path) {
				s -= 0.5
			}
			out = append(out, scored{round9(s), p.b})
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].s != out[j].s {
			return out[i].s > out[j].s
		}
		if out[i].b.Path != out[j].b.Path {
			return out[i].b.Path < out[j].b.Path
		}
		return out[i].b.First < out[j].b.First
	})
	return out
}

func Brief(args []string) {
	words := WordsIn(args)
	if len(words) == 0 {
		Die("Say the task in a few words, as the code names things: brief cart totals discount")
	}
	blocks, _, untagged := Everything()
	g := NewGraph(blocks)
	comps := Components(blocks, g)
	hits := Ranked(blocks, g, words)
	var perOrder []string
	per := map[string][]scored{}
	for _, h := range hits {
		if IsTest(h.b.Path) {
			continue
		}
		c := Component(h.b.ID)
		if _, ok := per[c]; !ok {
			perOrder = append(perOrder, c)
		}
		per[c] = append(per[c], h)
	}
	score := map[string]float64{}
	for _, c := range perOrder {
		xs := append([]scored{}, per[c]...)
		sort.SliceStable(xs, func(i, j int) bool { return xs[i].s > xs[j].s })
		t := 0.0
		for i, x := range xs {
			if i >= 3 {
				break
			}
			t += x.s * []float64{1, 0.5, 0.25}[i]
		}
		score[c] = round9(t)
	}
	order := append([]string{}, perOrder...)
	sort.SliceStable(order, func(i, j int) bool { return score[order[i]] > score[order[j]] })
	if len(order) == 0 {
		Die("No block matches those words. Try others, or " + CMD + " find <word>.")
	}
	var near []string
	for _, c := range order {
		if score[c] >= 0.25*score[order[0]] && len(near) < 10 {
			near = append(near, c)
		}
	}
	chosen, also := near, []string{}
	if len(near) > 3 {
		chosen, also = near[:3], near[3:]
	}
	Printf("brief %s: %d of %d components that match, best first. ask <id or name> reads a block.", strings.Join(words, " "), len(near), len(order))
	for ci, c := range chosen {
		info := comps.M[c]
		fs := SortedKeys(info.Files)
		shownFs := fs
		more := ""
		if len(shownFs) > 4 {
			shownFs = shownFs[:4]
			more = " …"
		}
		Printf("\n%s  %s  [%s%s]", c, Short(info.What, 100), strings.Join(shownFs, ", "), more)
		type bestEntry struct {
			b *Block
			n int
		}
		var bestOrder []string
		best := map[string]*bestEntry{}
		xs := append([]scored{}, per[c]...)
		sort.SliceStable(xs, func(i, j int) bool { return xs[i].s > xs[j].s })
		for _, x := range xs {
			if _, ok := best[x.b.ID]; !ok {
				best[x.b.ID] = &bestEntry{x.b, 0}
				bestOrder = append(bestOrder, x.b.ID)
			}
			best[x.b.ID].n++
		}
		limit := 3
		if ci < 2 {
			limit = 5
		}
		for i, id := range bestOrder {
			if i >= limit {
				break
			}
			e := best[id]
			label := "      "
			if i == 0 {
				label = "parts:"
			}
			more := ""
			if e.n > 1 {
				more = fmt.Sprintf(" (+%d files)", e.n-1)
			}
			Printf("  %s %s %s:%d-%d%s — %s", label, e.b.ID, e.b.Path, e.b.First, e.b.Last, more, Short(e.b.Purpose, 70))
		}
		decl := Unique(info.Declares)
		if len(decl) > 0 {
			var about, rest []string
			for _, d := range decl {
				matched := false
				for h := range WordsOf(d) {
					for _, w := range words {
						if strings.HasPrefix(h, w) {
							matched = true
						}
					}
				}
				if matched {
					about = append(about, d)
				} else {
					rest = append(rest, d)
				}
			}
			shown := append(about, rest...)
			if len(shown) > 8 {
				shown = shown[:8]
			}
			line := fmt.Sprintf("  declares (%d): %s", len(decl), strings.Join(shown, ", "))
			if len(decl) > 8 {
				line += " …"
			}
			Print(line)
		}
		near_ := topN(SortedKeys(info.Needs), 5)
		by := topN(SortedKeys(info.By), 5)
		if near_ != "" || by != "" {
			if near_ == "" {
				near_ = "—"
			}
			if by == "" {
				by = "—"
			}
			Printf("  needs (imports): %s; needed by: %s", near_, by)
		}
		var ts []string
		for t := range info.Tests {
			ts = append(ts, t)
		}
		sort.Strings(ts)
		if len(ts) > 0 {
			shown := ts
			more := ""
			if len(shown) > 6 {
				shown = shown[:6]
				more = " …"
			}
			Printf("  tests (%d): %s%s", len(ts), strings.Join(shown, " "), more)
		} else {
			Print("  tests (0): none import or name it")
		}
		if len(info.Docs) > 0 {
			docs := SortedKeys(info.Docs)
			if len(docs) > 5 {
				docs = docs[:5]
			}
			Print("  docs: " + strings.Join(docs, ", "))
		}
		log := Git(append([]string{"log", "-n", "2", "--format=%ad %h %s", "--date=short", "--"}, fs...)...)
		for _, ln := range strings.Split(log, "\n") {
			if strings.TrimSpace(ln) != "" {
				Print("  changed " + Short(ln, 110))
			}
		}
	}
	if len(also) > 0 {
		Print("\nalso:")
	}
	for _, c := range also {
		xs := append([]scored{}, per[c]...)
		sort.SliceStable(xs, func(i, j int) bool { return xs[i].s > xs[j].s })
		b := xs[0].b
		Printf("%s  %s %s:%d-%d — %s; %d tests", c, b.ID, b.Path, b.First, b.Last, Short(b.Purpose, 70), len(comps.M[c].Tests))
	}
	var checks []string
	for _, h := range hits {
		if IsTest(h.b.Path) && len(checks) < 3 {
			checks = append(checks, fmt.Sprintf("%s %s:%d-%d", h.b.ID, h.b.Path, h.b.First, h.b.Last))
		}
	}
	if len(checks) > 0 {
		Print("tests that say it: " + strings.Join(checks, "; "))
	}
	for _, r := range RecipesMatching(words) {
		Printf("recipe %s: %s (%s recipe %s)", r[0], r[1], CMD, r[0])
	}
	if len(untagged) > 0 {
		Printf("%d files carry no tag yet (%s gaps): ask <file> gives their declarations", len(untagged), CMD)
	}
	var first []string
	for _, h := range hits {
		if !IsTest(h.b.Path) {
			first = append(first, h.b.ID)
		}
	}
	first = Unique(first)
	if len(first) > 4 {
		first = first[:4]
	}
	if len(first) > 0 {
		Print("Next, one call for the whole first round (add every other question to it): " + CMD + " ask " + strings.Join(first, " "))
	}
	Print("End each change with: " + CMD + " check")
	SaveCache()
}

func topN(xs []string, n int) string {
	if len(xs) == 0 {
		return ""
	}
	shown := xs
	more := ""
	if len(shown) > n {
		shown = shown[:n]
		more = " …"
	}
	return strings.Join(shown, ", ") + more
}

// @end map.brief.print
