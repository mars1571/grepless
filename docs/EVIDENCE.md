# The evidence

What the article and this repository claim, how each number was measured, and its limits. The data behind every
figure is in [article/data/](../article/data/), each file with its source; the figures are drawn from it by
[article/src/figures.py](../article/src/figures.py).

Two scopes:

- **113 sessions** (§1, §3): every Claude Code transcript on one machine with 20 or more model calls, from
  2026-09-21 to 2026-10-12. That is 36 sessions and the 77 sub-agents they started, in five projects:
  26,007 calls and 10.7 billion tokens of context. Measured by
  [article/analysis/transcripts.py](../article/analysis/transcripts.py), which anyone can run on their own
  transcripts.
- **One codebase** (§2, §4 to §9): the project where the map was built, an application of 403 code files and
  3,074 tagged blocks built with coding agents by one person, measured on its own sessions from 2026-10-03 to
  2026-10-12, and on its code on 2026-10-16. No comparative runs exist on other codebases or with other agents.

## 1. Tokens by kind, and what they cost

**Method.** Each call's usage as the transcript records it: input, cache-read and cache-write tokens (the
context), and output tokens. Each call priced at its model's list price from
[Anthropic's pricing page](https://platform.claude.com/docs/en/about-claude/pricing), read 2026-10-17. For
Claude Opus 5.5: $4 per million input tokens, $5 and $8 for 5-minute and 1-hour cache writes, $0.20 for cache
reads, $20 for output. For Claude Sonnet 5.5, half of each. Calls to other models, 3% of them, are priced as
Opus 5.5.

**Found.** 98.65% of the tokens were cache reads, context the model had already been sent; 1.05% cache writes;
0.30% output; uncached input under 0.01%. At list prices the 113 sessions come to about $3,383: 59.5% for cache
reads, 21.6% for cache writes, 18.9% for output. 85.7% of the calls went to Claude Opus 5.5 and 11.3% to Claude
Sonnet 5.5. ([scale.json](../article/data/scale.json))

## 2. What a call costs: the context it carries

**Method.** One session of 2026-10-12, read call by call (`map-sessions.py`): each call's context, as in §1.

**Found.** 716 calls read 380.3 million tokens. The first call carried 44k tokens. The context reached 967k at
call 310 and was compacted to 61k, then reached 937k and was compacted to 71k. The 405 calls that carried 500k tokens or
more (57% of the calls) read 77.2% of the total; calls under 200k read 2.5%, 200k to 500k 20.3%, 500k to
800k 48.7%, over 800k 28.6%. ([context-per-call.json](../article/data/context-per-call.json), Figure 1)

## 3. Response time by context

**Method.** In the 113 sessions, the seconds from the transcript line before each call (usually a tool's result)
to the call's last line, bucketed by the context the call carried. Calls under 0.3 s or over 300 s are left out,
which leaves 21,310 calls.

**Found.**

| Context | Calls | Median | Middle half | Median, replies under 200 tokens | Median reply, tokens |
|---|---|---|---|---|---|
| 0–100k | 1,930 | 2.67 s | 1.33–5.32 s | 2.25 s | 189 |
| 100–200k | 3,671 | 3.49 s | 1.52–7.59 s | 2.58 s | 242 |
| 200–300k | 3,155 | 4.18 s | 1.75–9.72 s | 2.89 s | 347 |
| 300–400k | 2,603 | 4.89 s | 2.09–11.91 s | 3.14 s | 483 |
| 400–500k | 2,519 | 6.02 s | 2.68–14.34 s | 3.88 s | 541 |
| 500–600k | 2,134 | 5.94 s | 2.90–13.43 s | 4.35 s | 535 |
| 600–700k | 1,905 | 6.64 s | 3.11–14.15 s | 4.11 s | 647 |
| 700–800k | 1,462 | 8.06 s | 3.76–16.19 s | 3.96 s | 736 |
| 800–900k | 1,182 | 8.08 s | 4.01–16.69 s | 4.04 s | 763 |
| 900k–1M | 749 | 7.30 s | 3.41–15.35 s | 3.71 s | 802 |

The median triples from the first bucket to 700–900k. Replies also grow longer with the context. Among replies
under 200 tokens, the median still rises from 2.25 s to about 4 s. Restricted to the 18,053 timed calls of one
model, Claude Opus 5.5, every bucket's median stays within 0.3 s of the all-calls median.
([latency-by-context.json](../article/data/latency-by-context.json), Figure 2)

## 4. What filled the context

**Method.** The context growth of 23 sub-agents of one day (2026-10-04, 1,183 M tokens), attributed to the tool
results that entered it, weighted by the calls that re-read each.

**Found.** The output of `grep`, `sed` and `cat` 37%; whole files read 13%; build output 12%; the agents' own
edits 9%; the map, an early version, 7%; tests 6%; screenshots 5%; other 11%. Reading code the old way was
half. ([where-context-went.json](../article/data/where-context-went.json), Figure 3)

## 5. What enters the context per question

**Method, 2026-10-16.** Six names an agent had looked up (a drawing routine, an undo handler, a toolbar painter,
a page event, a test helper, a menu action). For each, the bytes printed by `grep -rn <name> src` plus the whole
file that declares the name (what an agent reads next), against the bytes one `ask <name>` prints. An agent that
reads a slice of the file with `sed -n` instead of the whole reads less, in more calls.

**Found.** 281.7 KB against 1.7 KB; 281.6 against 1.6; 214.3 against 1.8; 213.9 against 3.1; 133.9 against 4.2;
17.8 against 11.0 (the test helper: short, and named in many tests).
([grep-vs-ask.json](../article/data/grep-vs-ask.json), Figure 7)

**Earlier, 2026-10-03.** Eight real questions across eight areas: 432,340 characters read with grep and whole
files, 83,850 through the map (19%); the right block came first in seven of the eight, second in the other.

**A caveat the other way.** When the guard replaced 470 recorded shell reads with their asks, the asks printed
36% more bytes than the commands they replaced (1,537 KB against 1,130 KB). A name's answer adds the code
declaring it and where it is named; an outline adds each block's functions. In 49 of those cases, a read the
agent made within its next four calls was already in the earlier answer. The saving is in calls, not in bytes
per call.

## 6. Reads through the map, before and after the guard

**Method.** Every session of the codebase with 20 or more calls that only searched or read (24 sessions,
2026-10-03 to 2026-10-12). Each call is classified as reading through the map (`map ask` and the other commands),
reading another way (`Read`, `Grep`, `Glob`, or a shell line made only of `grep`, `sed`, `cat`, `head`, `tail`,
`ls`, `find` and the like), or doing something else.

**Found.** With the "Finding code" section in `AGENTS.md` but no guard (2026-10-03 to 2026-10-11), the share of
reads through the map had a median of 10% over 20 sessions: 4% to 25% in sixteen, 1% in one, 48% to 66% in
three. With the guard (from 2026-10-12): 77%, 78%, 91% and 92%, a median of 85%. The sessions with the guard also had
revised instructions and the coach, both added on 2026-10-12, and a guard that refuses grep raises the share by
construction: this shows the habit changed at the tool level, not that the agents chose the map.

The guard was also replayed on the 1,148 recorded tool calls of five sessions of 2026-10-11. It refused 470
(every one a shell line) and named an ask for each, and every ask ran. 35 of them held a question that finds
nothing, a name the agent was guessing. Two shell lines that read code slipped through: a `for` loop over grep,
and `git show` into a scratch folder. The guard costs about 23 ms per tool call in Python, 2.8 to 3.2 ms compiled
(§9). ([sessions.json](../article/data/sessions.json), Figure 8)

**Not shown yet.** That the sessions make fewer calls. The guard moved the reads to the map, and the asks in the
sessions that followed carried 1.4 to 3.8 questions each (a round is several), but four sessions cannot show a
drop in calls. The coach that reminds the agent to ask in rounds was added on 2026-10-12 and has no measurement
yet.

## 7. One session replayed with the practices applied

**Method.** The session of §2 replayed call by call at the point it stood at 532 calls: 254.6 M tokens re-read,
94 minutes of model time, 141 of tool time, 19 runs of the whole test suite, one compaction at 967k. Replayed
unchanged, it reproduces 253.0 M and 95 minutes. Then each practice is applied in turn:

1. The checks that reach a change, instead of the whole suite after each change.
2. Reads after the first edit asked together with the round before: half, or two thirds, of them. The same
   answers enter the conversation, in fewer calls.
3. A fresh session at each change, starting near 60k tokens.

Each call's time is scaled by its new context: 5.3 s median under 300k and 6.4 s above 600k in this session.

**Found.** Checks per change and the suite once: tokens −2%, active time −26% (tool time from 141 to 81
minutes). With reads in rounds: tokens −33% to −43%, active time −40% to −44%, calls from 532 to 310–363. With a
session per change: tokens −77% to −81%, active time −43% to −46%. The session asked 286 questions in 243
calls to the map, 154 of them alone. Its fifth change began with 708k tokens of context, and its sixth with
778k. ([replay.json](../article/data/replay.json), Figure 9)

**Not counted.** Starting about ten sessions (a few calls each, about 1% of the tokens and five minutes), the
failures that others' unfinished work caused in a shared working tree, and the owner's time to start sessions.

## 8. Tokens and work time per 1,000 lines written, and the projection

**Method.** The 25 main sessions of the codebase with 20 or more calls that wrote code, read with
[article/analysis/rates.py](../article/analysis/rates.py). Lines written count every line the agent wrote to any
file: whole files, replacements, the new text of search-and-replace scripts, and here-documents. Rewrites count
again. Work time is the transcript's gaps that end in the model's answer (the model working) or in a tool's
result (the tool working). The time a session waits for the person is left out.

**Found.** 73,211 lines written, 4.13 billion tokens, 37.2 hours of work (17.0 of the model, 20.2 of tools):
56.4 million tokens and 30.5 minutes of work per 1,000 lines (56.38 and 30.48 before rounding). An earlier draft of the article used the sessions'
wall-clock span, 162 minutes per 1,000 lines; most of that span was the sessions waiting for the person, so it is
not used. ([rates.json](../article/data/rates.json))

**The projection (Figure 10).** 40 million lines at these rates: 2.26 trillion tokens and 28 months of one agent
working without pause. With the replay's reductions, each step added to the one before: 2.21 trillion tokens
(21 months) testing only what each change reaches; 1.29–1.51 trillion (16–17 months) with reads in rounds; and
0.43–0.52 trillion (15–16 months) with a session per change as well. 40 million is a round figure
of Chromium's size, not a count of it. Public counts seen in search results put Chromium at about 36 to 40 million
lines of code; Open Hub's page refused automated reads, so no count could be confirmed at its source. This is an extrapolation of one project's rates, not a
measurement.

## 9. The tool's own speed

**Method, 2026-10-16.** Wall time of each command on the codebase (403 code files, 3,074 blocks): the median of
three runs on a laptop, the parse cached between calls. Measured for both this generic tool and the codebase's
own earlier version of it, which also reads relations with Node and a JavaScript parser.

**Found.** This tool: build 0.64 s (2.0 s with a cold cache), check 0.65 s, brief 0.77 s, ask with one question
0.24 s, with eight 0.39 s, find 0.09 s, impact 0.16 s; the guard 23 ms per call. The earlier version: build
0.59 s, check 0.69 s, brief 0.70 s, ask 0.56 and 0.69 s, find 0.40 s, guard 31 ms. One ask of eight questions
printed 29 KB. ([timings.json](../article/data/timings.json))

The same measurements for the Python, Node, Go and Rust versions of this tool, on a generated codebase of 400
files: [LANGUAGES.md](LANGUAGES.md) and Figure 12.

## Limits of all of it

- One developer, one agent product (Claude Code), mostly one model.
- The sessions before and after the guard differ in their tasks, so the shares in §6 show a change of behaviour,
  not a controlled comparison, and the sample after the guard is four sessions.
- The replay in §7 is an estimate from one session, with the assumptions stated. The projection in §8
  extrapolates one project's rates.
- The bytes in §5 compare one habit (grep, then the whole file) with one ask; agents vary, and on the reads they
  actually made the asks printed more.
- Nothing here measures the quality of the work done, only what it cost.
