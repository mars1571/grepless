// @map map.coach.remind: once and in the moment, after three reads of the map in a row, the reminder to ask every question of a round in one call
// map-coach: a post-tool hook that reminds the agent of the working loop when it drifts from it, once each time and
// never blocking. The Go version of python/map-coach.py, for the same five agents and with the same answers.
//
//	map-coach [--agent claude|codex|cursor|copilot|gemini]   the hook: stdin in, the reminder out
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

const reads = "Three reads of the map in a row (AGENTS.md, \"Finding code\"): ask in one call every question you can already " +
	"name, the blocks, names and line ranges these answers point to, and send the calls that do not depend on each other in one message."

// again is how many seconds apart the same call is still the same call (Cursor and Copilot CLI also run .claude/settings.json).
const again = 5.0

var quiet = map[string]bool{"head": true, "tail": true, "cut": true, "wc": true, "echo": true, "grep": true, "sort": true, "uniq": true}
var shell = map[string]bool{"Bash": true, "bash": true, "powershell": true, "Shell": true, "run_shell_command": true}
var heredocTag = regexp.MustCompile(`<<-?\s*'?(\w+)'?`)
var stepSplit = regexp.MustCompile(`&&|\|\||[;\n|]`)
var assigns = regexp.MustCompile(`^(\w+=\S+\s+)+`)
var mapScript = regexp.MustCompile(`map(?:\.py|\.mjs)$|(?:^|/)map$`)
var nonWord = regexp.MustCompile(`[^A-Za-z0-9_]`)

func str(v any) string {
	s, _ := v.(string)
	return s
}

// truthy is Python's truth of a JSON value: null, false, 0, "", [] and {} are false.
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
	case []any:
		return len(x) > 0
	case map[string]any:
		return len(x) > 0
	}
	return true
}

func kind(tool string, given map[string]any) string {
	if !shell[tool] {
		return "work"
	}
	cmd := str(given["command"])
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
	readsN, quietN := 0, 0
	for _, w := range words {
		if ((w[0] == "python3" || w[0] == "python" || w[0] == "node") && len(w) > 1 && mapScript.MatchString(w[1])) || mapScript.MatchString(w[0]) {
			readsN++
		} else if quiet[w[0]] {
			quietN++
		}
	}
	if readsN > 0 && readsN+quietN == len(words) {
		return "map"
	}
	return "work"
}

func detect(data map[string]any) string {
	_, version := data["cursor_version"]
	_, conversation := data["conversation_id"]
	if version || conversation {
		return "cursor"
	}
	_, toolName := data["toolName"]
	_, sessionID := data["sessionId"]
	if toolName || sessionID {
		return "copilot"
	}
	if str(data["hook_event_name"]) == "AfterTool" {
		return "gemini"
	}
	return "claude"
}

// normalise gives the call as one shape, whichever agent sent it: its session, its tool and the tool's input.
func normalise(agent string, data map[string]any) (string, string, map[string]any) {
	if agent == "copilot" {
		given, ok := data["toolArgs"]
		if !ok {
			given = data["tool_input"]
		}
		if s, ok := given.(string); ok {
			var parsed any
			if json.Unmarshal([]byte(s), &parsed) == nil {
				given = parsed
			} else {
				given = map[string]any{"command": s}
			}
		}
		g, _ := given.(map[string]any)
		session, tool := str(data["sessionId"]), str(data["toolName"])
		if session == "" {
			session = str(data["session_id"])
		}
		if tool == "" {
			tool = str(data["tool_name"])
		}
		return session, tool, g
	}
	session := str(data["session_id"])
	if agent == "cursor" {
		session = str(data["conversation_id"])
	}
	g, _ := data["tool_input"].(map[string]any)
	return session, str(data["tool_name"]), g
}

func answer(agent string) any {
	switch agent {
	case "cursor":
		return map[string]any{"additional_context": reads}
	case "copilot":
		return map[string]any{"additionalContext": reads}
	}
	event := "PostToolUse"
	if agent == "gemini" {
		event = "AfterTool"
	}
	return map[string]any{"hookSpecificOutput": map[string]any{"hookEventName": event, "additionalContext": reads}}
}

func main() {
	defer func() { recover() }() // a reminder is never worth a failed call
	agent := ""
	for i, a := range os.Args[1:] {
		if a == "--agent" {
			if i+2 < len(os.Args) {
				agent = os.Args[i+2]
			}
			break
		}
	}
	input, err := io.ReadAll(os.Stdin)
	if err != nil {
		return
	}
	var data map[string]any
	if json.Unmarshal(input, &data) != nil || data == nil || truthy(data["agent_id"]) {
		return // a subagent's calls are its own business
	}
	if agent == "" {
		agent = detect(data)
	}
	session, tool, given := normalise(agent, data)
	if session == "" {
		return
	}
	if given == nil {
		given = map[string]any{}
	}
	call := str(given["command"])
	if call == "" {
		call = str(given["file_path"])
	}
	if call == "" {
		call = str(given["path"])
	}
	dir := os.Getenv("MAP_COACH_DIR")
	if dir == "" {
		dir = filepath.Join(os.TempDir(), "map-coach")
	}
	name := nonWord.ReplaceAllString(session, "")
	if len(name) > 64 {
		name = name[:64]
	}
	file := filepath.Join(dir, name+".json")
	state := map[string]any{}
	if b, err := os.ReadFile(file); err == nil {
		json.Unmarshal(b, &state)
	}
	now := float64(time.Now().UnixNano()) / 1e9
	at, _ := state["at"].(float64)
	if call != "" && str(state["last"]) == call && now-at >= 0 && now-at < again {
		return // the same call, from a second source
	}
	f, _ := state["reads"].(float64)
	n := int(f)
	if kind(tool, given) == "map" {
		n++
	} else {
		n = 0
	}
	os.MkdirAll(dir, 0o755)
	if entries, err := os.ReadDir(dir); err == nil {
		for _, e := range entries {
			if info, err := e.Info(); err == nil && time.Since(info.ModTime()) > 3*24*time.Hour {
				os.Remove(filepath.Join(dir, e.Name()))
			}
		}
	}
	b, _ := json.Marshal(map[string]any{"reads": n, "last": call, "at": now})
	tmp := fmt.Sprintf("%s.%d", file, os.Getpid())
	if os.WriteFile(tmp, b, 0o644) == nil {
		os.Rename(tmp, file)
	}
	if n == 3 {
		out, _ := json.Marshal(answer(agent))
		fmt.Println(string(out))
	}
}

// @end map.coach.remind
