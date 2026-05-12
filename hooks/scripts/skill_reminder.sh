#!/usr/bin/env bash
# UserPromptSubmit hook for Claude Code.
# When the active project is a Flutter project, inject a compact reminder of the top-5 rules
# as additionalContext (stdout for UserPromptSubmit becomes context).
# No-ops outside Flutter projects. Always exits 0.

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
Top-5 rules:
  (1) `dart analyze` exits 0; `flutter_skill_lints` wired in `analysis_options.yaml plugins:`, never `pubspec.yaml`.
  (2) `if (!ref.mounted) return;` after every `await` in notifier; `if (!context.mounted) return;` in widgets/State.
  (3) Public widgets only — no `_buildXxx()` and no `class _Foo extends StatelessWidget|StatefulWidget|ConsumerWidget|HookWidget`. State<T> subclasses exempt.
  (4) `Object?` not `dynamic` (Map<String, dynamic> for JSON is fine); no `value!`.
  (5) `@riverpod` codegen for every provider; no manual `Provider(...)`. Use `AppLocalizations` for UI strings, not hardcoded `Text('...')`.

Read `references/` files via the trigger-map in SKILL.md before generating code in their domain. Emit the filled-in Pre-Flight checklist after every code change.
EOF

exit 0
