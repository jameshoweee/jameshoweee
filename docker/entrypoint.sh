#!/usr/bin/env sh
# Clone the profile repo, regenerate the stat cards, and push if anything changed.
# Designed to run as a one-shot homelab container (docker compose up) or, with
# REFRESH_INTERVAL set, on a loop.
set -eu

: "${GH_TOKEN:?set GH_TOKEN to a PAT with 'repo' + 'read:org' scopes}"
PROFILE_REPO="${PROFILE_REPO:-jameshoweee/jameshoweee}"
GIT_NAME="${GIT_NAME:-James Howe}"
GIT_EMAIL="${GIT_EMAIL:-jameshoweee@users.noreply.github.com}"
BRANCH="${BRANCH:-main}"
WORKDIR=/work/repo

run_once() {
  rm -rf "$WORKDIR"
  git clone --depth 1 --branch "$BRANCH" \
    "https://x-access-token:${GH_TOKEN}@github.com/${PROFILE_REPO}.git" "$WORKDIR"
  cd "$WORKDIR"
  git config user.name "$GIT_NAME"
  git config user.email "$GIT_EMAIL"

  GH_TOKEN="$GH_TOKEN" python3 scripts/generate_profile_cards.py --out profile

  if [ -n "$(git status --porcelain profile)" ]; then
    git add profile/stats.svg profile/top-langs.svg
    git commit -m "chore: auto-update profile cards"
    git push origin "HEAD:${BRANCH}"
    echo "pushed updated cards"
  else
    echo "cards already up to date, nothing to push"
  fi
}

if [ -n "${REFRESH_INTERVAL:-}" ]; then
  echo "loop mode: regenerating every ${REFRESH_INTERVAL}s"
  while true; do
    run_once || echo "run failed, will retry next interval"
    sleep "$REFRESH_INTERVAL"
  done
else
  run_once
fi
