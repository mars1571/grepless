// @map map.sessions.read: a Claude Code transcript's model calls: the context each re-read, whether it only searched or read, its response time
// map-sessions: how the agents' sessions on this repository went, read from Claude Code's transcripts. The Go version of
// python/map-sessions.py, the same columns.   map-sessions [--since YYYY-MM-DD] [session-id-prefix …]
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/mars1571/grepless/go/internal/guard"
)

var look = map[string]bool{}
var mapCall = regexp.MustCompile(`map(?:\.py|\.mjs)?\s+(ask|brief|find|history|deps|impact|recipe|where)\b`)
var quietRx = regexp.MustCompile(`\d?>&\d|\d?>\s*/dev/null`)
var notRead = regexp.MustCompile(`\bsed\s+-i|>\s*\S|\bnode\b|\bmake\b|\bnpx\b`)
var pyCall = regexp.MustCompile(`\bpython3?\s+(\S*)`)
var askRx = regexp.MustCompile(`map(?:\.py|\.mjs)?\s+ask\s+`)
var stopRx = regexp.MustCompile(`\d?>|\||;|&&|\n`) // a redirection, a pipe or the next step

func init() {
	for _, w := range strings.Fields("grep egrep fgrep rg ag ack cat sed head tail awk nl less more ls find tree wc cut sort uniq tr xargs column echo printf") {
		look[w] = true
	}
}

func looks(tool string, given map[string]any) string {
	if tool == "Read" || tool == "Grep" || tool == "Glob" {
		return "other"
	}
	if tool != "Bash" {
		return ""
	}
	line, _ := given["command"].(string)
	if mapCall.MatchString(line) {
		return "map"
	}
	line = quietRx.ReplaceAllString(line, " ")
	if notRead.MatchString(line) {
		return ""
	}
	for _, m := range pyCall.FindAllStringSubmatch(line, -1) {
		if !strings.HasSuffix(m[1], "map.py") {
			return ""
		}
	}
	words := strings.Fields(strings.ReplaceAll(strings.ReplaceAll(strings.ReplaceAll(line, "|", " | "), ";", " ; "), "&&", " && "))
	var firsts []string
	for k, w := range words {
		if k == 0 || words[k-1] == "|" || words[k-1] == ";" || words[k-1] == "&&" || words[k-1] == "||" {
			firsts = append(firsts, w)
		}
	}
	if len(firsts) == 0 {
		return ""
	}
	for _, w := range firsts {
		if !look[filepath.Base(w)] && w != "cd" {
			return ""
		}
	}
	return "other"
}

func questions(line string) []int {
	var out []int
	for _, loc := range askRx.FindAllStringIndex(line, -1) {
		rest := line[loc[1]:]
		end := len(rest)
		if s := stopRx.FindStringIndex(rest); s != nil {
			end = s[0]
		}
		words := strings.Fields(rest[:end])
		n := 0
		for k, w := range words {
			if !strings.HasPrefix(w, "--") && (k == 0 || words[k-1] != "--in") {
				n++
			}
		}
		out = append(out, n)
	}
	return out
}

func stamp(s string) (float64, bool) {
	if s == "" {
		return 0, false
	}
	t, err := time.Parse(time.RFC3339Nano, s)
	if err != nil {
		return 0, false
	}
	return float64(t.Unix()) + float64(t.Nanosecond())/1e9, true // exact to the millisecond, as Python's
}

// said: the text of a tool's result: a string, or the text of its parts.
func said(content any) string {
	switch x := content.(type) {
	case string:
		return x
	case []any:
		var b strings.Builder
		for _, p := range x {
			if m, ok := p.(map[string]any); ok {
				if t, ok := m["text"].(string); ok {
					b.WriteString(t)
				}
			}
		}
		return b.String()
	}
	return ""
}

type kindOf struct{ id, kind string }

type call struct {
	ctx         int
	kinds       []kindOf
	since, last float64
	hasSince    bool
}

type row struct {
	ctx  int
	kind string
	secs float64
}

func calls(path string) ([]row, []int, int) {
	f, err := os.Open(path)
	if err != nil {
		return nil, nil, 0
	}
	defer f.Close()
	out := map[string]*call{}
	var order []string
	var asked []int
	type use struct {
		name string
		in   map[string]any
		cwd  string
	}
	uses := map[string]use{}
	refused := map[string]bool{}
	mapped := map[string]bool{}
	var prev float64
	hasPrev := false
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<28)
	for sc.Scan() {
		var o map[string]any
		if json.Unmarshal(sc.Bytes(), &o) != nil {
			continue
		}
		m, _ := o["message"].(map[string]any)
		t, hasT := stamp(fmt.Sprint(o["timestamp"]))
		if content, ok := m["content"].([]any); ok {
			for _, x := range content {
				if xm, ok := x.(map[string]any); ok && xm["type"] == "tool_result" {
					b, _ := json.Marshal(xm["content"])
					if strings.Contains(string(b), "through its map") {
						refused[fmt.Sprint(xm["tool_use_id"])] = true
					} else if strings.HasPrefix(said(xm["content"]), "== ") {
						mapped[fmt.Sprint(xm["tool_use_id"])] = true // the map's answer: a line the guard ran through the map
					}
				}
			}
		}
		id, _ := m["id"].(string)
		if o["type"] != "assistant" || id == "" {
			if hasT {
				prev, hasPrev = t, true
			}
			continue
		}
		cwd, _ := o["cwd"].(string)
		if cwd == "" {
			cwd = guard.ROOT
		}
		if content, ok := m["content"].([]any); ok {
			for _, x := range content {
				if xm, ok := x.(map[string]any); ok && xm["type"] == "tool_use" {
					in, _ := xm["input"].(map[string]any)
					name, _ := xm["name"].(string)
					uses[fmt.Sprint(xm["id"])] = use{name, in, cwd}
					if name == "Bash" {
						cmd, _ := in["command"].(string)
						n := 0
						for _, q := range questions(cmd) {
							n += q
						}
						if n > 0 {
							asked = append(asked, n)
						}
					}
				}
			}
		}
		u, _ := m["usage"].(map[string]any)
		c, ok := out[id]
		if !ok {
			c = &call{since: prev, hasSince: hasPrev, last: t}
			out[id] = c
			order = append(order, id)
		}
		if hasT {
			c.last = t
		}
		ctx := 0
		for _, k := range []string{"input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"} {
			if v, ok := u[k].(float64); ok {
				ctx += int(v)
			}
		}
		if ctx > c.ctx {
			c.ctx = ctx
		}
		if content, ok := m["content"].([]any); ok {
			for _, x := range content {
				if xm, ok := x.(map[string]any); ok && xm["type"] == "tool_use" {
					in, _ := xm["input"].(map[string]any)
					name, _ := xm["name"].(string)
					c.kinds = append(c.kinds, kindOf{fmt.Sprint(xm["id"]), looks(name, in)})
				}
			}
		}
		if hasT {
			prev, hasPrev = t, true
		}
	}
	outside := 0
	for id, u := range uses {
		if refused[id] || mapped[id] {
			continue
		}
		data := map[string]any{"tool_name": u.name, "tool_input": u.in, "cwd": u.cwd}
		if guard.Replacement("claude", data) != "" {
			outside++
		}
	}
	var rows []row
	for _, id := range order {
		c := out[id]
		kind := ""
		if len(c.kinds) > 0 {
			kind = "other"
			for _, ko := range c.kinds {
				k := ko.kind
				if mapped[ko.id] && k == "other" {
					k = "map"
				}
				if k == "" {
					kind = ""
					break
				}
				if k == "map" {
					kind = "map"
				}
			}
		}
		secs := 0.0
		if c.hasSince && c.last-c.since > 0 && c.last-c.since < 600 {
			secs = c.last - c.since
		}
		rows = append(rows, row{c.ctx, kind, secs})
	}
	return rows, asked, outside
}

func median(xs []float64) (float64, bool) {
	if len(xs) == 0 {
		return 0, false
	}
	s := append([]float64{}, xs...)
	sort.Float64s(s)
	return s[len(s)/2], true
}

func f1(x float64, ok bool) string {
	if !ok {
		return "-"
	}
	return fmt.Sprintf("%.1f", x)
}

// measure: one transcript: [calls, context, search/read calls, their context, via map, asks, questions, outside, runs],
// and its response times under and over 300k tokens.
func measure(p string) ([]int, []float64, []float64) {
	cs, asked, outside := calls(p)
	r := make([]int, 9)
	r[0] = len(cs)
	runs, run := 0, 0
	var lo, hi []float64
	for _, c := range cs {
		r[1] += c.ctx
		if c.kind != "" {
			r[2]++
			r[3] += c.ctx
			if c.kind == "map" {
				r[4]++
			}
			run++
		} else {
			if run >= 8 {
				runs++
			}
			run = 0
		}
		if c.secs > 0 {
			if c.ctx < 300000 {
				lo = append(lo, c.secs)
			} else {
				hi = append(hi, c.secs)
			}
		}
	}
	if run >= 8 {
		runs++
	}
	r[5] = len(asked)
	for _, a := range asked {
		r[6] += a
	}
	r[7] = outside
	r[8] = runs
	return r, lo, hi
}

// spend is a session's cost in USD and whether some model's price was unknown.
type spend struct {
	usd     float64
	unknown bool
}

// cost is the largest totalCostUSD of the session's cost-state records, or nil when it has none.
func cost(p string) *spend {
	f, err := os.Open(p)
	if err != nil {
		return nil
	}
	defer f.Close()
	var best *spend
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<28)
	for sc.Scan() {
		if !strings.Contains(sc.Text(), `"cost-state"`) {
			continue
		}
		var d map[string]any
		if json.Unmarshal(sc.Bytes(), &d) != nil || d["type"] != "cost-state" {
			continue
		}
		v, ok := d["totalCostUSD"].(float64)
		if !ok {
			continue
		}
		u := d["hasUnknownModelCost"] == true
		if best == nil {
			best = &spend{v, u}
		} else {
			best.usd, best.unknown = max(best.usd, v), best.unknown || u
		}
	}
	return best
}

func report(paths []string) {
	fmt.Printf("%-19s%6s%7s%8s%8s%16s%8s%8s%6s%6s%8s%8s%8s%8s\n", "session", "calls", "agents", "$", "read M", "search/read", "their M", "via map", "asks", "q/ask", "outside", "runs 8+", "s <300k", "s >300k")
	total := make([]int, 10)
	var allLo, allHi []float64
	var spent *spend
	line := func(name string, r []int, lo, hi []float64, usd *spend) {
		money := "-"
		if usd != nil {
			money = fmt.Sprintf("%.2f", usd.usd)
			if usd.unknown {
				money += "+"
			}
		}
		perAsk := 0.0
		if r[5] > 0 {
			perAsk = float64(r[6]) / float64(r[5])
		}
		ml, okl := median(lo)
		mh, okh := median(hi)
		share := fmt.Sprintf("%.0f", float64(r[2])/float64(r[0])*100) // a tie to the even digit, as Python's format
		fmt.Printf("%-19s%6d%7d%8s%8.1f%9d (%3s%%)%8.1f%8d%6d%6.1f%8d%8d%8s%8s\n", name, r[0], r[9], money, float64(r[1])/1e6, r[2], share, float64(r[3])/1e6, r[4], r[5], perAsk, r[7], r[8], f1(ml, okl), f1(mh, okh))
	}
	for _, p := range paths {
		// the subagents' calls are the session's
		subs, _ := filepath.Glob(filepath.Join(filepath.Dir(p), strings.TrimSuffix(filepath.Base(p), ".jsonl"), "subagents", "*.jsonl"))
		sort.Strings(subs)
		r := make([]int, 10)
		r[9] = len(subs)
		var lo, hi []float64
		for _, t := range append([]string{p}, subs...) {
			m, l, h := measure(t)
			for k := range m {
				r[k] += m[k]
			}
			lo, hi = append(lo, l...), append(hi, h...)
		}
		if r[0] == 0 {
			continue
		}
		for k := range r {
			total[k] += r[k]
		}
		allLo = append(allLo, lo...)
		allHi = append(allHi, hi...)
		day := ""
		if f, err := os.Open(p); err == nil {
			sc := bufio.NewScanner(f)
			sc.Buffer(make([]byte, 1<<20), 1<<28)
			for sc.Scan() {
				if strings.Contains(sc.Text(), `"timestamp"`) {
					var o map[string]any
					if json.Unmarshal(sc.Bytes(), &o) == nil {
						if ts, ok := o["timestamp"].(string); ok && len(ts) >= 10 {
							day = ts[:10]
						}
					}
					break
				}
			}
			f.Close()
		}
		stem := strings.TrimSuffix(filepath.Base(p), ".jsonl")
		if len(stem) > 8 {
			stem = stem[:8]
		}
		usd := cost(p)
		if usd != nil {
			if spent == nil {
				spent = &spend{usd.usd, usd.unknown}
			} else {
				spent.usd, spent.unknown = spent.usd+usd.usd, spent.unknown || usd.unknown
			}
		}
		line(day+" "+stem, r, lo, hi, usd)
	}
	if total[0] > 0 {
		line("all", total, allLo, allHi, spent)
	}
}

func firstStamp(p string) string {
	f, err := os.Open(p)
	if err != nil {
		return ""
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<28)
	for sc.Scan() {
		if strings.Contains(sc.Text(), `"timestamp"`) {
			var o map[string]any
			if json.Unmarshal(sc.Bytes(), &o) == nil {
				ts, _ := o["timestamp"].(string)
				return ts
			}
		}
	}
	return ""
}

func main() {
	guard.Setup()
	args := os.Args[1:]
	since := ""
	var named []string
	for i := 0; i < len(args); i++ {
		if args[i] == "--since" && i+1 < len(args) {
			since = args[i+1]
			i++
		} else {
			named = append(named, args[i])
		}
	}
	home, _ := os.UserHomeDir()
	projects := filepath.Join(home, ".claude", "projects")
	slug := strings.ReplaceAll(strings.ReplaceAll(guard.ROOT, "/", "-"), ".", "-")
	var found []string
	if entries, err := os.ReadDir(projects); err == nil {
		for _, e := range entries {
			if e.IsDir() && strings.HasPrefix(e.Name(), slug) {
				files, _ := os.ReadDir(filepath.Join(projects, e.Name()))
				for _, f := range files {
					if strings.HasSuffix(f.Name(), ".jsonl") {
						found = append(found, filepath.Join(projects, e.Name(), f.Name()))
					}
				}
			}
		}
	}
	sort.Slice(found, func(i, j int) bool {
		a, _ := os.Stat(found[i])
		b, _ := os.Stat(found[j])
		return a.ModTime().Before(b.ModTime())
	})
	if len(named) > 0 {
		var picked []string
		for _, a := range named {
			if strings.HasSuffix(a, ".jsonl") {
				picked = append(picked, a)
				continue
			}
			for _, p := range found {
				if strings.HasPrefix(filepath.Base(p), a) {
					picked = append(picked, p)
				}
			}
		}
		found = picked
	}
	if len(found) == 0 {
		fmt.Fprintf(os.Stderr, "No transcripts for %s under %s (Claude Code writes them there).\n", guard.ROOT, projects)
		os.Exit(1)
	}
	seen := map[string]bool{}
	var paths []string
	for _, p := range found {
		if seen[p] {
			continue
		}
		seen[p] = true
		if since == "" || firstStamp(p) >= since {
			paths = append(paths, p)
		}
	}
	report(paths)
}

// @end map.sessions.read
