#!/usr/bin/env bash

set -uo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "Dart Decimate pre-push: not inside a Git repository." >&2
  exit 2
}
cd "$REPO_ROOT" || exit 2

if ! command -v npx >/dev/null 2>&1; then
  echo "Dart Decimate pre-push: npx is required." >&2
  exit 2
fi

REMOTE_NAME="${1:-origin}"
BASE_REF=$(git symbolic-ref --quiet --short "refs/remotes/$REMOTE_NAME/HEAD" 2>/dev/null || true)
if [[ -z "$BASE_REF" ]]; then
  BASE_REF=$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)
fi

if [[ -n "$BASE_REF" ]] && git rev-parse --verify "$BASE_REF^{commit}" >/dev/null 2>&1; then
  exec npx --yes dart-decimate audit . --base "$BASE_REF" --format json --summary --gate new-only
fi

exec npx --yes dart-decimate json .
