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

A smell needs one of four engines. `sniff-forge` picks the right one when you make
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

## Install (Claude Code)

```bash
/plugin marketplace add https://github.com/ambervdberg/sniff
/plugin install sniff
```

Update later with `git pull` on the marketplace or the `/plugin` update flow.

## What's here

| Skill | Does |
| --- | --- |
| `largest-methods` | Rank the longest methods/functions by line count. |
| `large-classes` | Rank the longest classes by line count. |
| `sniff-lint` | Run the rule catalog in one `ast-grep scan` pass; compact findings table. |
| `sniff-forge` | Scaffold a new smell skill or catalog rule from a short conversation. |

`skills/_ast-harness/` is the shared engine every ast-based skill reuses (running
ast-grep, parsing JSON, folding nested matches, ranking, printing the table). The
underscore prefix and missing description keep it from triggering as a skill.

## Layout

```
.claude-plugin/   plugin.json + marketplace.json
skills/
  _ast-harness/   shared engine + its tests
  largest-methods/
  large-classes/
  sniff-lint/     rule catalog (ast-grep scan)
  sniff-forge/    the skill/rule generator
hooks/            suggest-forge detection hook (planned)
docs/             design spec
```

## Tests

```bash
python skills/_ast-harness/test_harness.py
```
