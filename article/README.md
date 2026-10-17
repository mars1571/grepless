# The article

`medium.md` is the article as it goes on Medium. Every figure in it is drawn from the measured data in `data/`,
and every number in the text comes from the same files; [docs/EVIDENCE.md](../docs/EVIDENCE.md) says how each was
measured.

| Folder | Holds |
|---|---|
| `data/` | the measurements, one JSON file each, with its source and method in the file |
| `analysis/` | the two scripts that measure Claude Code transcripts: `transcripts.py` (scale, tokens by kind, cost, response time) and `rates.py` (tokens and work time per 1,000 lines written) |
| `src/` | `figures.py` (each figure as an HTML page, from `data/`), `render.mjs` (the pages to PNG and GIF with Playwright and Chrome), `gif.mjs` (the GIF encoder, no dependency) |
| `images/` | the rendered figures: PNG at twice their size, the animated session as a GIF, and the three preview cards |
| `package.json` | the one dependency of the rendering, Playwright, pinned (`package-lock.json`) |

The measurements, from the transcripts of the project where the map was built (they cannot be run again here;
`data/` keeps what they gave):

```sh
python3 article/analysis/transcripts.py --until 2026-10-12 --exclude <this article's session> --out article/data
python3 article/analysis/rates.py --project ~/.claude/projects/<project folder> --exclude <…> --out article/data
```

The figures, from `data/`:

```sh
python3 article/src/figures.py                   # the pages, in article/src/html/
cd article && npm install                        # Playwright, into article/node_modules/
npx playwright install chromium                  # only without Google Chrome, which render.mjs uses when it is installed
node src/render.mjs                              # the images, into article/images/
node src/render.mjs --out /tmp/figures           # or into another folder, to compare with article/images/ first
```

With Playwright 1.64.1 and Chrome 155 on macOS, the render reproduces every file of `images/` byte for byte. Another
browser version or system can move a few pixels of antialiasing; such a change alone is no reason to replace an
image.

## The figures

| File | In the article | What it shows |
|---|---|---|
| `01-context-per-call.png` | Figure 1, and the featured image | the context of each call of one 716-call session |
| `02-response-time.png` | Figure 2 | median seconds to reply by context size, all calls and short replies |
| `03-what-filled-the-context.png` | Figure 3 | what 23 agents re-read, by kind of tool result |
| `04-how-it-works.png` | Figure 4 | the code, the map, the agent and the hook |
| `05-method-on-an-example.png` | Figure 5 | the four parts on the example project |
| `06-hook-and-ask.gif` | Figure 6 | the hook refusing grep and one ask answering |
| `07-one-lookup.png` | Figure 7 | text returned for six lookups, grep and file against one ask |
| `08-instructions-and-hook.png` | Figure 8 | each session's share of reads through the map |
| `09-replayed-session.png` | Figure 9 | one session replayed with each practice added |
| `10-projection.png` | Figure 10 | the projection to 40 million lines |
| `11-related-tools.png` | Figure 11 | related tools, as their own pages describe them |
| `12-four-implementations.png` | Figure 12 | run time of the four implementations |
| `og-image.png` | not in the article | 1200×630, for links to the repository's site |
| `social-preview.png` | not in the article | 1280×640, GitHub's social preview for the repository |
| `devto-cover.png` | not in the article | 1000×420, the cover for the dev.to cross-post |

The design is the one of a research report: white, a title that says what is plotted, the sample and the finding
in the subtitle, the source under the plot, grey for the sessions as they ran and one blue for the map. The PNGs
are 1,720 px wide: Medium shows them about 680 px wide, so the type is drawn about a quarter larger than it
displays, and they stay sharp on high-density screens.

## Publishing on Medium

Medium's editor takes no Markdown file, so the article goes in by hand. From Medium's help pages (read
2026-10-16 and 2026-10-17):

1. **Write** starts a draft. The first line is the title, the second the subtitle.
2. Paste the text section by section. A code block is three backticks on an empty line; inline code is one
   backtick. Medium has no tables, which is why the article uses lists.
3. Where `medium.md` has `![alt text](images/…)`, insert that file (the `+` on an empty line, then the image
   icon). Medium takes JPG, PNG and GIF up to 25 MB, and images at least 1,192 px wide fit every layout.
   - Select the image, choose **Alt text**, and paste the text between the brackets.
   - Type the caption, the italic line under the image in `medium.md`, under the image.
4. Before publishing, open **⋯ > More settings**:
   - **SEO title** (Medium cuts it past 60 characters; 40 to 50 is best):
     `Where a coding agent's tokens go: 113 sessions` (46 characters).
   - **SEO description** (140 to 156 characters):
     `In 113 coding-agent sessions, 98.7% of 10.7 billion tokens were context the model had already read. What filled it, what it cost, and a first test of a fix.` (156 characters).
   - **Custom link**, which can only be set before publishing: `coding-agent-tokens-re-read`.
5. **Featured image**: Figure 1 (select it and use the featured-image option, or Shift+F). Its preview title and
   subtitle can be changed with **Change display title / subtitle** if the full title is too long for cards.
6. **Topics** (up to five): Claude Code, AI Agents, Software Engineering, Developer Tools, Large Language Models.
7. If the article is also published elsewhere first (the repository's site, a blog), set it as **originally
   published elsewhere**, so Medium's page points search engines to the original.

### Before publishing: write it in your own voice

Medium's Boost, the curation that puts stories in front of more readers, leaves out stories generated by AI,
content marketing, press releases, and stories written to drive signups or traffic. This draft was written with an
agent. Rewrite it in your own words, keep the numbers and their sources as they are, and keep the tone of a report
rather than an announcement. The repository link at the end is enough; the article should not ask anyone to
install anything.

### After publishing

The repository's `PROMOTION.md` has the texts for GitHub, Hacker News, Reddit, LinkedIn and dev.to, each written
to the rules of the place it goes.
