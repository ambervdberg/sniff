# CI mode

Gate PRs on code-smell regressions using the committed baseline:

1. Run `sniff baseline write` once and commit the resulting `.sniff/baseline.json`.
2. Add this action to a workflow, after a checkout step:

```yaml
- uses: actions/checkout@v4
- uses: ambervdberg/sniff@v0.16.1
  with:
    path: .
```

The action installs `ast-grep` and `sniff`, then runs `sniff diff --comment` against the
committed baseline, failing the job if any detector regressed. It needs the checkout: on
its own it would scan an empty workspace and find nothing to compare.

`--comment` only *formats* the result as a PR comment body; the action saves it to
`sniff-diff.md` in the workspace. (Running `sniff diff --comment` yourself just prints
it.) Nothing is posted for you. To get a comment on the PR, add a step that posts that
file.

Pin a release tag, as above, so a push to this repo cannot change what runs in your CI.
`@main` tracks the latest instead, at that cost.

**When the gate goes red.** Either fix the regression, or accept it: re-run
`sniff baseline write` and commit the updated `.sniff/baseline.json` in the same PR. The
baseline is a snapshot you own, not a target sniff enforces, so raising it deliberately
is a normal move. What it buys you is that the next PR cannot raise it by accident.
