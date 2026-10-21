// @map map.cli.init: init: the areas detected, map.json written, the section for AGENTS.md printed; and the command line
use crate::ask::ask;
use crate::brief::{brief, pack};
use crate::config::*;
use crate::files::*;
use crate::parse::{facts, save_cache, Problem};
use crate::query::{deps, find, gaps, history, impact, tests, where_cmd};
use crate::recipes::{plan, recipe};
use crate::write::{build, problems};
use serde_json::{json, Map, Value};

const AGENTS_SECTION: &str = "## Finding code

Every block of code carries a tag naming it (`@map <area>.<topic>.<part>: what it does`), and the map is read
from the tags and the code: `map.yaml` (the areas and what each needs from the others) and `map/<area>.yaml`
(each area's components). The map, not grep, is how this repository is read. Every call of an agent re-reads the
whole conversation, so questions go in rounds: every question of a round in one call, each answered whole.

1. **Start with `{cmd} brief <the task's words>`**, as the code names things: the components
   the words name, their blocks and lines, what they declare, need and are needed by, their tests, docs and
   latest commits; then the first round of questions, as one call.
2. **Then one `ask` for each round of questions.** Write down every question the brief leaves open and ask them
   together; a later round asks only what the answers opened:
   `{cmd} ask <question> [<question> …] [--in <paths>] [--all]` reads and locates everything:
   a block id (its code), an identifier (what it is, the code declaring it, every line naming it), a file (whole,
   or its outline), a folder, `src/x.js:120-180`, `docs/X.md#heading`, `data.json#key`, `'src/**/*.css'`, or any
   text (every line holding it, by block or section). `--in` narrows the questions before it.
   Beside `ask`: `find <words>`, `history <id>` (its commits), `deps` and `impact <id or file>` (imports, and
   the tests to run), `recipe [name]` (the steps of a change across layers).
3. **Do not read or search the code and the docs with `grep`, `rg`, `sed`, `cat`, `head`, `tail`, `ls`, `find`,
   with a script that only prints them, or with a file-reading tool on whole files**: `ask` answers the same
   question, by block, with the code. Counting, computing over data, editing and other files go ahead; so does a
   range of lines before an edit.
4. **Tag what you add or move** (`https://github.com/mars1571/grepless/blob/main/docs/TAGGING.md`): a tag on the line above each block, in the file's comment form,
   `@end <id>` when other code follows it; keep purposes true. **End each change with `{cmd} check`**, which also
   checks that the map is current (`{cmd} build` writes it again).
";

const USAGE: &str = "The code map: a map of the areas (map.yaml) and of each area's components (map/<area>.yaml), read from the tags
in the code; what agents ask it instead of grepping. Start a task with brief, read with ask, end each change with check.

    {cmd} build            write map.yaml (the areas) and map/<area>.yaml (each area's components)
    {cmd} check            the rules, and that the map matches the code (for CI); exit 1 when not
    {cmd} brief <words>    where a task starts: the components the words name, their blocks and lines, what
                                they declare, need and are needed by, their tests, docs and latest commits, then
                                the first round of questions to ask, in one call
    {cmd} pack [recipe] <words>   brief (and the recipe's steps) with that first round already answered, in one call
    {cmd} ask <question> [<question> …] [--in <paths>] [--all] [--budget N]
                                the one way to read and locate: every question of a round in one call, each
                                answered whole: a block id (its code), an identifier (what it is, the code declaring
                                it, every line naming it), a file (whole, or its outline), a folder, src/x.js:120-180,
                                docs/X.md#heading, data.json#key, 'src/**/*.css', or any text (every line holding it)
    {cmd} find <words>     blocks whose id, purpose or file has every word; an identifier first
    {cmd} history <id|file>      the commits that touched a block's lines (git log -L)
    {cmd} deps|impact <id|file>  what it imports; what imports it, and the tests to run
    {cmd} tests [paths | --changed]   the test files that reach these files, or the changed ones
    {cmd} recipe [name]    the steps of a change across layers (map.json, recipes), each at a block
    {cmd} plan <plan.md>   which parts of a plan can go to two agents at once
    {cmd} gaps [paths]     the files without tags, the lines outside blocks, the blocks to split
    {cmd} init             detect the areas, write map.json, print the section for AGENTS.md

Configuration, all of it optional, in map.json at the root ({cmd} init writes one): docs/CONFIG.md. The same
tool exists in Python, Node, Go and Rust, with the same answers (tests/conformance.py).";

pub fn usage() -> String { USAGE.replace("{cmd}", cmd()) }

/// The guard's command beside the map's: python3 tools/map.py → python3 tools/map-guard.py, tools/map → tools/map-guard.
fn guard_command() -> String {
    let mut words: Vec<String> = cmd().split_whitespace().map(String::from).collect();
    let cut = |w: &str| w.rfind('/').map(|i| i + 1).unwrap_or(0);
    match words.iter().position(|w| matches!(&w[cut(w)..], "map" | "map.py" | "map.mjs")) {
        Some(k) => {
            let at = cut(&words[k]);
            words[k] = format!("{}map-guard{}", &words[k][..at], &words[k][at + 3..]);
            words.join(" ")
        }
        None => "python3 tools/map-guard.py".into(),
    }
}

pub fn init(args: &[String]) {
    let mut counts: Vec<(String, usize)> = Vec::new();
    for p in files() {
        let a = area_of(p);
        match counts.iter_mut().find(|(k, _)| *k == a) { Some(e) => e.1 += 1, None => counts.push((a, 1)) }
    }
    counts.sort_by_key(|c| std::cmp::Reverse(c.1));
    let untagged: Vec<&String> = files().iter().filter(|p| facts(p).blocks.is_empty()).collect();
    print(&format!("Root: {} (--root <path> or MAP_ROOT names another)", root().display()));
    if !is_file("map.json") || args.iter().any(|a| a == "--force") {
        let mut cfgm = Map::new();
        cfgm.insert("command".into(), json!(cmd()));
        let mut holds = Map::new();
        for (a, _) in &counts {
            holds.insert(a.clone(), json!(""));
        }
        cfgm.insert("holds".into(), Value::Object(holds));
        if files().iter().any(|p| area_of(p) == "root") {
            let mut areas = Map::new();
            areas.insert(".".into(), json!("root"));
            cfgm.insert("areas".into(), Value::Object(areas));
        }
        let _ = std::fs::write(root().join("map.json"), format!("{}\n", jdump(&Value::Object(cfgm), 2, 0)));
        print(&format!("map.json written: {} areas detected, each with an empty \"holds\" to fill in (one line: what the area holds).", counts.len()));
    } else {
        print("map.json is there already (--force writes it again).");
    }
    print(&format!("Areas (code files each): {}", counts.iter().map(|(a, n)| format!("{} {}", a, n)).collect::<Vec<_>>().join(", ")));
    print(&format!("{} code files, {} tagged, {} without tags yet.", files().len(), files().len() - untagged.len(), untagged.len()));
    print("");
    print(&format!("Next: 1. tag the code (https://github.com/mars1571/grepless/blob/main/docs/TAGGING.md; {} gaps lists what is left), 2. {} build, 3. paste this in AGENTS.md", cmd(), cmd()));
    print(&format!("(CLAUDE.md imports it with a line \"@AGENTS.md\"), 4. install the guard: {} install <agent>.", guard_command()));
    print("");
    print(&AGENTS_SECTION.replace("{cmd}", cmd()));
    save_cache();
}

fn print_problems(found: &[Problem]) {
    for p in found {
        if p.line != 0 { print(&format!("{}:{}: {}", p.path, p.line, p.text)); } else { print(&format!("{}: {}", p.path, p.text)); }
    }
}

/// Runs one command; it is what the map binary calls.
pub fn main(argv: Vec<String>) {
    let argv = setup(argv);
    let (command, rest): (String, Vec<String>) = if argv.is_empty() { ("check".into(), vec![]) } else { (argv[0].clone(), argv[1..].to_vec()) };
    match command.as_str() {
        "find" | "brief" if rest.iter().any(|a| a == "--json") => {
            set_json(true);
            let rest: Vec<String> = rest.into_iter().filter(|a| a != "--json").collect();
            if rest.is_empty() { die(&usage()); }
            if command == "find" {
                let more = find(&rest);
                let mut doc = Map::new();
                for k in ["declarations", "blocks"] { doc.insert(k.into(), json!([])); }
                for (k, v) in take_rec() { doc.insert(k, v); }
                doc.insert("more".into(), json!(more));
                print_json(&Value::Object(doc));
            } else {
                brief(&rest, true);
            }
        }
        "find" if !rest.is_empty() => { find(&rest); }
        "deps" if rest.len() == 1 => deps(&rest[0]),
        "impact" if rest.len() == 1 => impact(&rest[0]),
        "history" if rest.len() == 1 => history(&rest[0]),
        "where" if rest.len() == 1 => where_cmd(&rest[0]),
        "ask" if !rest.is_empty() => ask(&rest),
        "brief" if !rest.is_empty() => { brief(&rest, true); }
        "pack" if !rest.is_empty() => pack(&rest),
        "tests" => tests(&rest),
        "recipe" if rest.len() <= 1 => recipe(rest.first().map(|s| s.as_str()).unwrap_or("")),
        "plan" if rest.len() == 1 => plan(&rest[0]),
        "gaps" => gaps(&rest),
        "init" => init(&rest),
        "build" => {
            let found = build();
            print_problems(&found);
            if !found.is_empty() { exit(1); }
        }
        "check" => {
            let (found, n_blocks, n_untagged) = problems();
            print_problems(&found);
            let mut line = format!("{} blocks, {} problems", n_blocks, found.len());
            if n_untagged > 0 { line.push_str(&format!(", {} files without tags ({} gaps)", n_untagged, cmd())); }
            print(&line);
            if !found.is_empty() { exit(1); }
        }
        "help" | "-h" | "--help" => print(&usage()),
        "version" | "--version" => print(VERSION),
        _ => die(&usage()),
    }
    flush();
}
// @end map.cli.init
