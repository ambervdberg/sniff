# sniff

Token-cheap **code-smell skills**. Point a skill at a repo, get back a small
ranked table or findings list, never raw source or AST dumped into the conversation.

The goal: a self-serve, private alternative to a SonarCloud-style scan, built from
small skills you can grow one at a time. Each smell is its own skill or catalog
rule, so the model only loads what it needs and answers for a handful of tokens.

Skills are **agent-agnostic** (Claude Code, Codex, Gemini, ...). The `.claude-plugin/`
packaging is Claude Code's marketplace mechanism; the `SKILL.md` files follow the
portable skill convention.

## Engines

A smell needs one of four engines. `sniff-create` picks the right one when you make
a new check:

| Engine | For | Example |
| --- | --- | --- |
| **pattern rule** | a specific code shape, flagged with a severity | `any` type, empty `imports: []` |
| **node metric** | score each method/class from its AST | nesting depth, cyclomatic / cognitive complexity, inline-template line count |
| **file metric** | a number per file, no AST | largest files (split candidates) |
| **cross-file** | needs a whole-project graph | inheritance depth |

`pattern rule` and `node metric` run on [ast-grep](https://ast-grep.github.io);
`file metric` is plain Python. The shared engine lives in `skills/_ast-harness/`.

## Prerequisites

- [`ast-grep`](https://ast-grep.github.io) on PATH (`ast-grep --version`)
- Python 3 (any recent version)

One-time per machine, not per repo.

## Install

### Claude Code (plugin)

```bash
/plugin marketplace add https://github.com/ambervdberg/sniff
/plugin install sniff
```

Update later with `git pull` on the marketplace or the `/plugin` update flow.

### Python CLI (`uv tool install`)

```bash
uv tool install .
sniff [DIR]
```

Puts `sniff` on PATH via [uv](https://docs.astral.sh/uv/). Requires Python 3.9+.

### Zero-install (Windows, after `git clone`)

```bat
sniff.bat [DIR]
```

No install step — just Python on PATH. The `sniff.bat` in the repo root delegates to `skills/sniff/scripts/run.py`.

## Common asks

| User asks | Run |
| --- | --- |
| Full scan / find all code smells / run all checks | `sniff [DIR]` |
| See available detectors | `sniff --list` |
| Pattern rules only | `sniff --only sniff-patterns [DIR]` |
| List pattern rules | `sniff --list-patterns` |
| Single metric | `sniff --only <detector> [DIR]` |
## Commands

| Command | What it does |
| --- | --- |
| `sniff [DIR]` | Scan `DIR` (default: `.`) with all detectors. |
| `sniff --list` | List all available detectors. |
| `sniff --list-patterns` | List all pattern rules (RULE / SEVERITY / MESSAGE). |
| `sniff --only a,b [DIR]` | Run only the named detectors. |
| `sniff --skip a,b [DIR]` | Run all detectors except the named ones. |
| `sniff --only sniff-patterns [DIR]` | Run pattern rules only. |
| `sniff --help` | Show usage and examples. |

## What's here

| Skill | Does |
| --- | --- |
| `largest-methods` | Rank the longest methods/functions by line count. |
| `large-classes` | Rank the longest classes by line count. |
| `largest-files` | Rank the largest source files by non-blank line count (no AST). |
| `deepest-nesting` | Rank functions by control-flow nesting depth (S134). |
| `cyclomatic-complexity` | Rank functions by cyclomatic complexity (S1541). |
| `cognitive-complexity` | Rank functions by cognitive complexity (nesting-weighted read difficulty). |
| `most-parameters` | Rank functions by parameter count (long-parameter-list smell). |
| `large-inline-templates` | Rank Angular components by inline-template line count. |
| `sniff` | Umbrella runner: runs **all** detectors in one pass. Use this for a full scan. |
| `sniff-patterns` | Run the pattern rule catalog in one `ast-grep scan` pass; compact findings table. |
| `sniff-create` | Scaffold a new smell skill or catalog rule from a short conversation. |

`skills/_ast-harness/` is the shared engine every ast-based skill reuses (running
ast-grep, parsing JSON, folding nested matches, ranking, printing the table). The
underscore prefix and missing description keep it from triggering as a skill.

## Layout

```
.claude-plugin/   plugin.json (skills, Stop hook) + marketplace.json
skills/
  _ast-harness/   shared engine (+ node_metric) + tests
  largest-methods/
  large-classes/
  largest-files/
  deepest-nesting/
  cyclomatic-complexity/
  cognitive-complexity/
  most-parameters/
  large-inline-templates/
  sniff/           umbrella runner (runs all detectors)
  sniff-patterns/  rule catalog (ast-grep scan)
  sniff-create/    the skill/rule generator + suggest-create detection hook
docs/             design spec
```

## Suggest-create hook

A `Stop` hook (declared in `plugin.json`) watches each turn and, when it spots a
costly repeated structural search (>= 6 read/grep/glob calls plus a structural
prompt), prints one line suggesting you run `sniff-create` to turn it into a
token-cheap skill. Suggest-only: it never creates anything and never blocks.
The detector lives in `skills/sniff-create/scripts/detect_costly_search.py`.

### Tuning

| Env var | Default | Effect |
| --- | --- | --- |
| `SNIFF_CREATE_NUDGE` | on | Set to `0`/`off`/`false`/`no` to silence the nudge entirely. |
| `SNIFF_MIN_CALLS` | `6` | Read/grep/glob calls in a turn needed to trip the heuristic. |

### Caveats

It is a **heuristic**, not a judgement of intent. The hook sees the turn's tool
calls and the prompt text, never your reasoning, so:

- Expect the occasional **miss** (a real repeated search the prompt did not phrase
  structurally) and the occasional **false positive** (lots of reads for an
  unrelated reason). Both are cheap: a missed nudge costs nothing, a stray one is a
  single ignorable line.
- It only inspects the **most recent turn**; a search spread across several turns
  does not accumulate.
- Raise `SNIFF_MIN_CALLS` if a project trips it too often; lower it to catch
  searches sooner. Turn it off per session with `SNIFF_CREATE_NUDGE=0` when it is
  noise for the task at hand.

## Tests

```bash
python skills/_ast-harness/test_harness.py
```
