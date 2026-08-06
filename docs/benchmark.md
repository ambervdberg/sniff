# Does sniff actually save tokens?

Short answer: yes, and the size of the saving depends entirely on how vague the
question is.

This page reports a head to head measurement: the same coding agent, on the same
repository, answering the same question, with and without sniff available. Every
number below comes from a recorded run, and the caveats at the bottom are part
of the result, not an apology for it.

## Headline

Sixteen runs, two repositories, four questions, both arms, one run each.

| | Without sniff | With sniff |
|---|---|---|
| Total cost | $6.69 | $1.35 |
| Files read | 112 | 1 |
| Tool calls | 297 | 26 |
| Verified claims made | 149 | 504 |

sniff answered every question for between $0.07 and $0.24, whatever the
repository and whatever the question. The unaided agent ranged from $0.13 to
$3.07, because its cost is a function of how much of the repository the question
makes it read.

## Cost, question by question

| Repo | Question | Without sniff | With sniff | Ratio |
|---|---|---|---|---|
| excalidraw | Find all code smells in this repo. | $2.087 | $0.239 | 8.7x |
| excalidraw | Where should I start refactoring? | $0.310 | $0.136 | 2.3x |
| excalidraw | Give me the top 10 largest functions. | $0.235 | $0.070 | 3.4x |
| excalidraw | Which parts are the most complex? | $0.303 | $0.189 | 1.6x |
| scrapy | Find all code smells in this repo. | $3.071 | $0.217 | 14.2x |
| scrapy | Where should I start refactoring? | $0.303 | $0.221 | 1.4x |
| scrapy | Give me the top 10 largest functions. | $0.134 | $0.105 | 1.3x |
| scrapy | Which parts are the most complex? | $0.245 | $0.173 | 1.4x |

The pattern is consistent: **the vaguer the question, the larger the saving.**
"Find all code smells" has no obvious stopping point, so the unaided agent read
32 files on excalidraw and 70 on scrapy, spending 112 and 124 tool calls. A
precise question like "the top 10 largest functions" tells it exactly where to
stop, and the gap narrows to 1.3x.

## Quality

Cheap answers are worthless if they are wrong, so quality was scored before cost
was celebrated.

**Accuracy: a tie.** Every file, symbol and line number in all 16 answers was
checked against the source. Of 504 checkable claims from sniff, 0 were wrong. Of
149 from the unaided agent, 4 were wrong, and reading those four by hand they are
all the scorer mis-attributing a symbol inside a dense list, not the agent
inventing anything. Both arms stayed accurate. The cost saving is not bought with
hallucination.

**Specificity: a clear win.** sniff produced 504 checkable claims to the unaided
agent's 149, so more than three times as many concrete, verifiable statements for
a fifth of the money.

**Agreement with an independent reference.** For the two questions with an
objective answer, the reference ranking was generated separately using
[lizard](https://github.com/terryyin/lizard), which shares no code with sniff.
On scrapy:

| Question | Without sniff | With sniff |
|---|---|---|
| Top 10 largest functions | 3 of 10 | 6 of 10 |
| Most complex functions | 0 of 10 | 10 of 10 |

The 0 of 10 needs context and is not as damning as it looks: the unaided agent
answered at module level ("the dual async model", "the Twisted interop layer")
rather than naming functions. That is a defensible reading of "which parts are
the most complex". It is still an answer you cannot act on directly.

## What sniff does not find

The unaided agent reported five kinds of smell that no sniff detector can
produce. This is the one dimension where reading the whole repository wins.

| Found without sniff | Why sniff misses it |
|---|---|
| Duplicated logic: sync/async twin methods, a `peek()` implementation copy-pasted across three classes | sniff detects duplicate string literals only, never duplicated code |
| Reaching into other modules' private internals | no rule for underscore-attribute access on a non-self receiver |
| Shared mutable state: class attributes used as instance state, globals rebound at runtime | no rule beyond mutable default arguments |
| Magic numbers | no rule |
| Self-admitted debt: TODO comments, "hopefully temporary" design notes | no TODO/FIXME/HACK detector |

There is also a difference in shape. The unaided agent finishes with themes
("most of this is left over from the asyncio migration"). sniff finishes with ten
ranked tables. Ranking is not synthesis, and an agent reading sniff's output
still has to do that part.

## Method

**Repositories**, pinned by commit and cloned with full history:

| Repo | Language | Commit | Files | Lines |
|---|---|---|---|---|
| excalidraw | TypeScript, TSX | `786ab26` | 654 | 188k |
| scrapy | Python | `a499dc9` | 475 | 84k |

**Both arms** ran Claude Code non-interactively on Sonnet, one fresh session per
run, capped at 60 turns. Each session pointed at a throwaway configuration
directory, loaded no settings sources, no MCP servers, no user plugins, no
memories and no output style, so the only difference between arms was whether
sniff was available. For the baseline arm, every directory containing a `sniff`
executable was also stripped from `PATH`, rather than trusting the absence of the
plugin.

Three details matter for fairness:

- **Write tools stayed enabled for both arms.** Blocking them looks symmetric and
  is not: on its first run the unaided agent wrote a script into the repository,
  ran it, and deleted it. sniff never needs scratch space, so removing that
  option would have removed a strategy only one side uses. The repository is
  restored with `git checkout` and `git clean` after every run instead.
- **The repository's own `CLAUDE.md` was given to both arms.** It is a map of the
  source tree, and only the arm that has to find files by hand can profit from a
  map.
- **sniff's setup cost is charged to sniff.** The sniff arm pays for the tokens
  of `sniff prime` in its system prompt, which is what a real user's session
  loads.

**Scoring** did not compare sniff against another tool, which would only measure
agreement between two tools. Instead every claim an answer makes is checked
against the source: does that file exist, does it define that symbol, is that
line number right. Claims too vague to check are excluded from the ratio rather
than counted against either side.

## Limits

Read these before quoting the numbers.

- **One run per cell.** The 14.2x is a single sample, not an average. Language
  model runs vary, and nothing here measures that variance.
- **One model.** Sonnet only. A cheaper or more expensive model shifts the
  absolute costs, though the mechanism driving the gap, how many files get read,
  is not model specific.
- **Two repositories, one question set.** Four questions chosen in advance, on
  two well-maintained open source projects. A messier codebase might favour
  either side.
- **The scorer was written by sniff's author.** Every round of scorer bugs found
  so far was one-sided, and the direction flipped between rounds: the first set
  punished sniff, the second punished the arm that writes more prose. The
  hallucination numbers above survive a manual read of every failure, which is
  the only reason they are quoted at all.
- **One question was reworded mid-benchmark.** Asked bare, "Where should I start
  refactoring?" made the unaided agent ask which file was meant and stop, since a
  non-interactive session has nobody to answer. That produced a meaningless cost
  win for the baseline. The question now tells both arms that no follow-up is
  possible, and the void runs are excluded.
- **The reference ranking is only trusted for Python.** lizard mis-parses
  TypeScript function boundaries badly enough on excalidraw that its ranking there
  was discarded rather than used as truth.

## Reproducing

The raw data is one JSON line per run, recorded alongside the full stream
transcript, so every number above can be re-derived rather than taken on trust.
The harness that produced it is a local development script and is not part of the
published package.

To try the same comparison yourself, install sniff and ask your agent a vague
question about a repository, once with sniff on `PATH` and once without:

```bash
uv tool install sniff-smells
sniff /path/to/repo
```
