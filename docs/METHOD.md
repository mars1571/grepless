# The method: fewer calls over a smaller context

The map is a tool, but what saved the tokens was a way of working that the tool makes the easy way. This page
says what that way is and why, with the numbers it was measured against ([EVIDENCE.md](EVIDENCE.md)).

## The cost of an agent is the sum of its contexts

Every call an agent makes to its model re-reads the whole conversation so far: the instructions, every tool
call, every tool result, every answer. Cached or not, that re-reading is what the bill and the latency follow.
In one real session of 716 calls, 380 million tokens were re-read, and the calls that carried 500k tokens of
context or more read 77% of them. Across 113 sessions, 98.7% of the tokens were context the model had already
been sent. The model also answered more slowly as the context grew: a median of 2.7 s under 100k tokens and about
8 s between 700k and 900k; for replies under 200 tokens, from 2.25 s to about 4 s
([EVIDENCE.md](EVIDENCE.md), [Figure 2](../article/images/02-response-time.png)).

Two things follow. **A call is expensive whatever it does**, so a call that only asks where a drawing routine is
costs almost what a call that edits a file costs. And **what enters the context stays**: the output of a
`grep -rn` over a folder, or a 280 KB file read whole, is paid again on every later call of the session.

So the aim is not a smaller answer per question but **fewer calls over a smaller context**: the same reading, in
fewer rounds, with less in each.

## The four practices

### 1. Start with `brief`, then read in rounds of `ask`

A task starts with `python3 tools/map.py brief <the task's words>`: the components those words name, each with
its blocks and their lines, what it declares, needs and is needed by, its tests, docs and latest commits, in
about a hundred lines. The brief ends with the first round of questions as one command.

Then the agent writes down every question the brief leaves open and asks them together:
`python3 tools/map.py ask <q> <q> <q> …`. Each question is answered whole (the block's code, a name's
declaration and the lines naming it, a section of a doc, a key of a JSON file), so no second call is needed to
read what the first one located. A later round asks only what the answers opened.

Why it works: the audited session asked 286 questions in 243 calls, 154 of them alone; replayed with the same
questions grouped as the rounds above, the tokens re-read fell by 33% to 43% and the active time by 40% to 44%
([Figure 9](../article/images/09-replayed-session.png)).

### 2. One session per change

A task of several changes is planned first (a Markdown plan with `## Part <n>` sections, each with its files),
and each part goes in a session of its own, started by the owner with the part's line. The audited session
built eight changes in one context: its fifth change began at 708k tokens and its sixth at 778k, so every call of
those changes re-read the earlier ones. Had each started a session of its own, the replay estimates 77% to 81%
fewer tokens re-read.

`python3 tools/map.py plan docs/plans/<file>.md` says which parts share no file and no import, so two agents can
build them at once, each in a git worktree of its own.

### 3. Check each change, run the suite once

A change ends with the checks that reach it (`python3 tools/map.py check`, the tests `impact` and `tests` name),
in a minute; the whole suite runs once per task, before the commit. By its 532nd call, the audited session had
run the whole suite 19 times; replayed with the checks that reach each change instead, its active time fell 26%.

### 4. A guard, and a coach

Instructions are context, and context fades: with the "Finding code" section in `AGENTS.md`, most sessions still
put 75% to 96% of their reads through `grep`, `sed` and `cat`. The guard (`map-guard.py`) is a pre-tool hook
that refuses those reads on the code and the docs and names the `ask` that answers the same question, with the
agent's own filters kept (`| cut`, `| sort`; a `| head` would cut the ask's answer, so it is dropped). Nothing else is refused: counting, editing (and the reads that check the
edit, in the same line), writing, tests, builds, other files, a range of lines before an edit. In Claude Code a
line whose every step only reads (the reads, `git status`, `which`, `--version`, `echo`, counts, filters) is not
refused but run through the map in its place, so a refusal costs no extra call; a line that also does something
else (`cargo`, `npm`, `git commit`) is refused whole with the same line to send again, its reads already through the map.
With the guard, 77% to 92% of the reads went through the map
([Figure 8](../article/images/08-instructions-and-hook.png)).

The coach (`map-coach.py`, optional) is a post-tool hook that says, once, after three reads of the map in a row,
to ask every question of the round in one call; a subagent's reads are counted apart from its session's. It never
blocks.

## Measure before claiming

`python3 tools/map-sessions.py` reads the agent's transcripts of the repository and prints, per session, the
calls, the tokens re-read, the calls that only searched or read, how many went through the map, the asks and
the questions per ask, the reads that ran outside the map, the runs of eight or more reading calls in a row, and
the median response time under and over 300k tokens. Run it before adopting the map, and again a week later.
What matters is the questions per ask (one is a call per question: the old way through a new door) and the
share of reads through the map; the tokens follow.

## What a tag is for

A tag names a block and says what it is for, in the words a task would use: not what the code does line by
line, but what a person looking for it would call it. `shop.cart.totals: the totals: each line's amount and
discount, the coupon on the rest, and the sum in cents` is found by "discount", "coupon" and "total";
`shop.cart.totals: helper functions` is found by nothing. The tool keeps the form of the tags true (every file
tagged, purposes of three words or more, ids unique, blocks small enough to read whole, the map current); the
truth of the purposes rests on the people and agents who change the code, which is why the instructions say to
tag what you add or move and to keep purposes true, and why `check` runs in CI. [TAGGING.md](TAGGING.md) has the
convention and the prompt that tags a codebase.

## Where this came from

An application of about 400 files, built with coding agents by one person over a few months. On 2026-10-03 every block got a tag and a map of the
whole repository was generated; on 2026-10-04 the map got relations and rules; on 2026-10-11 the owner saw the
agents still reading with `grep` one question per call, measured five sessions (43% of their calls only
searched or read, 109 of those 557 calls through the map), and the `ask` command and the guard were built that
day; on 2026-10-12 an audit of one session gave the replay estimates above and the practices of one session per
change and checks per change. This repository is that tool made general, with the same convention, for any
language and five agents.
