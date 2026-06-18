#!/usr/bin/env bash
# check_drift.sh — Drift regression checker for building-flutter-apps skill
#
# Usage:
#   bash tool/check_drift.sh [--ignore <rule-id>[,<rule-id>...]] [<path>...]
#
# Exit: 0 = all clean, 1 = violations found, 2 = usage error
#
# Per-line escape hatch:
#   Add "# drift-ignore: <rule-id>" on the same line (or next line for multi-line hits)
#   to suppress a specific rule for that location.
#
# Default scan paths: references/ SKILL.md README.md CONTRIBUTING.md
# Always excluded: AUDIT_REPORT.md tool/

set -euo pipefail

# ── Helpers ──────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# TAP counters
_TAP_INDEX=0
_TAP_FAILS=0
_TAP_IGNORES=""

tap_plan_header() {
  # Called at end once we know total count — use deferred mode instead:
  # we collect results and emit plan at top (TAP spec requires it first,
  # but GNU prove/bash-tap accept trailing plan too).
  true
}

emit_tap() {
  # emit_tap <rule-id> <description> <hits> <hint>
  local rule_id="$1"
  local description="$2"
  local hits="$3"
  local hint="$4"

  _TAP_INDEX=$(( _TAP_INDEX + 1 ))

  # Check if rule is ignored via --ignore flag
  if _rule_ignored "$rule_id"; then
    echo "ok $_TAP_INDEX - ${rule_id}: SKIPPED (--ignore)"
    return 0
  fi

  # Filter drift-ignore escape hatches from hits
  local filtered_hits=""
  if [ -n "$hits" ]; then
    filtered_hits=$(printf '%s\n' "$hits" | grep -v "drift-ignore: ${rule_id}" || true)
  fi

  if [ -z "$filtered_hits" ]; then
    echo "ok $_TAP_INDEX - ${rule_id}: ${description}"
  else
    echo "not ok $_TAP_INDEX - ${rule_id}: ${description}"
    echo "  # Hint: ${hint}"
    while IFS= read -r line; do
      [ -n "$line" ] && echo "  # ${line}"
    done <<< "$filtered_hits"
    _TAP_FAILS=$(( _TAP_FAILS + 1 ))
  fi
}

_rule_ignored() {
  local rule_id="$1"
  # Check comma-separated ignore list
  local IFS=','
  for ignored in $_TAP_IGNORES; do
    if [ "$ignored" = "$rule_id" ]; then
      return 0
    fi
  done
  return 1
}

# ── Argument parsing ──────────────────────────────────────────────────────────

SCAN_PATHS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --ignore)
      shift
      _TAP_IGNORES="$1"
      shift
      ;;
    --ignore=*)
      _TAP_IGNORES="${1#--ignore=}"
      shift
      ;;
    -*)
      echo "Unknown flag: $1" >&2
      exit 2
      ;;
    *)
      SCAN_PATHS+=("$1")
      shift
      ;;
  esac
done

# Default scan paths (relative to repo root)
if [ ${#SCAN_PATHS[@]} -eq 0 ]; then
  for p in references SKILL.md README.md CONTRIBUTING.md; do
    full="$REPO_ROOT/$p"
    [ -e "$full" ] && SCAN_PATHS+=("$full")
  done
fi

# Always exclude: AUDIT_REPORT.md and tool/ (self-trigger protection)
RG_EXCLUDE=(
  --glob '!**/AUDIT_REPORT.md'
  --glob '!**/tool/**'
  --glob '!**/.github/**'
)

# ── Rule: B3 — type cast must use Map<String, dynamic> ───────────────────────
rule_b3() {
  local hits
  hits=$(rg -n --no-heading \
    'as Map<String, Object\?>' \
    "${RG_EXCLUDE[@]}" \
    "${SCAN_PATHS[@]}" 2>/dev/null || true)
  emit_tap "b3" \
    "type cast must use Map<String,dynamic> not Map<String,Object?>" \
    "$hits" \
    "Replace 'as Map<String, Object?>' with 'as Map<String, dynamic>'"
}

# ── Rule: B7 — select() callback must use => arrow syntax ────────────────────
rule_b7() {
  local hits
  # Matches .select((s) followed by body that does NOT have => on same line
  # Pattern: .select((s) <anything-not-containing-=>>
  hits=$(rg -n --no-heading --pcre2 \
    '\.select\(\([a-zA-Z_]\w*\)\s+(?!=>)[^)=]' \
    "${RG_EXCLUDE[@]}" \
    "${SCAN_PATHS[@]}" 2>/dev/null || true)
  emit_tap "b7" \
    "select() callback must use => arrow syntax" \
    "$hits" \
    "Change '.select((s) s.field)' to '.select((s) => s.field)'"
}

# ── Rule: A4-raw — no raw error.toString() in references ─────────────────────
rule_a4_raw() {
  local hits
  hits=$(rg -n --no-heading \
    'error:\s*e\.toString\(\)' \
    "${RG_EXCLUDE[@]}" \
    "${SCAN_PATHS[@]}" 2>/dev/null || true)
  emit_tap "a4-raw" \
    "no raw e.toString() error surfacing in references" \
    "$hits" \
    "Use AppException or structured error types, not e.toString()"
}

# ── Rule: V7 — riverpod_lint prerelease pin must have comment ────────────────
rule_v7() {
  local hits
  # Detect prerelease version pins (e.g. riverpod_lint: 2.3.4-dev.1)
  # The preceding line must start with '#' (a comment)
  # We use awk to do context-aware checking
  local tmp_hits=""
  for scanpath in "${SCAN_PATHS[@]}"; do
    if [ -d "$scanpath" ]; then
      # Find all .md and .yaml files recursively
      while IFS= read -r f; do
        result=$(awk '
          /riverpod_lint:[[:space:]]*[0-9]+\.[0-9]+\.[0-9]+-/ {
            if (NR == 1 || prev !~ /^[[:space:]]*#/) {
              print FILENAME ":" NR ": " $0
            }
          }
          { prev = $0 }
        ' "$f" 2>/dev/null || true)
        [ -n "$result" ] && tmp_hits="$tmp_hits"$'\n'"$result"
      done < <(find "$scanpath" -type f \( -name '*.md' -o -name '*.yaml' -o -name '*.yml' \) 2>/dev/null)
    elif [ -f "$scanpath" ]; then
      result=$(awk '
        /riverpod_lint:[[:space:]]*[0-9]+\.[0-9]+\.[0-9]+-/ {
          if (NR == 1 || prev !~ /^[[:space:]]*#/) {
            print FILENAME ":" NR ": " $0
          }
        }
        { prev = $0 }
      ' "$scanpath" 2>/dev/null || true)
      [ -n "$result" ] && tmp_hits="$tmp_hits"$'\n'"$result"
    fi
  done
  # Strip leading newline
  hits="${tmp_hits#$'\n'}"
  emit_tap "v7" \
    "riverpod_lint prerelease pin must have preceding comment line" \
    "$hits" \
    "Add '# Pinned prerelease for X reason' on the line before riverpod_lint: X.Y.Z-dev"
}

# ── Rule: B4 — @Riverpod(keepAlive:true) must not be followed by family decl ─
rule_b4() {
  local tmp_hits=""
  for scanpath in "${SCAN_PATHS[@]}"; do
    if [ -d "$scanpath" ]; then
      while IFS= read -r f; do
        result=$(awk '
          /@Riverpod\(keepAlive:[[:space:]]*true/ {
            keep_line = NR
          }
          keep_line > 0 && NR <= keep_line + 3 && /Ref[^)]*,/ && NR != keep_line {
            print FILENAME ":" NR ": keepAlive+family detected (memory leak pattern)"
            keep_line = 0
          }
          keep_line > 0 && NR > keep_line + 3 { keep_line = 0 }
        ' "$f" 2>/dev/null || true)
        [ -n "$result" ] && tmp_hits="$tmp_hits"$'\n'"$result"
      done < <(find "$scanpath" -type f -name '*.md' 2>/dev/null)
    elif [ -f "$scanpath" ]; then
      result=$(awk '
        /@Riverpod\(keepAlive:[[:space:]]*true/ {
          keep_line = NR
        }
        keep_line > 0 && NR <= keep_line + 3 && /Ref[^)]*,/ && NR != keep_line {
          print FILENAME ":" NR ": keepAlive+family detected (memory leak pattern)"
          keep_line = 0
        }
        keep_line > 0 && NR > keep_line + 3 { keep_line = 0 }
      ' "$scanpath" 2>/dev/null || true)
      [ -n "$result" ] && tmp_hits="$tmp_hits"$'\n'"$result"
    fi
  done
  hits="${tmp_hits#$'\n'}"
  emit_tap "b4" \
    "keepAlive:true must not appear with family provider (memory leak)" \
    "$hits" \
    "Remove keepAlive or restructure — family+keepAlive leaks all arg variants"
}

# ── Rule: A1 — wrong repository pattern (extends _$OrderRepository) ───────────
rule_a1() {
  local hits
  hits=$(rg -n --no-heading --pcre2 \
    'class\s+\w+Repository\s+extends\s+_\$\w+Repository' \
    "${RG_EXCLUDE[@]}" \
    "${SCAN_PATHS[@]}" 2>/dev/null || true)
  emit_tap "a1" \
    "repositories must implement interface not extend generated class" \
    "$hits" \
    "Use 'class HiveXRepository implements IXRepository' not 'extends _\$XRepository'"
}

# ── Rule: A4-freezed — String? error inside @freezed state classes ────────────
rule_a4_freezed() {
  local tmp_hits=""
  for scanpath in "${SCAN_PATHS[@]}"; do
    if [ -d "$scanpath" ]; then
      while IFS= read -r f; do
        result=$(awk '
          /@freezed/ { in_freezed = 1; freezed_line = NR }
          in_freezed && /^}/ { in_freezed = 0 }
          in_freezed && /String\?[[:space:]]+error/ {
            print FILENAME ":" NR ": String? error inside @freezed state"
          }
        ' "$f" 2>/dev/null || true)
        [ -n "$result" ] && tmp_hits="$tmp_hits"$'\n'"$result"
      done < <(find "$scanpath" -type f -name '*.md' 2>/dev/null)
    elif [ -f "$scanpath" ]; then
      result=$(awk '
        /@freezed/ { in_freezed = 1 }
        in_freezed && /^}/ { in_freezed = 0 }
        in_freezed && /String\?[[:space:]]+error/ {
          print FILENAME ":" NR ": String? error inside @freezed state"
        }
      ' "$scanpath" 2>/dev/null || true)
      [ -n "$result" ] && tmp_hits="$tmp_hits"$'\n'"$result"
    fi
  done
  hits="${tmp_hits#$'\n'}"
  emit_tap "a4-freezed" \
    "no String? error field inside @freezed state classes" \
    "$hits" \
    "Use AsyncError/failure union state instead of nullable String? error"
}

# ── Rule: V6 — Mutation< must include experimental warning nearby ─────────────
rule_v6() {
  local tmp_hits=""
  for scanpath in "${SCAN_PATHS[@]}"; do
    if [ -d "$scanpath" ]; then
      while IFS= read -r f; do
        result=$(awk '
          /Mutation</ {
            mut_line = NR
            # Store surrounding context
            for (i = 1; i <= 5; i++) buf[i] = buf_next[i]
          }
          { buf_next[NR % 11] = $0 }
          mut_line > 0 {
            # Scan forward up to 5 lines
            pending[mut_line] = 1
          }
        ' "$f" 2>/dev/null || true)
        # Simpler approach: use grep context
        result2=$(grep -n 'Mutation<' "$f" 2>/dev/null | while IFS=: read -r lineno rest; do
          # Check ±5 lines for "experimental"
          start=$(( lineno - 5 ))
          end=$(( lineno + 5 ))
          [ "$start" -lt 1 ] && start=1
          if ! awk "NR>=$start && NR<=$end" "$f" | grep -qi 'experimental'; then
            echo "$f:$lineno: Mutation< without 'experimental' warning nearby"
          fi
        done || true)
        [ -n "$result2" ] && tmp_hits="$tmp_hits"$'\n'"$result2"
      done < <(find "$scanpath" -type f -name '*.md' 2>/dev/null)
    elif [ -f "$scanpath" ]; then
      result2=$(grep -n 'Mutation<' "$scanpath" 2>/dev/null | while IFS=: read -r lineno rest; do
        start=$(( lineno - 5 ))
        end=$(( lineno + 5 ))
        [ "$start" -lt 1 ] && start=1
        if ! awk "NR>=$start && NR<=$end" "$scanpath" | grep -qi 'experimental'; then
          echo "$scanpath:$lineno: Mutation< without 'experimental' warning nearby"
        fi
      done || true)
      [ -n "$result2" ] && tmp_hits="$tmp_hits"$'\n'"$result2"
    fi
  done
  hits="${tmp_hits#$'\n'}"
  emit_tap "v6" \
    "Mutation< usage must have 'experimental' warning within ±5 lines" \
    "$hits" \
    "Add '// experimental API' or prose warning near Mutation< usage"
}

# ── Rule: V11 — runZonedGuarded is forbidden ─────────────────────────────────
rule_v11() {
  local tmp_hits=""
  for scanpath in "${SCAN_PATHS[@]}"; do
    if [ -d "$scanpath" ]; then
      while IFS= read -r f; do
        result=$(grep -n 'runZonedGuarded' "$f" 2>/dev/null || true)
        [ -n "$result" ] && tmp_hits="$tmp_hits"$'\n'"$result"
      done < <(find "$scanpath" -type f -name '*.md' 2>/dev/null)
    elif [ -f "$scanpath" ]; then
      result=$(grep -n 'runZonedGuarded' "$scanpath" 2>/dev/null || true)
      [ -n "$result" ] && tmp_hits="$tmp_hits"$'\n'"$result"
    fi
  done
  hits="${tmp_hits#$'\n'}"
  emit_tap "v11" \
    "runZonedGuarded must not appear" \
    "$hits" \
    "Use Crash.init() before runApp instead"
}

# ── Rule: D5 — README.md must have Core Stack table; SKILL.md must link to it ─
rule_d5() {
  local hits=""

  # Check README.md for Core Stack table
  local readme="$REPO_ROOT/README.md"
  if [ -f "$readme" ]; then
    if ! grep -qi 'Core Stack' "$readme" 2>/dev/null; then
      hits="${hits}${readme}:0: README.md missing 'Core Stack' table"$'\n'
    fi
  else
    hits="${hits}README.md not found"$'\n'
  fi

  # Check SKILL.md links to README for versions
  local skillmd="$REPO_ROOT/SKILL.md"
  if [ -f "$skillmd" ]; then
    if ! grep -qi 'README' "$skillmd" 2>/dev/null; then
      hits="${hits}${skillmd}:0: SKILL.md does not link to README for version table"$'\n'
    fi
  fi

  # Check references/ for inline version pins (outside README/CONTRIBUTING)
  local inline_hits
  inline_hits=$(rg -n --no-heading \
    '(riverpod|flutter_riverpod|go_router|hive|freezed):\s*\^?[0-9]+\.[0-9]+' \
    --glob '!**/README.md' \
    --glob '!**/CONTRIBUTING.md' \
    --glob '!**/AUDIT_REPORT.md' \
    --glob '!**/tool/**' \
    "${SCAN_PATHS[@]}" 2>/dev/null || true)
  [ -n "$inline_hits" ] && hits="${hits}${inline_hits}"$'\n'

  hits="${hits%$'\n'}"
  emit_tap "d5" \
    "Core Stack table in README; no inline version pins in references/" \
    "$hits" \
    "Version pins belong in README.md Core Stack table only (SSOT)"
}

# ── Rule: D7 — build_runner -d shorthand must be accompanied by full flag ─────
rule_d7() {
  local hits="" candidates
  candidates=$(rg -n --no-heading \
    'build_runner.*\s-d(\s|$)' \
    "${RG_EXCLUDE[@]}" \
    "${SCAN_PATHS[@]}" 2>/dev/null || true)
  if [ -n "$candidates" ]; then
    # Filter out lines that already have --delete-conflicting-outputs
    hits=$(printf '%s\n' "$candidates" | grep -v '\-\-delete-conflicting-outputs' || true)
  fi

  emit_tap "d7" \
    "build_runner -d shorthand must be paired with --delete-conflicting-outputs" \
    "$hits" \
    "Always use '--delete-conflicting-outputs' not just '-d'; or add drift-ignore comment"
}

# ── Rule: C1 — mounted guard missing after await before state mutation ─────────
rule_c1() {
  local tmp_hits=""
  for scanpath in "${SCAN_PATHS[@]}"; do
    if [ -d "$scanpath" ]; then
      while IFS= read -r f; do
        result=$(awk '
          /await ref\.(read|watch)\(/ {
            await_line = NR
            found_guard = 0
          }
          await_line > 0 && NR > await_line && NR <= await_line + 3 {
            if (/if[[:space:]]*\(!?ref\.mounted\)/) found_guard = 1
            if (/state[[:space:]]*=/ && !found_guard) {
              print FILENAME ":" NR ": state mutation after await without mounted guard"
              await_line = 0
            }
          }
          await_line > 0 && NR > await_line + 3 { await_line = 0 }
        ' "$f" 2>/dev/null || true)
        [ -n "$result" ] && tmp_hits="$tmp_hits"$'\n'"$result"
      done < <(find "$scanpath" -type f -name '*.md' 2>/dev/null)
    elif [ -f "$scanpath" ]; then
      result=$(awk '
        /await ref\.(read|watch)\(/ {
          await_line = NR
          found_guard = 0
        }
        await_line > 0 && NR > await_line && NR <= await_line + 3 {
          if (/if[[:space:]]*\(!?ref\.mounted\)/) found_guard = 1
          if (/state[[:space:]]*=/ && !found_guard) {
            print FILENAME ":" NR ": state mutation after await without mounted guard"
            await_line = 0
          }
        }
        await_line > 0 && NR > await_line + 3 { await_line = 0 }
      ' "$scanpath" 2>/dev/null || true)
      [ -n "$result" ] && tmp_hits="$tmp_hits"$'\n'"$result"
    fi
  done
  hits="${tmp_hits#$'\n'}"
  emit_tap "c1" \
    "state mutation after await must have ref.mounted guard" \
    "$hits" \
    "Add 'if (!ref.mounted) return;' before 'state =' after any 'await ref.read/watch'"
}

# ── Rule: W1 — no private widget classes (use public + @visibleForTesting) ───
rule_w1() {
  local hits
  # Match: class _Foo extends <widget base>
  # Exempt: State<T> subclasses (Flutter convention requires private).
  hits=$(rg -n --no-heading --pcre2 \
    '^\s*class\s+_\w+\s+extends\s+(StatelessWidget|StatefulWidget|ConsumerWidget|ConsumerStatefulWidget|HookWidget|HookConsumerWidget|StatelessHookConsumerWidget)\b' \
    "${RG_EXCLUDE[@]}" \
    "${SCAN_PATHS[@]}" 2>/dev/null || true)
  emit_tap "w1" \
    "no private widget classes — extract public + @visibleForTesting or new file" \
    "$hits" \
    "Rename 'class _Foo extends StatelessWidget' to public 'class Foo' + @visibleForTesting; State subclasses (_FooState extends State<>) exempt"
}

# ── Main ──────────────────────────────────────────────────────────────────────

echo "TAP version 13"

rule_b3
rule_b7
rule_a4_raw
rule_v7
rule_b4
rule_a1
rule_a4_freezed
rule_v6
rule_v11
rule_d5
rule_d7
rule_c1
rule_w1

echo "1..$_TAP_INDEX"

if [ "$_TAP_FAILS" -gt 0 ]; then
  echo "# FAILED $_TAP_FAILS/$_TAP_INDEX rules"
  exit 1
else
  echo "# All $_TAP_INDEX rules passed"
  exit 0
fi
