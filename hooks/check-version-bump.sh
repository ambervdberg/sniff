#!/usr/bin/env bash
# PreToolUse(Bash) hook: warn when committing skills/ changes without bumping
# plugin.json and pyproject.toml versions. Stale-cache guard: marketplace
# installs key on version, so an unchanged version means other machines keep
# running old code. Non-blocking: prints to stderr, always exits 0.
set -euo pipefail

# The hook payload arrives as JSON on stdin; pull out the command being run.
payload=$(cat)
command=$(printf '%s' "$payload" \
  | python -c "import json,sys;print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null || true)

# Only react to git commits.
case "$command" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

cd "${CLAUDE_PROJECT_DIR:-.}"

# Files staged for this commit.
staged=$(git diff --cached --name-only 2>/dev/null || true)

# Did this commit touch skills? If not, nothing to guard.
if ! printf '%s\n' "$staged" | grep -qE '^skills/'; then
  exit 0
fi

# Was the plugin.json version line bumped (an added "version": line)?
version_bumped=$(git diff --cached -- .claude-plugin/plugin.json 2>/dev/null \
  | grep -E '^\+[^+].*"version"' || true)

if [ -z "$version_bumped" ]; then
  echo "WARN: skills/ changed but .claude-plugin/plugin.json version not bumped." >&2
  echo "      Marketplace installs cache by version; bump it so other machines get the new code." >&2
fi

# Was the pyproject.toml version line bumped?
pyproject_bumped=$(git diff --cached -- pyproject.toml 2>/dev/null \
  | grep -E '^\+version\s*=' || true)

if [ -z "$pyproject_bumped" ]; then
  echo "WARN: skills/ changed but pyproject.toml version not bumped." >&2
  echo "      Keep pyproject.toml version in sync with plugin.json." >&2
fi

exit 0
