// @map map.recipes.steps: recipes from map.json, the steps of a change across layers, each checked against a block that still exists; plans whose parts can run at once
package mapcore

import (
	"fmt"
	"os"
	"regexp"
	"sort"
	"strings"
)

func recipeSteps(r *OMap) [][2]string {
	var out [][2]string
	if arr, ok := r.Vals["steps"].([]any); ok {
		for _, e := range arr {
			pair := strs(e)
			for len(pair) < 2 {
				pair = append(pair, "")
			}
			out = append(out, [2]string{pair[0], pair[1]})
		}
	}
	return out
}

func Recipe(name string) {
	rs := CFG.Recipes
	r, ok := rs.Vals[name].(*OMap)
	if name == "" || !ok {
		if name != "" {
			Printf("No recipe %s.", name)
		}
		for _, key := range rs.Keys {
			about := ""
			if m, ok := rs.Vals[key].(*OMap); ok {
				about = m.Str("about")
			}
			Printf("%s %s", PadR(key, 15), about)
		}
		if rs.Len() == 0 {
			Print("No recipes in map.json yet (docs/CONFIG.md says how to write one).")
		}
		return
	}
	blocks, _, _ := Everything()
	sorted := append([]*Block{}, blocks...)
	sort.SliceStable(sorted, func(i, j int) bool { return sorted[i].Path < sorted[j].Path })
	at := map[string]string{}
	for _, b := range sorted {
		if _, ok := at[b.ID]; !ok {
			at[b.ID] = fmt.Sprintf("%s:%d-%d", b.Path, b.First, b.Last)
		}
	}
	head := fmt.Sprintf("%s: %s.", name, r.Str("about"))
	if c := r.Str("checked"); c != "" {
		head += " Checked against " + c + "."
	}
	Print(head)
	for i, step := range recipeSteps(r) {
		Print(strings.TrimRight(fmt.Sprintf("%d. %s  %s", i+1, step[0], at[step[0]]), " ") + "\n   " + step[1])
	}
	if n := r.Str("note"); n != "" {
		Print("Note: " + n)
	}
}

func RecipesMatching(words []string) [][2]string {
	var out [][2]string
	for _, key := range CFG.Recipes.Keys {
		r, ok := CFG.Recipes.Vals[key].(*OMap)
		if !ok {
			continue
		}
		mine := map[string]bool{}
		for _, w := range strings.Fields(fmt.Sprint(r.Vals["words"])) {
			mine[w] = true
		}
		for _, w := range strings.Split(key, "-") {
			mine[w] = true
		}
		n := 0
		for _, w := range words {
			if mine[w] {
				n++
			}
		}
		if n >= 2 {
			out = append(out, [2]string{key, r.Str("about")})
		}
	}
	return out
}

func RecipeProblems(blocks []*Block) []Problem {
	ids := map[string]bool{}
	for _, b := range blocks {
		ids[b.ID] = true
	}
	var out []Problem
	for _, key := range CFG.Recipes.Keys {
		r, ok := CFG.Recipes.Vals[key].(*OMap)
		if !ok {
			continue
		}
		for _, step := range recipeSteps(r) {
			target := step[0]
			if strings.Contains(target, "/") || strings.HasSuffix(target, ".md") || strings.HasSuffix(target, ".txt") {
				if !Exists(target) {
					out = append(out, Problem{"map.json", 0, fmt.Sprintf("recipe %s names %s, which is not in the repository", key, target)})
				}
			} else if !ids[target] {
				out = append(out, Problem{"map.json", 0, fmt.Sprintf("recipe %s names the block %s, which no file tags: find where it went (%s find …)", key, target, CMD)})
			}
		}
	}
	return out
}

var SHARED = []string{"map/", "map.yaml", "CHANGELOG", "changes/", "docs/plans/"}
var partRx = regexp.MustCompile(`^## Part (\d+)\b[:.\s-]*(.*)`)
var filesRx = regexp.MustCompile(`^\s*-\s*Files:(.*)`)
var wsComma = regexp.MustCompile(`[\s,]+`)

type planPart struct {
	n     int
	title string
	files map[string]bool
}

func Plan(path string) {
	b, err := os.ReadFile(path)
	if err != nil {
		Die(path + ": " + err.Error())
	}
	var parts []*planPart
	var current *planPart
	for _, line := range strings.Split(string(b), "\n") {
		if m := partRx.FindStringSubmatch(line); m != nil {
			n := 0
			fmt.Sscanf(m[1], "%d", &n)
			current = &planPart{n, strings.TrimSpace(m[2]), map[string]bool{}}
			parts = append(parts, current)
		} else if strings.HasPrefix(line, "## ") {
			current = nil
		} else if current != nil {
			if m := filesRx.FindStringSubmatch(line); m != nil {
				for _, w := range wsComma.Split(m[1], -1) {
					x := strings.TrimRight(strings.Trim(w, "`*,;:()[]"), ".")
					if x != "" && (strings.Contains(x, "/") || IsFile(x)) {
						current.files[x] = true
					}
				}
			}
		}
	}
	if len(parts) == 0 {
		Die(path + `: no "## Part <n>: …" sections with a "- Files:" line each`)
	}
	blocks, _, _ := Everything()
	g := NewGraph(blocks)
	Printf("%s: %d parts", path, len(parts))
	var apart [][2]int
	for i, a := range parts {
		for _, bp := range parts[i+1:] {
			var common []string
			for f := range a.files {
				if bp.files[f] {
					shared := false
					for _, s := range SHARED {
						if strings.HasPrefix(f, s) {
							shared = true
						}
					}
					if !shared {
						common = append(common, f)
					}
				}
			}
			sort.Strings(common)
			why := ""
			if len(common) > 0 {
				why = "both change " + strings.Join(common, ", ")
			}
			if why == "" {
				for _, pair := range [][2]*planPart{{a, bp}, {bp, a}} {
					x, y := pair[0], pair[1]
					for _, f := range SortedKeys(x.files) {
						for t := range g.FileEdges[f] {
							if y.files[t] {
								why = fmt.Sprintf("part %d imports what part %d changes (%s)", x.n, y.n, f)
								break
							}
						}
						if why != "" {
							break
						}
					}
					if why != "" {
						break
					}
				}
			}
			if why != "" {
				Printf("  %d and %d: one after the other: %s", a.n, bp.n, why)
			} else {
				Printf("  %d and %d: at once", a.n, bp.n)
				apart = append(apart, [2]int{a.n, bp.n})
			}
		}
	}
	if len(apart) > 0 {
		var pairs []string
		for _, p := range apart {
			pairs = append(pairs, fmt.Sprintf("%d with %d", p[0], p[1]))
		}
		Print("At once: " + strings.Join(pairs, ", ") + " (each agent in a worktree of its own: git worktree add ../<name>-<part> -b <branch>)")
	} else {
		Print("No two parts can run at once: one agent after another, in order.")
	}
}

// @end map.recipes.steps
