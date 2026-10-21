// @map map.cli.init: init: the areas detected, map.json written, the section for AGENTS.md printed; and the command line
package mapcore

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const agentsSection = "## Finding code\n\n" +
	"Every block of code carries a tag naming it (`@map <area>.<topic>.<part>: what it does`), and the map is read\n" +
	"from the tags and the code: `map.yaml` (the areas and what each needs from the others) and `map/<area>.yaml`\n" +
	"(each area's components). The map, not grep, is how this repository is read. Every call of an agent re-reads the\n" +
	"whole conversation, so questions go in rounds: every question of a round in one call, each answered whole.\n\n" +
	"1. **Start with `{cmd} brief <the task's words>`**, as the code names things: the components\n" +
	"   the words name, their blocks and lines, what they declare, need and are needed by, their tests, docs and\n" +
	"   latest commits; then the first round of questions, as one call.\n" +
	"2. **Then one `ask` for each round of questions.** Write down every question the brief leaves open and ask them\n" +
	"   together; a later round asks only what the answers opened:\n" +
	"   `{cmd} ask <question> [<question> …] [--in <paths>] [--all]` reads and locates everything:\n" +
	"   a block id (its code), an identifier (what it is, the code declaring it, every line naming it), a file (whole,\n" +
	"   or its outline), a folder, `src/x.js:120-180`, `docs/X.md#heading`, `data.json#key`, `'src/**/*.css'`, or any\n" +
	"   text (every line holding it, by block or section). `--in` narrows the questions before it.\n" +
	"   Beside `ask`: `find <words>`, `history <id>` (its commits), `deps` and `impact <id or file>` (imports, and\n" +
	"   the tests to run), `recipe [name]` (the steps of a change across layers).\n" +
	"3. **Do not read or search the code and the docs with `grep`, `rg`, `sed`, `cat`, `head`, `tail`, `ls`, `find`,\n" +
	"   with a script that only prints them, or with a file-reading tool on whole files**: `ask` answers the same\n" +
	"   question, by block, with the code. Counting, computing over data, editing and other files go ahead; so does a\n" +
	"   range of lines before an edit.\n" +
	"4. **Tag what you add or move** (`https://github.com/mars1571/grepless/blob/main/docs/TAGGING.md`): a tag on the line above each block, in the file's comment form,\n" +
	"   `@end <id>` when other code follows it; keep purposes true. **End each change with `{cmd} check`**, which also\n" +
	"   checks that the map is current (`{cmd} build` writes it again).\n"

const usageText = "The code map: a map of the areas (map.yaml) and of each area's components (map/<area>.yaml), read from the tags\n" +
	"in the code; what agents ask it instead of grepping. Start a task with brief, read with ask, end each change with check.\n\n" +
	"    {cmd} build            write map.yaml (the areas) and map/<area>.yaml (each area's components)\n" +
	"    {cmd} check            the rules, and that the map matches the code (for CI); exit 1 when not\n" +
	"    {cmd} brief <words>    where a task starts: the components the words name, their blocks and lines, what\n" +
	"                                they declare, need and are needed by, their tests, docs and latest commits, then\n" +
	"                                the first round of questions to ask, in one call\n" +
	"    {cmd} pack [recipe] <words>   brief (and the recipe's steps) with that first round already answered, in one call\n" +
	"    {cmd} ask <question> [<question> …] [--in <paths>] [--all] [--budget N]\n" +
	"                                the one way to read and locate: every question of a round in one call, each\n" +
	"                                answered whole: a block id (its code), an identifier (what it is, the code declaring\n" +
	"                                it, every line naming it), a file (whole, or its outline), a folder, src/x.js:120-180,\n" +
	"                                docs/X.md#heading, data.json#key, 'src/**/*.css', or any text (every line holding it)\n" +
	"    {cmd} find <words>     blocks whose id, purpose or file has every word; an identifier first\n" +
	"    {cmd} history <id|file>      the commits that touched a block's lines (git log -L)\n" +
	"    {cmd} deps|impact <id|file>  what it imports; what imports it, and the tests to run\n" +
	"    {cmd} tests [paths | --changed]   the test files that reach these files, or the changed ones\n" +
	"    {cmd} recipe [name]    the steps of a change across layers (map.json, recipes), each at a block\n" +
	"    {cmd} plan <plan.md>   which parts of a plan can go to two agents at once\n" +
	"    {cmd} gaps [paths]     the files without tags, the lines outside blocks, the blocks to split\n" +
	"    {cmd} init             detect the areas, write map.json, print the section for AGENTS.md\n\n" +
	"Configuration, all of it optional, in map.json at the root ({cmd} init writes one): docs/CONFIG.md. The same\n" +
	"tool exists in Python, Node, Go and Rust, with the same answers (tests/conformance.py)."

func Usage() string { return strings.ReplaceAll(usageText, "{cmd}", CMD) }

// guardCommand: the guard's command beside the map's (python3 tools/map.py → python3 tools/map-guard.py, tools/map → tools/map-guard).
func guardCommand() string {
	words := strings.Fields(CMD)
	for k, w := range words {
		cut := strings.LastIndex(w, "/")
		name := w[cut+1:]
		if name == "map" || name == "map.py" || name == "map.mjs" {
			words[k] = w[:cut+1] + "map-guard" + name[3:]
			return strings.Join(words, " ")
		}
	}
	return "python3 tools/map-guard.py"
}

func Init(args []string) {
	counts := map[string]int{}
	var order []string
	for _, p := range Files() {
		a := AreaOf(p)
		if _, ok := counts[a]; !ok {
			order = append(order, a)
		}
		counts[a]++
	}
	sort.SliceStable(order, func(i, j int) bool { return counts[order[i]] > counts[order[j]] })
	var untagged []string
	for _, p := range Files() {
		if len(FactsOf(p).Blocks) == 0 {
			untagged = append(untagged, p)
		}
	}
	Printf("Root: %s (--root <path> or MAP_ROOT names another)", ROOT)
	force := false
	for _, a := range args {
		if a == "--force" {
			force = true
		}
	}
	if !IsFile("map.json") || force {
		cfg := NewOMap()
		cfg.Set("command", CMD)
		holds := NewOMap()
		for _, a := range order {
			holds.Set(a, "")
		}
		cfg.Set("holds", holds)
		hasRoot := false
		for _, p := range Files() {
			if AreaOf(p) == "root" {
				hasRoot = true
			}
		}
		if hasRoot {
			areas := NewOMap()
			areas.Set(".", "root")
			cfg.Set("areas", areas)
		}
		os.WriteFile(filepath.Join(ROOT, "map.json"), []byte(Jdump(cfg, 2, 0)+"\n"), 0o644)
		Printf(`map.json written: %d areas detected, each with an empty "holds" to fill in (one line: what the area holds).`, len(counts))
	} else {
		Print("map.json is there already (--force writes it again).")
	}
	var parts []string
	for _, a := range order {
		parts = append(parts, fmt.Sprintf("%s %d", a, counts[a]))
	}
	Print("Areas (code files each): " + strings.Join(parts, ", "))
	Printf("%d code files, %d tagged, %d without tags yet.", len(Files()), len(Files())-len(untagged), len(untagged))
	Print("")
	Printf("Next: 1. tag the code (https://github.com/mars1571/grepless/blob/main/docs/TAGGING.md; %s gaps lists what is left), 2. %s build, 3. paste this in AGENTS.md", CMD, CMD)
	Printf(`(CLAUDE.md imports it with a line "@AGENTS.md"), 4. install the guard: %s install <agent>.`, guardCommand())
	Print("")
	Print(strings.ReplaceAll(agentsSection, "{cmd}", CMD))
	SaveCache()
}

func printProblems(found []Problem) {
	for _, p := range found {
		if p.Line != 0 {
			Printf("%s:%d: %s", p.Path, p.Line, p.Text)
		} else {
			Printf("%s: %s", p.Path, p.Text)
		}
	}
}

func containsArg(args []string, want string) bool {
	for _, a := range args {
		if a == want {
			return true
		}
	}
	return false
}

// Main runs one command; it is what cmd/map calls.
func Main(argv []string) {
	argv = Setup(argv)
	command, rest := "check", []string{}
	if len(argv) > 0 {
		command, rest = argv[0], argv[1:]
	}
	if (command == "find" || command == "brief") && containsArg(rest, "--json") {
		JSONMode = true
		var words []string
		for _, w := range rest {
			if w != "--json" {
				words = append(words, w)
			}
		}
		if len(words) == 0 {
			Die(Usage())
		}
		saved := out
		out = bufio.NewWriterSize(io.Discard, 1<<16)
		more := 0
		if command == "find" {
			more = Find(words)
		} else {
			Brief(words, true)
		}
		out = saved
		if command == "find" {
			PrintJSON(Obj("declarations", recList("declarations"), "blocks", recList("blocks"), "more", more))
		} else {
			PrintJSON(briefDoc)
		}
		Flush()
		return
	}
	switch {
	case command == "find" && len(rest) > 0:
		Find(rest)
	case command == "deps" && len(rest) == 1:
		Deps(rest[0])
	case command == "impact" && len(rest) == 1:
		Impact(rest[0])
	case command == "history" && len(rest) == 1:
		History(rest[0])
	case command == "where" && len(rest) == 1:
		Where(rest[0])
	case command == "ask" && len(rest) > 0:
		Ask(rest)
	case command == "brief" && len(rest) > 0:
		Brief(rest, true)
	case command == "pack" && len(rest) > 0:
		Pack(rest)
	case command == "tests":
		Tests(rest)
	case command == "recipe" && len(rest) <= 1:
		name := ""
		if len(rest) == 1 {
			name = rest[0]
		}
		Recipe(name)
	case command == "plan" && len(rest) == 1:
		Plan(rest[0])
	case command == "gaps":
		Gaps(rest)
	case command == "init":
		Init(rest)
	case command == "build":
		found := Build()
		printProblems(found)
		if len(found) > 0 {
			Exit(1)
		}
	case command == "check":
		found, nBlocks, nUntagged := Problems()
		printProblems(found)
		line := fmt.Sprintf("%d blocks, %d problems", nBlocks, len(found))
		if nUntagged > 0 {
			line += fmt.Sprintf(", %d files without tags (%s gaps)", nUntagged, CMD)
		}
		Print(line)
		if len(found) > 0 {
			Exit(1)
		}
	case command == "help" || command == "-h" || command == "--help":
		Print(Usage())
	case command == "version" || command == "--version":
		Print(Version)
	default:
		Die(Usage())
	}
	Flush()
}

// @end map.cli.init
