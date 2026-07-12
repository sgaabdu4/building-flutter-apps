#!/usr/bin/env bash
# check_drift_test.sh — Fixture-based regression tests for check_drift.sh
#
# For each rule, verifies:
#   positive: violation.md triggers that rule (exit non-zero, rule fails)
#   negative: clean.md passes that rule (rule does not fail)
#
# Usage: bash tool/check_drift_test.sh
# Exit:  0 = all tests pass, 1 = failures found

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CHECKER="$SCRIPT_DIR/check_drift.sh"
FIXTURE_DIR="$SCRIPT_DIR/test_fixtures"

PASS=0
FAIL=0

# ── helpers ──────────────────────────────────────────────────────────────────

pass() { echo "ok - $1"; PASS=$(( PASS + 1 )); }
fail() { echo "not ok - $1"; FAIL=$(( FAIL + 1 )); }

# Run checker against a single file path, keeping only the specified rule.
# Returns the TAP output for that rule only.
run_rule_on_file() {
  local rule_id="$1"
  local filepath="$2"
  # Build the --ignore list: all rules except the one we're testing
  local all_rules="b3 b7 a4-raw v7 b4 a1 a4-freezed v6 v11 d5 d7 c1 w1"
  local ignore_list=""
  for r in $all_rules; do
    if [ "$r" != "$rule_id" ]; then
      if [ -z "$ignore_list" ]; then
        ignore_list="$r"
      else
        ignore_list="${ignore_list},${r}"
      fi
    fi
  done
  bash "$CHECKER" --ignore "$ignore_list" "$filepath" 2>&1 || true
}

# Check whether a specific rule id appears as "not ok" in TAP output
rule_failed_in_output() {
  local rule_id="$1"
  local output="$2"
  echo "$output" | grep -q "^not ok.*${rule_id}:"
}

# Check whether a specific rule id appears as "ok" (not "not ok") in TAP output
rule_passed_in_output() {
  local rule_id="$1"
  local output="$2"
  echo "$output" | grep -q "^ok.*${rule_id}:"
}

# ── test each rule ────────────────────────────────────────────────────────────

test_rule() {
  local rule_id="$1"
  local fixture_dir="$FIXTURE_DIR/$rule_id"
  local violation_file="$fixture_dir/violation.md"
  local clean_file="$fixture_dir/clean.md"

  # Validate fixtures exist
  if [ ! -f "$violation_file" ]; then
    fail "${rule_id}: missing $violation_file"
    return
  fi
  if [ ! -f "$clean_file" ]; then
    fail "${rule_id}: missing $clean_file"
    return
  fi

  # Positive test: violation.md must trigger rule
  local pos_output
  pos_output=$(run_rule_on_file "$rule_id" "$violation_file")
  if rule_failed_in_output "$rule_id" "$pos_output"; then
    pass "${rule_id}: violation.md triggers rule"
  else
    fail "${rule_id}: violation.md did NOT trigger rule"
    echo "  # Output was:"
    echo "$pos_output" | while IFS= read -r line; do echo "  # $line"; done
  fi

  # Negative test: clean.md must NOT trigger rule
  local neg_output
  neg_output=$(run_rule_on_file "$rule_id" "$clean_file")
  if rule_passed_in_output "$rule_id" "$neg_output"; then
    pass "${rule_id}: clean.md passes rule"
  else
    fail "${rule_id}: clean.md incorrectly triggered rule (false positive)"
    echo "  # Output was:"
    echo "$neg_output" | while IFS= read -r line; do echo "  # $line"; done
  fi
}

# ── d5 is special: tests Core Stack ownership + README/SKILL links ────────────
# The d5 violation fixture only tests the inline version pin sub-check (which
# runs on arbitrary paths). The live Core Stack and README/SKILL link checks
# are structural checks on the live repo files — we test them separately.

test_d5_inline_version() {
  local rule_id="d5"
  local violation_file="$FIXTURE_DIR/$rule_id/violation.md"
  local clean_file="$FIXTURE_DIR/$rule_id/clean.md"

  if [ ! -f "$violation_file" ] || [ ! -f "$clean_file" ]; then
    fail "d5: missing fixtures"
    return
  fi

  # For d5, the inline version sub-check runs on the scanned path.
  # Pass it via the positional path arg, ignore all other rules.
  local all_rules="b3 b7 a4-raw v7 b4 a1 a4-freezed v6 v11 d7 c1 w1"
  local ignore_list
  ignore_list=$(echo "$all_rules" | tr ' ' ',')

  local pos_output
  pos_output=$(bash "$CHECKER" --ignore "$ignore_list" "$violation_file" 2>&1 || true)
  if rule_failed_in_output "d5" "$pos_output"; then
    pass "d5: violation.md (inline version pin) triggers rule"
  else
    fail "d5: violation.md (inline version pin) did NOT trigger rule"
    echo "$pos_output" | while IFS= read -r line; do echo "  # $line"; done
  fi

  local neg_output
  neg_output=$(bash "$CHECKER" --ignore "$ignore_list" "$clean_file" 2>&1 || true)
  if rule_passed_in_output "d5" "$neg_output"; then
    pass "d5: clean.md (no inline version pin) passes rule"
  else
    fail "d5: clean.md (no inline version pin) incorrectly triggered rule"
    echo "$neg_output" | while IFS= read -r line; do echo "  # $line"; done
  fi
}

# ── main ─────────────────────────────────────────────────────────────────────

echo "TAP version 13"
echo "# check_drift_test.sh — fixture tests"
echo ""

# Simple rg-based rules
test_rule "b3"
test_rule "b7"
test_rule "a4-raw"
test_rule "a1"
test_rule "v7"

# awk-based multi-line rules
test_rule "b4"
test_rule "a4-freezed"
test_rule "v6"
test_rule "v11"
test_rule "c1"

# file-level + inline rules
test_d5_inline_version
test_rule "d7"

# widget rules
test_rule "w1"

TOTAL=$(( PASS + FAIL ))
echo ""
echo "1..$TOTAL"
echo "# Results: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
