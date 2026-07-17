#!/usr/bin/env bash

set -uo pipefail

PACKAGE_ROOT=$(cd "$(dirname "$0")/.." && pwd -P) || exit 2
REPO_ROOT=$(git -C "$PACKAGE_ROOT" rev-parse --show-toplevel 2>/dev/null) || {
  echo "Dart Decimate pre-push: not inside a Git repository." >&2
  exit 2
}
cd "$REPO_ROOT" || exit 2

GATE="$HOME/.agents/skills/deterministic-checks/scripts/dart_decimate_gate.py"
if [[ ! -f "$GATE" ]]; then
  echo "Dart Decimate pre-push: canonical gate is missing." >&2
  exit 2
fi

REMOTE_NAME="${1:-origin}"
BASE_REF=$(git symbolic-ref --quiet --short "refs/remotes/$REMOTE_NAME/HEAD" 2>/dev/null || true)
if [[ -z "$BASE_REF" ]]; then
  BASE_REF=$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)
fi

if [[ -n "$BASE_REF" ]] && git rev-parse --verify "$BASE_REF^{commit}" >/dev/null 2>&1; then
  exec python3 "$GATE" --package "$PACKAGE_ROOT" --base "$BASE_REF"
fi

exec python3 "$GATE" --package "$PACKAGE_ROOT" --full
