#!/usr/bin/env bash
# Sync upstream/main into origin/main via rebase, optionally into orghi-main.
# Usage: ./sync-upstream.sh [--orghi] [--dry-run]
#   --orghi   Also run CI, merge main into orghi-main, tag, and push
#   --dry-run Print planned steps without executing

set -e

MERGE_ORGHI=false
DRY_RUN=false
TAG=""
for arg in "$@"; do
  [[ "$arg" == "--orghi" ]] && MERGE_ORGHI=true
  [[ "$arg" == "--dry-run" ]] && DRY_RUN=true
done

run() {
  if [[ "$DRY_RUN" == true ]]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

echo_cmd() {
  if [[ "$DRY_RUN" == true ]]; then
    echo "[dry-run] $*"
  else
    echo "$*"
  fi
}

# Pre-flight: check for uncommitted changes
if [[ -n $(git status -s) ]]; then
  echo "Error: Uncommitted changes detected. Commit or stash before syncing."
  exit 1
fi

# Pre-flight: verify upstream remote exists
if ! git remote get-url upstream &>/dev/null; then
  echo "Error: Remote 'upstream' not found. Add it with: git remote add upstream <url>"
  exit 1
fi

echo "Fetching upstream..."
run git fetch upstream

MAIN_REF=$(git rev-parse main)
UPSTREAM_REF=$(git rev-parse upstream/main)

if [[ "$MAIN_REF" == "$UPSTREAM_REF" ]]; then
  echo "main is already up to date with upstream/main."
  if [[ "$MERGE_ORGHI" != true ]]; then
    echo "Nothing to do."
    exit 0
  fi
else
  echo "Syncing main from upstream (rebase)..."
  run git checkout main
  run git rebase upstream/main
  echo_cmd "Pushing main (force-with-lease)..."
  run git push --force-with-lease origin main

  TAG="orghi-sync-$(date +%Y%m%d-%H%M)"
  echo "Tagging main as $TAG..."
  run git tag "$TAG"
  run git push origin "$TAG"
fi

if [[ "$MERGE_ORGHI" == true ]]; then
  MAIN_REF=$(git rev-parse main)
  ORGHI_REF=$(git rev-parse orghi-main)
  if [[ "$MAIN_REF" == "$ORGHI_REF" ]]; then
    echo "orghi-main is already up to date with main. Nothing to merge."
    exit 0
  fi
  echo "Running CI (pytest) on main..."
  if [[ "$DRY_RUN" == true ]]; then
    echo "[dry-run] uv sync --extra dev && uv run pytest"
  else
    uv sync --extra dev
    if ! uv run pytest; then
      echo "Error: CI failed. Aborting merge into orghi-main."
      exit 1
    fi
  fi

  echo "Merging main into orghi-main..."
  run git checkout orghi-main
  run git merge main
  echo "Running orghi tests..."
  if [[ "$DRY_RUN" == true ]]; then
    echo "[dry-run] uv run pytest tests/orghi -v"
  else
    if ! uv run pytest tests/orghi -v; then
      echo "Error: Orghi tests failed. Fix the merge resolution (feature code, not tests) and retry."
      exit 1
    fi
  fi
  run git push origin orghi-main
  echo "Done. main and orghi-main are synced.${TAG:+ Tag: $TAG}"
else
  echo "Done. main is synced.${TAG:+ Tag: $TAG} Run with --orghi to also update orghi-main."
fi
