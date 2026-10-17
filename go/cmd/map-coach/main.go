// @map map.coach.remind: once and in the moment, after three reads of the map in a row, the reminder to ask every question of a round in one call
// map-coach: a post-tool hook (Claude Code's PostToolUse, Codex's too) that reminds the agent of the working loop when it
// drifts from it, once each time and never blocking. The Go version of python/map-coach.py.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

const reads = "Three reads of the map in a row (AGENTS.md, \"Finding code\"): ask in one call every question you can already " +
	"name, the blocks, names and line ranges these answers point to, and send the calls that do not depend on each other in one message."

var quiet = map[string]bool{"head": true, "tail": true, "cut": true, "wc": true, "echo": true, "grep": true, "sort": true, "uniq": true}
var heredocTag = regexp.MustCompile(`<<-?\s*'?(\w+)'?`)
var stepSplit = regexp.MustCompile(`&&|\|\||[;\n|]`)
var assigns = regexp.MustCompile(`^(\w+=\S+\s+)+`)
var mapScript = regexp.MustCompile(`map(?:\.py|\.mjs)$|(?:^|/)map$`)
var nonWord = regexp.MustCompile(`\W`)

func kind(tool string, given map[string]any) string {
	if tool != "Bash" {
		return "work"
	}
	cmd, _ := given["command"].(string)
	var lines []string
	end := ""
	for _, line := range strings.Split(cmd, "\n") {
		if end != "" {
			if strings.TrimSpace(line) == end {
				end = ""
			}
			continue
		}
		lines = append(lines, line)
		if m := heredocTag.FindStringSubmatch(line); m != nil {
			end = m[1]
		}
	}
	var words [][]string
	for _, step := range stepSplit.Split(strings.Join(lines, "\n"), -1) {
		step = assigns.ReplaceAllString(strings.TrimSpace(step), "")
		if step != "" && !strings.HasPrefix(step, "cd ") {
			f := strings.Fields(step)
			if len(f) > 2 {
				f = f[:2]
			}
			words = append(words, f)
		}
	}
	reads, quietN := 0, 0
	for _, w := range words {
		if (w[0] == "python3" || w[0] == "python" || w[0] == "node") && len(w) > 1 && mapScript.MatchString(w[1]) {
			reads++
		} else if mapScript.MatchString(w[0]) {
			reads++
		} else if quiet[w[0]] {
			quietN++
		}
	}
	if reads > 0 && reads+quietN == len(words) {
		return "map"
	}
	return "work"
}

func main() {
	defer func() { recover() }()
	var data map[string]any
	if json.NewDecoder(os.Stdin).Decode(&data) != nil || data == nil {
		return
	}
	if _, agent := data["agent_id"]; agent {
		return
	}
	sid, _ := data["session_id"].(string)
	if sid == "" {
		return
	}
	given, _ := data["tool_input"].(map[string]any)
	tool, _ := data["tool_name"].(string)
	k := kind(tool, given)
	dir := os.Getenv("MAP_COACH_DIR")
	if dir == "" {
		dir = filepath.Join(os.TempDir(), "map-coach")
	}
	name := nonWord.ReplaceAllString(sid, "")
	if len(name) > 64 {
		name = name[:64]
	}
	file := filepath.Join(dir, name+".json")
	state := map[string]int{"reads": 0}
	if b, err := os.ReadFile(file); err == nil {
		json.Unmarshal(b, &state)
	}
	if k == "map" {
		state["reads"]++
	} else {
		state["reads"] = 0
	}
	os.MkdirAll(dir, 0o755)
	if entries, err := os.ReadDir(dir); err == nil {
		for _, e := range entries {
			if info, err := e.Info(); err == nil && time.Since(info.ModTime()) > 3*24*time.Hour {
				os.Remove(filepath.Join(dir, e.Name()))
			}
		}
	}
	b, _ := json.Marshal(state)
	tmp := fmt.Sprintf("%s.%d", file, os.Getpid())
	if os.WriteFile(tmp, b, 0o644) == nil {
		os.Rename(tmp, file)
	}
	if state["reads"] == 3 {
		out, _ := json.Marshal(map[string]any{"hookSpecificOutput": map[string]any{"hookEventName": "PostToolUse", "additionalContext": reads}})
		fmt.Println(string(out))
	}
}
// @end map.coach.remind
