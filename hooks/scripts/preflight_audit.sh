#!/usr/bin/env bash
# Stop hook for Claude Code.
# Runs a full pre-flight audit on the active Flutter project before letting Claude end the turn.
# Always exits 0. Emits JSON {"decision":"block","reason":"..."} on stdout to keep Claude going if violations remain.
# No-ops outside Flutter projects.

set -uo pipefail

PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"

# Walk up from PROJECT_ROOT to find pubspec.yaml
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

cd "$FLUTTER_ROOT" || exit 0

VIOLATIONS=()
add_violation() { VIOLATIONS+=("$1"); }

# 1. analysis_options.yaml must exist at project root
if [[ ! -f "$FLUTTER_ROOT/analysis_options.yaml" ]]; then
  add_violation "Missing $FLUTTER_ROOT/analysis_options.yaml. Copy references/analysis_options.yaml from the skill to the project root."
fi

# 2. flutter_skill_lints wired in analysis_options.yaml plugins
if [[ -f "$FLUTTER_ROOT/analysis_options.yaml" ]]; then
  if ! grep -qE '^\s*flutter_skill_lints\s*:' "$FLUTTER_ROOT/analysis_options.yaml" 2>/dev/null; then
    add_violation "flutter_skill_lints not wired under plugins: in analysis_options.yaml. Add it under analyzer.plugins."
  fi
  # Plugin must NOT be in pubspec.yaml (wrong location)
  if [[ -f "$FLUTTER_ROOT/pubspec.yaml" ]] && grep -qE '^\s*(flutter_skill_lints|riverpod_lint)\s*:' "$FLUTTER_ROOT/pubspec.yaml" 2>/dev/null; then
    # That's fine in dev_dependencies; the bad pattern is `analyzer.plugins:` block IN pubspec.yaml itself
    # We can't easily disambiguate without a YAML parser; skip the warning here.
    :
  fi
fi

# 3. Repo-wide grep checks across lib/ and test/
if [[ -d "$FLUTTER_ROOT/lib" ]]; then
  SCAN_ROOTS=("$FLUTTER_ROOT/lib")
  [[ -d "$FLUTTER_ROOT/test" ]] && SCAN_ROOTS+=("$FLUTTER_ROOT/test")

  # Helper: grep ERE recursively, exclude generated files
  recursive_grep() {
    local pattern="$1"
    shift
    grep -rnE "$pattern" "${SCAN_ROOTS[@]}" \
      --include='*.dart' \
      --exclude='*.g.dart' \
      --exclude='*.freezed.dart' \
      --exclude='*.gr.dart' \
      --exclude='*.config.dart' \
      --exclude='*.mocks.dart' \
      2>/dev/null || true
  }

  COUNT=0
  while IFS= read -r match; do
    [[ -z "$match" ]] && continue
    COUNT=$((COUNT + 1))
  done < <(recursive_grep '_build[A-Z][A-Za-z0-9_]*[[:space:]]*\(' | head -n 5)
  [[ $COUNT -gt 0 ]] && add_violation "$COUNT _buildXxx() helper(s) found in lib/. Extract to public widget classes."

  COUNT=0
  while IFS= read -r match; do
    [[ -z "$match" ]] && continue
    COUNT=$((COUNT + 1))
  done < <(recursive_grep 'class[[:space:]]+_[A-Z][A-Za-z0-9_]*[[:space:]]+extends[[:space:]]+(StatelessWidget|StatefulWidget|ConsumerWidget|ConsumerStatefulWidget|HookWidget|HookConsumerWidget)\b' | head -n 5)
  [[ $COUNT -gt 0 ]] && add_violation "$COUNT private widget class(es) found. Use public + @visibleForTesting. State<T> subclasses exempt."

  COUNT=0
  while IFS= read -r match; do
    [[ -z "$match" ]] && continue
    COUNT=$((COUNT + 1))
  done < <(recursive_grep 'shrinkWrap:[[:space:]]*true' | head -n 5)
  [[ $COUNT -gt 0 ]] && add_violation "$COUNT shrinkWrap: true found. Use slivers or fix viewport constraint."

  COUNT=0
  while IFS= read -r match; do
    [[ -z "$match" ]] && continue
    COUNT=$((COUNT + 1))
  done < <(recursive_grep 'ValueKey[[:space:]]*\([[:space:]]*['\''"]' | head -n 5)
  [[ $COUNT -gt 0 ]] && add_violation "$COUNT inline string ValueKey(...) found. Use AppWidgetKeys central registry."

  feature_notifier_keepalive_scan() {
    local tmp_hits="" result
    [[ -d "$FLUTTER_ROOT/lib/features" ]] || return 0
    while IFS= read -r f; do
      result=$(awk '
        {
          line[NR] = $0
          if ($0 ~ /ref[[:space:]]*\.[[:space:]]*onDispose[[:space:]]*\(/) has_dispose = 1
        }
        END {
          for (i = 1; i <= NR; i++) {
            if (line[i] !~ /@(riverpod|Riverpod)/) continue

            class_line = 0
            for (j = i + 1; j <= i + 8 && j <= NR; j++) {
              if (line[j] ~ /^[[:space:]]*class[[:space:]]+[A-Za-z_][A-Za-z0-9_]*Notifier([[:space:]]|$)/) {
                class_line = j
                break
              }
            }
            if (class_line == 0) continue

            keep_alive = 0
            for (j = i; j < class_line; j++) {
              if (line[j] ~ /keepAlive:[[:space:]]*true/) keep_alive = 1
            }
            if (keep_alive) continue
            if (has_dispose) continue

            family = 0
            for (j = class_line; j <= class_line + 80 && j <= NR; j++) {
              if (line[j] ~ /^[[:space:]]*[A-Za-z0-9_<>,?[:space:]]+[[:space:]]+build[[:space:]]*\([^)]*[A-Za-z_][A-Za-z0-9_]*[[:space:]]+[A-Za-z_][A-Za-z0-9_]*/) {
                family = 1
                break
              }
            }
            if (family) continue

            rationale = 0
            for (j = i - 6; j < i; j++) {
              if (j > 0 && line[j] ~ /(auto[- ]?dispose|ephemeral|transient|route[- ]?local|screen[- ]?local|reset when|dispose when unused)/) {
                rationale = 1
              }
            }
            if (rationale) continue

            print FILENAME ":" i ": feature notifier without keepAlive"
          }
        }
      ' "$f" 2>/dev/null || true)
      [[ -n "$result" ]] && tmp_hits="$tmp_hits"$'\n'"$result"
    done < <(find "$FLUTTER_ROOT/lib/features" -type f -path '*/presentation/notifiers/*_notifier.dart' 2>/dev/null)
    printf '%s\n' "${tmp_hits#$'\n'}"
  }

  COUNT=0
  while IFS= read -r match; do
    [[ -z "$match" ]] && continue
    COUNT=$((COUNT + 1))
  done < <(feature_notifier_keepalive_scan | head -n 5)
  [[ $COUNT -gt 0 ]] && add_violation "$COUNT feature presentation notifier(s) auto-dispose without keepAlive or rationale. Use @Riverpod(keepAlive: true) unless it is family, lifecycle-cleanup, or documented ephemeral state."

  raw_or_named_nav_grep() {
    {
      recursive_grep '(^|[^A-Za-z0-9_])context[[:space:]]*\.[[:space:]]*(go|push|replace|pushReplacement)[[:space:]]*(<[^>]+>)?[[:space:]]*\([[:space:]]*r?['\''"]'
      recursive_grep '(^|[^A-Za-z0-9_])context[[:space:]]*\.[[:space:]]*(goNamed|pushNamed|replaceNamed)[[:space:]]*(<[^>]+>)?[[:space:]]*\('
      recursive_grep '(^|[^A-Za-z0-9_])GoRouter[[:space:]]*\.[[:space:]]*of[[:space:]]*\([^)]*\)[[:space:]]*\.[[:space:]]*(go|push|replace|pushReplacement)[[:space:]]*(<[^>]+>)?[[:space:]]*\([[:space:]]*r?['\''"]'
      recursive_grep '(^|[^A-Za-z0-9_])GoRouter[[:space:]]*\.[[:space:]]*of[[:space:]]*\([^)]*\)[[:space:]]*\.[[:space:]]*(goNamed|pushNamed|replaceNamed)[[:space:]]*(<[^>]+>)?[[:space:]]*\('
      recursive_grep '(^|[^A-Za-z0-9_])(_?router|[A-Za-z_][A-Za-z0-9_]*Router[A-Za-z0-9_]*)[[:space:]]*\.[[:space:]]*(go|push|replace|pushReplacement)[[:space:]]*(<[^>]+>)?[[:space:]]*\([[:space:]]*r?['\''"]'
      recursive_grep '(^|[^A-Za-z0-9_])(_?router|[A-Za-z_][A-Za-z0-9_]*Router[A-Za-z0-9_]*)[[:space:]]*\.[[:space:]]*(goNamed|pushNamed|replaceNamed)[[:space:]]*(<[^>]+>)?[[:space:]]*\('
      recursive_grep '(^|[^A-Za-z0-9_])initialLocation[[:space:]]*:[[:space:]]*r?['\''"]'
    }
  }

  COUNT=0
  while IFS= read -r match; do
    [[ -z "$match" ]] && continue
    COUNT=$((COUNT + 1))
  done < <(raw_or_named_nav_grep | head -n 5)
  [[ $COUNT -gt 0 ]] && add_violation "$COUNT raw or named route navigation call(s) found. Use generated typed route helpers; route definitions own paths."

  direct_page_nav_grep() {
    {
      recursive_grep '(^|[^A-Za-z0-9_])context[[:space:]]*\.[[:space:]]*(go|push|replace|pushReplacement|goNamed|pushNamed|replaceNamed)[[:space:]]*(<[^>]+>)?[[:space:]]*\('
      recursive_grep '(^|[^A-Za-z0-9_])(_?router|[A-Za-z_][A-Za-z0-9_]*Router[A-Za-z0-9_]*)[[:space:]]*\.[[:space:]]*(go|push|replace|pushReplacement|goNamed|pushNamed|replaceNamed)[[:space:]]*(<[^>]+>)?[[:space:]]*\('
      recursive_grep '(^|[^A-Za-z0-9_])Navigator[[:space:]]*(\.[[:space:]]*of[[:space:]]*\([^)]*\)[[:space:]]*)?\.[[:space:]]*(push|pushReplacement|pushAndRemoveUntil|pushNamed|pushReplacementNamed|restorablePush|restorablePushNamed)[[:space:]]*(<[^>]+>)?[[:space:]]*\('
    }
  }

  COUNT=0
  while IFS= read -r match; do
    [[ -z "$match" ]] && continue
    COUNT=$((COUNT + 1))
  done < <(direct_page_nav_grep | head -n 5)
  [[ $COUNT -gt 0 ]] && add_violation "$COUNT raw context/router/Navigator page navigation call(s) found. Call generated typed route helpers for page navigation."

  # Extension SSOT — scope checks to OUTSIDE core/extensions/ and *_extensions.dart files
  ext_grep() {
    local pattern="$1"
    grep -rnE "$pattern" "${SCAN_ROOTS[@]}" \
      --include='*.dart' \
      --exclude='*.g.dart' \
      --exclude='*.freezed.dart' \
      --exclude='*.gr.dart' \
      --exclude='*.config.dart' \
      --exclude='*.mocks.dart' \
      --exclude='*_extensions.dart' \
      --exclude-dir='extensions' \
      2>/dev/null || true
  }

  # Inline capitalize: '${x[0].toUpperCase()}${x.substring(1)}'
  COUNT=0
  while IFS= read -r match; do
    [[ -z "$match" ]] && continue
    COUNT=$((COUNT + 1))
  done < <(ext_grep '\[0\]\.toUpperCase\(\)[^,)]*substring\([[:space:]]*1' | head -n 5)
  [[ $COUNT -gt 0 ]] && add_violation "$COUNT inline capitalize anti-pattern found. Use String extension .capitalized — see references/extensions-utilities.md (Critical Rule 11)."

  # Inline timeAgo: DateTime.now().difference(...)
  COUNT=0
  while IFS= read -r match; do
    [[ -z "$match" ]] && continue
    COUNT=$((COUNT + 1))
  done < <(ext_grep 'DateTime\.now\(\)\.difference\(' | head -n 5)
  [[ $COUNT -gt 0 ]] && add_violation "$COUNT inline DateTime.now().difference(...) found outside core/extensions/. Use DateTime extension .timeAgo or add to date_time_extensions.dart (Critical Rule 11)."

  # Inline currency format: NumberFormat.currency(...).format(
  COUNT=0
  while IFS= read -r match; do
    [[ -z "$match" ]] && continue
    COUNT=$((COUNT + 1))
  done < <(ext_grep 'NumberFormat\.currency\(.*\)\.format\(' | head -n 5)
  [[ $COUNT -gt 0 ]] && add_violation "$COUNT inline NumberFormat.currency(...).format(...) found outside core/extensions/. Use .asCurrency() extension (Critical Rule 11)."

  # Inline DateFormat(...).format(...) outside extensions
  COUNT=0
  while IFS= read -r match; do
    [[ -z "$match" ]] && continue
    COUNT=$((COUNT + 1))
  done < <(ext_grep 'DateFormat\(.*\)\.format\(' | head -n 5)
  [[ $COUNT -gt 0 ]] && add_violation "$COUNT inline DateFormat(...).format(...) found outside core/extensions/. Use .formatted() / .asDate / .asTime extension (Critical Rule 11)."
fi

# 4. dart analyze must exit 0
if command -v dart >/dev/null 2>&1; then
  ANALYZE_OUT=$(dart analyze --fatal-infos 2>&1 || true)
  ANALYZE_EXIT=$?
  if [[ $ANALYZE_EXIT -ne 0 ]] || printf '%s' "$ANALYZE_OUT" | grep -qE '\b(error|warning) '; then
    # Truncate analyze output to first 30 lines for the reason
    ANALYZE_PREVIEW=$(printf '%s' "$ANALYZE_OUT" | head -n 30)
    add_violation "dart analyze failed. Output (first 30 lines):"$'\n'"$ANALYZE_PREVIEW"
  fi
fi

# 5. Emit result
if [[ ${#VIOLATIONS[@]} -eq 0 ]]; then
  exit 0
fi

REASON="building-flutter-apps pre-flight audit found violations in $FLUTTER_ROOT. Fix before declaring done:"
for v in "${VIOLATIONS[@]}"; do
  REASON+=$'\n— '"$v"
done

if command -v python3 >/dev/null 2>&1; then
  python3 -c "import json,sys; print(json.dumps({'decision':'block','reason':sys.stdin.read()}))" <<<"$REASON"
else
  ESCAPED=${REASON//\\/\\\\}
  ESCAPED=${ESCAPED//\"/\\\"}
  ESCAPED=${ESCAPED//$'\n'/\\n}
  printf '{"decision":"block","reason":"%s"}\n' "$ESCAPED"
fi

exit 0
