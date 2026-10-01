#!/usr/bin/env bash
# UserPromptSubmit stdout becomes agent context; stays silent outside Flutter projects and always exits 0.

set -uo pipefail

PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"

find_flutter_root() {
  local d="$1"
  while [[ "$d" != "/" && -n "$d" ]]; do
    if [[ -f "$d/pubspec.yaml" ]]; then
      printf '%s' "$d"
      return 0
    fi
    d=$(dirname "$d")
  done
  return 1
}

FLUTTER_ROOT=$(find_flutter_root "$PROJECT_ROOT") || exit 0
[[ -z "$FLUTTER_ROOT" ]] && exit 0

# Only fire if lib/ also exists (signal of a Flutter app, not just a Dart package)
[[ -d "$FLUTTER_ROOT/lib" ]] || exit 0

cat <<'EOF'
[building-flutter-apps active]
Rule owner = the building-flutter-apps SKILL.md; load it before Flutter/Dart edits. Most-missed Critical Rules:
  R1 package-root `dart analyze` + project-owned Dart Decimate gates; R2 `@riverpod` codegen only;
  R3 `ref.mounted` / `context.mounted` after awaits; R4 public widget classes, no `_buildXxx()`;
  R5 no `value!` or sentinel fallbacks; R6 `AppLocalizations` for UI copy.
  `Object?`, not `dynamic`, except JSON `Map<String, dynamic>`.
Its Trigger Map is the progressive-disclosure gate; run its Pre-Flight after each write batch.
EOF

exit 0
