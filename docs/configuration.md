# Configuration

Drop a `.sniff.toml` in the root of the repo being scanned to turn rules off, re-grade
severities, skip detectors, retune thresholds, and ignore paths. `sniff doctor` validates it.

Scanning a subdirectory still picks it up: sniff looks in the directory you scan, then
walks up to the repository root and uses the first file it finds. So `sniff packages/api`
honours the repo's committed config, and a `packages/api/.sniff.toml` of its own would
override it rather than merge with it.

```toml
[rules]                           # targets the sniff-patterns catalog only. Key is a rule id:
no-console-log = false            # turn a pattern rule off
no-explicit-any = "error"         # re-grade it (error | warning | info | hint)

[detectors]
skip = "most-imports,largest-files"   # comma-separated detector names
largest-methods.top = 15              # <detector>.<arg> becomes --arg on that detector
deepest-nesting.min-depth = 3         
top = 5                               # all detectors except for overrides.

[ignore]
globs = ["docs/**", "**/*.generated.ts"]
```

Details worth knowing:

- **Keep every value on one line.** sniff reads this file line by line rather than with a
  full TOML parser, so an array split across lines is not understood. Write
  `globs = ["docs/**", "**/*.generated.ts"]` on one line.
- Note the two shapes above: `skip` takes one comma-separated **string**, `globs` takes a
  **list**. `globs` also accepts a string (`globs = "docs/**,**/*.generated.ts"`); `skip`
  does not accept a list.
- `[rules]` only affects pattern rules. `[detectors]` affects the detectors, and each `<detector>.<arg>`
  key becomes a `--arg` flag on that detector. Only flags that take a value work here, so
  `--include-tests` cannot be set this way.
- The bare `top` key caps every detector's table at that many rows. A detector-specific
  `<name>.top` still wins for that one detector.
- Ignore paths are matched from the root of the repo you scan.
- A section or key that sniff does not recognize is a warning, not an error, so a typo does not stop a scan.
  Run `sniff doctor` to see those warnings.

## What gets skipped

1. **Vendored and build directories**, always: `node_modules`, `dist`, `build`, `out`,
   `coverage`, `target`, `vendor`, `.venv`, `venv`, `.git`, `.nx`, `.angular`, `.astro`,
   `.next`, `.svelte-kit`, `.nuxt`, `.turbo`, `__pycache__`, `.claude`.
2. **Anything `.gitignore` excludes**, when the scanned directory is a git repo. Your
   `.git/info/exclude` and global ignore file count too, since sniff asks git rather than
   parsing the ignore files itself. Outside a git repo this layer is simply absent.
3. **Your own globs**: `[ignore] globs` in `.sniff.toml`, plus any `--ignore` flags.

Every detector also skips test code, so the tables describe the source you ship.
That means `*.test.*` and `*.spec.*` files in any language, `test_*.py`, `*_test.py`,
`conftest.py`, `*_test.go`, and anything inside a `tests/`, `test/`, `__tests__/`,
`spec/`, or `specs/` directory.

To rank test code too, add `--include-tests` to a single detector (see
[Passing flags to one detector](../README.md#passing-flags-to-one-detector)). There is no
whole-repo equivalent, so scan the detectors you care about one at a time:

```bash
sniff --only largest-methods . --include-tests
```

`--ignore` is the one exclusion you can pass to a whole scan. It is repeatable, and it
adds to the repo's committed globs rather than replacing them:

```bash
sniff --ignore "docs/**" --ignore "**/*.generated.ts" .
```

## Custom checks, without forking sniff

Two ways to teach sniff your repo's conventions:

- **Local pattern rules.** Drop a `.yml` in `.sniff/rules/` and it runs in the same pass
  as the catalog. See [Add a rule](../README.md#add-a-rule).
- **External detectors.** Drop a `detector.yml` manifest under `.sniff/detectors/<name>/`
  and `sniff --list` picks it up alongside the built-ins.

Either way `sniff-create` picks the engine for you;
[CONTRIBUTING.md](../CONTRIBUTING.md#engines) lists all five if you want to choose by hand.
