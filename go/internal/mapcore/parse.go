// @map map.core.parse: a file's tags into blocks, the problems found on the way, and every block of the repository
package mapcore

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"unicode/utf8"
)

type Block struct {
	ID      string `json:"id"`
	Purpose string `json:"purpose"`
	First   int    `json:"first"`
	Last    int    `json:"last"`
	Path    string `json:"path"`
	Own     int    `json:"own"`
	Lines   int    `json:"lines"`
}

type Problem struct {
	Path string
	Line int
	Text string
}

type Decl struct {
	Name  string `json:"name"`
	Kind  string `json:"kind"`
	First int    `json:"first"`
	Last  int    `json:"last"`
	What  string `json:"what"`
}

type Import struct {
	Line int    `json:"line"`
	What string `json:"what"`
}

type Facts struct {
	Key      string   `json:"key"`
	Blocks   []*Block `json:"blocks"`
	Problems [][2]any `json:"problems"`
	Outside  []int    `json:"outside"`
	Decls    []Decl   `json:"decls"`
	Imports  []Import `json:"imports"`
}

func (f *Facts) problems() []Problem {
	var out []Problem
	for _, p := range f.Problems {
		n := 0
		switch v := p[0].(type) {
		case float64:
			n = int(v)
		case int:
			n = v
		}
		out = append(out, Problem{"", n, fmt.Sprint(p[1])})
	}
	return out
}

// Parse: the blocks of one file (id, purpose, first and last line, own size), problems, lines outside any block.
func Parse(p, text string) ([]*Block, [][2]any, []int) {
	lines := strings.Split(text, "\n")
	if len(lines) > 0 && lines[len(lines)-1] == "" {
		lines = lines[:len(lines)-1]
	}
	var blocks, open []*Block
	var problems [][2]any
	form := Forms(p)
	if form == nil {
		return blocks, problems, nil
	}
	pat := TagPatterns(form)
	known := Areas()
	close := func(upto int, keep string, any_ bool) {
		for len(open) > 0 {
			top := open[len(open)-1]
			if !any_ && (keep == top.ID || strings.HasPrefix(keep, top.ID+".")) {
				break
			}
			top.Last = upto
			open = open[:len(open)-1]
		}
	}
	for k, line := range lines {
		n := k + 1
		kind, id, purpose, ok := TagMatch(pat, line)
		if !ok {
			if pat.looks.MatchString(line) {
				problems = append(problems, [2]any{n, `a tag that cannot be read: "@map <id>: <purpose>" or "@end <id>", alone on its line`})
			} else if strings.HasPrefix(line, "#!") && n > 1 {
				problems = append(problems, [2]any{n, "the #! line must stay the first line: put the tag below it"})
			}
			continue
		}
		if kind == "map" {
			if !known[strings.Split(id, ".")[0]] {
				problems = append(problems, [2]any{n, fmt.Sprintf("%s: its first word is not an area (%s); the file's area is %s", id, strings.Join(SortedKeys(known), ", "), AreaOf(p))})
			}
			if len(strings.Fields(purpose)) < 3 {
				problems = append(problems, [2]any{n, id + " needs a purpose of three words or more"})
			}
			for _, b := range blocks {
				if b.ID == id {
					problems = append(problems, [2]any{n, id + " appears twice in this file"})
					break
				}
			}
			close(n-1, id, false)
			b := &Block{ID: id, Purpose: purpose, First: n, Path: p}
			blocks = append(blocks, b)
			open = append(open, b)
		} else {
			found := false
			for _, b := range open {
				if b.ID == id {
					found = true
				}
			}
			if !found {
				problems = append(problems, [2]any{n, "@end " + id + " closes no open block"})
			} else {
				for len(open) > 0 {
					b := open[len(open)-1]
					open = open[:len(open)-1]
					b.Last = n
					if b.ID == id {
						break
					}
				}
			}
		}
	}
	close(len(lines), "", true)
	depth := make([]int, len(lines)+1)
	for _, b := range blocks {
		for i := b.First; i <= b.Last; i++ {
			depth[i]++
		}
	}
	for _, b := range blocks {
		mine := 0
		for _, o := range blocks {
			if o.First <= b.First && o.Last >= b.Last {
				mine++
			}
		}
		own := 0
		for i := b.First; i <= b.Last; i++ {
			if depth[i] == mine {
				own += utf8.RuneCountInString(lines[i-1]) + 1
			}
		}
		b.Own = own
		b.Lines = b.Last - b.First + 1
	}
	var outside []int
	for i := 1; i <= len(lines); i++ {
		if depth[i] == 0 && strings.TrimSpace(lines[i-1]) != "" {
			outside = append(outside, i)
		}
	}
	return blocks, problems, outside
}

type cacheFile struct {
	Version string            `json:"version"`
	Files   map[string]*Facts `json:"files"`
}

var cache *cacheFile
var cacheDirty bool

// FactsOf: a file's blocks, declarations, imports and problems, read once per change of the file (a cache in the temp folder).
func FactsOf(p string) *Facts {
	if cache == nil {
		cache = &cacheFile{Version: Version, Files: map[string]*Facts{}}
		if b, err := os.ReadFile(CacheFile("go")); err == nil {
			var c cacheFile
			if json.Unmarshal(b, &c) == nil && c.Version == Version && c.Files != nil {
				cache = &c
			}
		}
	}
	st, err := os.Stat(filepath.Join(ROOT, p))
	if err != nil {
		return &Facts{}
	}
	key := fmt.Sprintf("%d:%d:%s", st.ModTime().UnixNano(), st.Size(), AreaOf(p))
	if kept, ok := cache.Files[p]; ok && kept.Key == key {
		return kept
	}
	text := ReadFile(p)
	blocks, problems, outside := Parse(p, text)
	if blocks == nil {
		blocks = []*Block{}
	}
	if problems == nil {
		problems = [][2]any{}
	}
	if outside == nil {
		outside = []int{}
	}
	f := &Facts{Key: key, Blocks: blocks, Problems: problems, Outside: outside, Decls: DeclarationsIn(p, text), Imports: ImportsIn(p, text)}
	if f.Decls == nil {
		f.Decls = []Decl{}
	}
	if f.Imports == nil {
		f.Imports = []Import{}
	}
	cache.Files[p] = f
	cacheDirty = true
	return f
}

func SaveCache() {
	if cache == nil || !cacheDirty {
		return
	}
	keep := map[string]bool{}
	for _, p := range RepoFiles() {
		keep[p] = true
	}
	c := cacheFile{Version: Version, Files: map[string]*Facts{}}
	for p, f := range cache.Files {
		if keep[p] {
			c.Files[p] = f
		}
	}
	path := CacheFile("go")
	if os.MkdirAll(filepath.Dir(path), 0o755) != nil {
		return
	}
	b, err := json.Marshal(c)
	if err != nil {
		return
	}
	tmp := fmt.Sprintf("%s.%d.tmp", path, os.Getpid())
	if os.WriteFile(tmp, b, 0o644) == nil {
		os.Rename(tmp, path)
	}
}

// Everything: all blocks of the repository (copies), every problem with them, and the files that carry no tag yet.
func Everything() ([]*Block, []Problem, []string) {
	var all []*Block
	var problems []Problem
	var untagged []string
	for _, p := range Files() {
		f := FactsOf(p)
		for _, b := range f.Blocks {
			c := *b
			all = append(all, &c)
		}
		for _, pr := range f.problems() {
			pr.Path = p
			problems = append(problems, pr)
		}
		if len(f.Blocks) == 0 {
			untagged = append(untagged, p)
		} else if len(f.Outside) > UNTAGGED {
			problems = append(problems, Problem{p, f.Outside[0], fmt.Sprintf("%d lines outside blocks (at most %d); the first is this one", len(f.Outside), UNTAGGED)})
		}
		for _, b := range f.Blocks {
			if b.Own > LARGEST {
				problems = append(problems, Problem{p, b.First, fmt.Sprintf("%s holds %s characters of its own (at most %s): split it with blocks inside it", b.ID, Commas(b.Own), Commas(LARGEST))})
			}
		}
	}
	return all, problems, untagged
}

// @end map.core.parse
