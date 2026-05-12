#!/usr/bin/env bash
# Smoke test for the `building-flutter-apps` Claude Code plugin.
# Run from any directory. Builds a temp Flutter project, drives each hook end-to-end
# with crafted violators + clean fixtures, asserts every rule fires correctly and
# nothing fires on clean code. Use this before publishing a release.

set -uo pipefail

# Locate plugin root (the directory containing .claude-plugin/plugin.json)
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PLUGIN_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
if [[ ! -f "$PLUGIN_ROOT/.claude-plugin/plugin.json" ]]; then
  echo "✗ Cannot locate plugin root. Expected .claude-plugin/plugin.json at $PLUGIN_ROOT" >&2
  exit 1
fi

HOOK="$PLUGIN_ROOT/hooks/scripts/dart_gate.sh"
PREFLIGHT="$PLUGIN_ROOT/hooks/scripts/preflight_audit.sh"
REMINDER="$PLUGIN_ROOT/hooks/scripts/skill_reminder.sh"

for f in "$HOOK" "$PREFLIGHT" "$REMINDER"; do
  if [[ ! -x "$f" ]]; then
    echo "✗ Missing or non-executable: $f" >&2
    exit 1
  fi
done

PASS=0
FAIL=0

report() {
  if [[ "$1" == "pass" ]]; then
    echo "  ✓ $2"
    PASS=$((PASS+1))
  else
    echo "  ✗ $2"
    FAIL=$((FAIL+1))
  fi
}

# --------- 1. Manifest validity ---------
echo "── 1. Plugin manifest ──"
if command -v claude >/dev/null 2>&1; then
  if claude plugin validate "$PLUGIN_ROOT" >/dev/null 2>&1; then
    report pass "claude plugin validate"
  else
    report fail "claude plugin validate (run manually to see error)"
  fi
else
  report pass "claude CLI not on PATH — skipping validate (install Claude Code to enable)"
fi

# --------- 2. JSON syntax ---------
echo ""
echo "── 2. JSON syntax ──"
for f in \
  "$PLUGIN_ROOT/.claude-plugin/plugin.json" \
  "$PLUGIN_ROOT/.claude-plugin/marketplace.json" \
  "$PLUGIN_ROOT/.codex-plugin/plugin.json" \
  "$PLUGIN_ROOT/plugin.json" \
  "$PLUGIN_ROOT/.github/plugin/marketplace.json" \
  "$PLUGIN_ROOT/hooks/hooks.json" \
  "$PLUGIN_ROOT/hooks/hooks.copilot.json"; do
  if python3 -c "import json; json.load(open('$f'))" 2>/dev/null; then
    report pass "$(basename "$(dirname "$f")")/$(basename "$f")"
  else
    report fail "$(basename "$(dirname "$f")")/$(basename "$f")"
  fi
done

# --------- 3. Shell syntax ---------
echo ""
echo "── 3. Shell syntax ──"
for f in "$HOOK" "$PREFLIGHT" "$REMINDER"; do
  bash -n "$f" 2>/dev/null && report pass "$(basename "$f")" || report fail "$(basename "$f")"
done

# --------- 4. Build temp Flutter project + fixtures ---------
echo ""
echo "── 4. End-to-end hook fixtures ──"
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT

mkdir -p "$TEST_DIR/lib/features/orders/presentation"
mkdir -p "$TEST_DIR/lib/features/orders/data/datasources"
mkdir -p "$TEST_DIR/test"
echo "name: smoke_test
description: building-flutter-apps smoke fixture
environment:
  sdk: ^3.0.0" > "$TEST_DIR/pubspec.yaml"
touch "$TEST_DIR/analysis_options.yaml"

# Violator (5 old rules)
cat > "$TEST_DIR/lib/violator.dart" <<'EOF'
import 'package:flutter/material.dart';
class HomeScreen extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Column(children: [_buildHeader(), Text('Welcome User')]);
  }
  Widget _buildHeader() => const SizedBox();
}
class _PrivateCard extends StatelessWidget { const _PrivateCard(); }
void doStuff(dynamic x) {}
final list = ListView(shrinkWrap: true, children: const []);
EOF

# Clean (no rules)
cat > "$TEST_DIR/lib/clean.dart" <<'EOF'
import 'package:flutter/material.dart';
class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});
  @override
  Widget build(BuildContext context) => const SizedBox();
}
Map<String, dynamic> json = {};
EOF

# Storage in notifier (new rule 13)
cat > "$TEST_DIR/lib/features/orders/presentation/orders_notifier.dart" <<'EOF'
import 'package:hive_ce/hive.dart';
class OrdersNotifier {
  Future<void> load() async { Hive.openBox('orders'); }
}
EOF

# Prop-drill non-suffix (new rule 14, allowlist)
cat > "$TEST_DIR/lib/widget_propdrill.dart" <<'EOF'
import 'package:flutter/material.dart';
class FoodCard extends StatelessWidget {
  const FoodCard({super.key, required this.food});
  final Food food;
  @override
  Widget build(BuildContext context) => const SizedBox();
}
EOF

# Datasource — storage allowed
cat > "$TEST_DIR/lib/features/orders/data/datasources/orders_local_datasource.dart" <<'EOF'
import 'package:hive_ce/hive.dart';
class OrdersLocalDatasourceImpl {
  Future<void> save() async { Hive.openBox('orders'); }
}
EOF

# main.dart — storage init allowed
cat > "$TEST_DIR/lib/main.dart" <<'EOF'
import 'package:hive_ce_flutter/hive_flutter.dart';
void main() async { await Hive.initFlutter(); }
EOF

# Test file — storage allowed
cat > "$TEST_DIR/test/foo_test.dart" <<'EOF'
import 'package:hive_ce/hive.dart';
void main() { Hive.openBox('test'); }
EOF

# Clean widget — only allowlist types
cat > "$TEST_DIR/lib/widget_clean.dart" <<'EOF'
import 'package:flutter/material.dart';
class CleanWidget extends StatelessWidget {
  const CleanWidget({super.key, required this.id, required this.onTap, this.color});
  final String id;
  final VoidCallback onTap;
  final Color? color;
  @override
  Widget build(BuildContext context) => const SizedBox();
}
EOF

assert_block() {
  local name="$1" file="$2"
  echo "{\"tool_input\":{\"file_path\":\"$file\"}}" | "$HOOK" > /tmp/smoke_out.json 2>/dev/null
  if [[ -s /tmp/smoke_out.json ]]; then
    DEC=$(python3 -c "import json; print(json.load(open('/tmp/smoke_out.json')).get('decision',''))" 2>/dev/null)
    [[ "$DEC" == "block" ]] && report pass "$name" || report fail "$name (decision=$DEC)"
  else
    report fail "$name (expected block, got silent)"
  fi
}

assert_silent() {
  local name="$1" file="$2"
  echo "{\"tool_input\":{\"file_path\":\"$file\"}}" | "$HOOK" > /tmp/smoke_out.json 2>/dev/null
  [[ ! -s /tmp/smoke_out.json ]] && report pass "$name" || report fail "$name (expected silent)"
}

assert_block  "violator → 5 old rules fire"             "$TEST_DIR/lib/violator.dart"
assert_silent "clean Map<String, dynamic>"              "$TEST_DIR/lib/clean.dart"
assert_block  "storage SDK in notifier"                 "$TEST_DIR/lib/features/orders/presentation/orders_notifier.dart"
assert_block  "prop-drill non-suffix domain"            "$TEST_DIR/lib/widget_propdrill.dart"
assert_silent "datasource (storage allowed)"            "$TEST_DIR/lib/features/orders/data/datasources/orders_local_datasource.dart"
assert_silent "main.dart Hive.initFlutter (allowed)"    "$TEST_DIR/lib/main.dart"
assert_silent "test/ file Hive (allowed)"               "$TEST_DIR/test/foo_test.dart"
assert_silent "widget — only allowlist types"           "$TEST_DIR/lib/widget_clean.dart"

# --------- 5. Stop hook ---------
echo ""
echo "── 5. Stop hook (preflight_audit.sh) ──"
CLAUDE_PROJECT_DIR="$TEST_DIR" "$PREFLIGHT" > /tmp/smoke_pf.json 2>/dev/null
if [[ -s /tmp/smoke_pf.json ]]; then
  report pass "dirty Flutter project → block"
else
  report fail "dirty Flutter project (expected block)"
fi

NON_FL=$(mktemp -d)
CLAUDE_PROJECT_DIR="$NON_FL" "$PREFLIGHT" > /tmp/smoke_pf2.json 2>/dev/null
[[ ! -s /tmp/smoke_pf2.json ]] && report pass "non-Flutter dir → silent" || report fail "non-Flutter dir (expected silent)"
rm -rf "$NON_FL"

# --------- 6. UserPromptSubmit ---------
echo ""
echo "── 6. UserPromptSubmit hook (skill_reminder.sh) ──"
CLAUDE_PROJECT_DIR="$TEST_DIR" "$REMINDER" > /tmp/smoke_sr.json 2>/dev/null
grep -q 'building-flutter-apps active' /tmp/smoke_sr.json 2>/dev/null && report pass "Flutter project → reminder injected" || report fail "reminder missing"

NON_FL2=$(mktemp -d)
CLAUDE_PROJECT_DIR="$NON_FL2" "$REMINDER" > /tmp/smoke_sr2.json 2>/dev/null
[[ ! -s /tmp/smoke_sr2.json ]] && report pass "non-Flutter dir → silent" || report fail "non-Flutter reminder fired"
rm -rf "$NON_FL2"

# --------- 7. Doc drift ---------
echo ""
echo "── 7. tool/check_drift.sh ──"
bash "$PLUGIN_ROOT/tool/check_drift.sh" > /dev/null 2>&1 && report pass "check_drift 13/13" || report fail "check_drift failed (run manually to see)"

# --------- Result ---------
echo ""
echo "════════════════════════════════════════"
echo "  PASS: $PASS    FAIL: $FAIL"
echo "════════════════════════════════════════"

rm -f /tmp/smoke_out.json /tmp/smoke_pf.json /tmp/smoke_pf2.json /tmp/smoke_sr.json /tmp/smoke_sr2.json

if [[ $FAIL -gt 0 ]]; then
  echo "Smoke test FAILED. Do not publish."
  exit 1
else
  echo "Smoke test PASSED. Safe to publish."
  exit 0
fi
