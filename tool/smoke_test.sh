#!/usr/bin/env bash
# Smoke test for the `building-flutter-apps` skill and plugin packages.
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
  "$PLUGIN_ROOT/.agents/plugins/marketplace.json" \
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

if python3 - "$PLUGIN_ROOT" <<'PY'
import json
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
claude = json.loads((root / ".claude-plugin/plugin.json").read_text())
claude_marketplace = json.loads((root / ".claude-plugin/marketplace.json").read_text())
codex = json.loads((root / ".codex-plugin/plugin.json").read_text())
codex_marketplace = json.loads((root / ".agents/plugins/marketplace.json").read_text())
copilot = json.loads((root / "plugin.json").read_text())
copilot_marketplace = json.loads((root / ".github/plugin/marketplace.json").read_text())
skill = root / "skills/building-flutter-apps"
expected_version = "5.5.6"

assert not (root / "hooks/hooks.codex.json").exists()
assert not (root / "SKILL.md").exists()
assert (skill / "SKILL.md").is_file()
assert (skill / "references/setup.md").is_file()
assert (skill / "references/dart-decimate.md").is_file()
assert (skill / "references/analysis_options.yaml").is_file()
assert (skill / "templates/flutter/lib/core/extensions/extensions.dart").is_file()
assert not any((skill / "templates/flutter/tool").glob("*"))
for pattern in ("*.md", "*.sh", "*.py"):
    for path in skill.rglob(pattern):
        assert ".agents/skills/deterministic-checks" not in path.read_text(), path
assert claude.get("version") == expected_version
assert codex.get("version") == expected_version
assert copilot.get("version") == expected_version
assert claude_marketplace["metadata"]["version"] == expected_version
assert claude_marketplace["plugins"][0]["version"] == expected_version
assert copilot_marketplace["metadata"]["version"] == expected_version
assert copilot_marketplace["plugins"][0]["version"] == expected_version
assert f'version: "{expected_version}"' in (skill / "SKILL.md").read_text()
assert "hooks" not in claude
assert "skills" not in claude
assert "hooks" not in codex
assert (root / "hooks/hooks.json").is_file()
assert codex.get("skills") == "./skills/"
assert codex_marketplace.get("name") == "building-flutter-apps"
assert codex_marketplace.get("plugins", [])[0].get("name") == "building-flutter-apps"
assert codex_marketplace["plugins"][0]["source"] == {
    "source": "url",
    "url": "https://github.com/sgaabdu4/building-flutter-apps.git",
    "ref": "main",
}
assert copilot.get("hooks") == "hooks/hooks.copilot.json"

for path in skill.rglob("*.md"):
    text = path.read_text()
    assert not re.search(
        r"(?m)Claude Code|\bCodex\b|\bCopilot\b|\bChatGPT\b|\bAnthropic\b|\bOpenAI\b|(?:^|[`\s])/(?:plugin|reload-plugins)\b|\$building-flutter-apps",
        text,
        re.IGNORECASE,
    ), f"harness-specific instruction leaked into installed skill: {path}"

shared_hooks = json.loads((root / "hooks/hooks.json").read_text())
commands = [
    hook["command"]
    for groups in shared_hooks["hooks"].values()
    for group in groups
    for hook in group["hooks"]
]
assert commands
assert all("PLUGIN_ROOT" in command for command in commands)
assert all("CLAUDE_PLUGIN_ROOT" in command for command in commands)
assert all("CODEX_PLUGIN_ROOT" not in command for command in commands)
assert all(".codex/plugins/cache" not in command for command in commands)
PY
then
  report pass "runtime manifests wire hooks"
else
  report fail "runtime manifests wire hooks"
fi

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
mkdir -p "$TEST_DIR/lib/l10n"
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

# Immutable view-data input is canonical for reusable widgets.
cat > "$TEST_DIR/lib/widget_view_data.dart" <<'EOF'
import 'package:flutter/material.dart';
final class FoodCardViewData {
  const FoodCardViewData({required this.name});
  final String name;
}
class FoodCard extends StatelessWidget {
  const FoodCard({super.key, required this.data, required this.onTap});
  final FoodCardViewData data;
  final ValueChanged<FoodCardViewData> onTap;
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
  const CleanWidget({super.key, required this.id, required this.onTap, required this.onReorder, this.color});
  final String id;
  final VoidCallback onTap;
  final ReorderCallback onReorder;
  final Color? color;
  @override
  Widget build(BuildContext context) => const SizedBox();
}
EOF

# Generated l10n output — hook must stay silent
cat > "$TEST_DIR/lib/l10n/app_localizations.dart" <<'EOF'
class LocalizationsDelegate<T> {}
abstract class AppLocalizations {
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[];
}
EOF

# Test fixtures may contain hardcoded UI strings
cat > "$TEST_DIR/test/hardcoded_text_test.dart" <<'EOF'
class Text {
  const Text(String value);
}

void main() {
  const Text('Login destination');
}
EOF

# Generated typed route helper call
cat > "$TEST_DIR/lib/direct_route_call.dart" <<'EOF'
void open(context, String id) {
  ProductDetailRoute(id: id).go(context);
}
EOF

# Raw context navigation with typed location
cat > "$TEST_DIR/lib/context_route_call.dart" <<'EOF'
void open(context, String id) {
  context.go(ProductDetailRoute(id: id).location);
}
EOF

# Raw router string navigation
cat > "$TEST_DIR/lib/raw_router_string.dart" <<'EOF'
class GoRouter {
  void go(String location) {}
  Future<T?> pushNamed<T>(String name) async => null;
}

void open(GoRouter router) {
  router.go('/home');
}
EOF

# Camel-case router variable navigation
cat > "$TEST_DIR/lib/raw_app_router_string.dart" <<'EOF'
class GoRouter {
  void go(String location) {}
}

void open(GoRouter appRouter) {
  appRouter.go('/home');
}
EOF

# Router route-specific helper bypass
cat > "$TEST_DIR/lib/router_go_home.dart" <<'EOF'
void open(router) {
  router.goHome();
}
EOF

# Route wrapper function bypass
cat > "$TEST_DIR/lib/route_wrapper_function.dart" <<'EOF'
void open(router) {
  navigateToHomeRoute(router);
}
EOF

# Router navigatorKey context escape
cat > "$TEST_DIR/lib/router_navigator_context.dart" <<'EOF'
void open(router) {
  final navigatorContext = router.routerDelegate.navigatorKey.currentContext;
  if (navigatorContext == null) return;
  const HomeRoute().go(navigatorContext);
}
EOF

# ConsumerState provider-derived cache/source fields
cat > "$TEST_DIR/lib/consumer_state_cache.dart" <<'EOF'
class AddExerciseSheet extends ConsumerStatefulWidget {}

class _AddExerciseSheetState extends ConsumerState<AddExerciseSheet> {
  List<Object>? _availableExercisesSource;
  List<Object> _availableExercisesCache = const [];

  Object build(context) {
    final items = ref.watch(itemsProvider.select((state) => state.items));
    return items;
  }
}
EOF

# Named router navigation
cat > "$TEST_DIR/lib/raw_router_named.dart" <<'EOF'
class GoRouter {
  Future<T?> pushNamed<T>(String name) async => null;
}

Future<T?> open<T>(GoRouter router) {
  return router.pushNamed<T>('home');
}
EOF

# Route fallback helper
cat > "$TEST_DIR/lib/fallback_route_call.dart" <<'EOF'
void popWithFallback(fallbackRoute) {
  fallbackRoute.go(this);
}
EOF

# Navigator dismissal for local modals
cat > "$TEST_DIR/lib/direct_navigator_call.dart" <<'EOF'
void close(context) {
  Navigator.of(context).maybePop();
}
EOF

# Shell branch navigation
cat > "$TEST_DIR/lib/direct_shell_call.dart" <<'EOF'
void selectTab(navigationShell) {
  navigationShell.goBranch(1);
}
EOF

# Local modal helper
cat > "$TEST_DIR/lib/direct_modal_call.dart" <<'EOF'
void confirm(context) {
  showDialog<bool>(context: context, builder: (_) => null);
}
EOF

# l10n.yaml — gen-l10n path config
cat > "$TEST_DIR/l10n.yaml" <<'EOF'
arb-dir: lib/l10n
synthetic-package: false
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
assert_silent "immutable widget view data"              "$TEST_DIR/lib/widget_view_data.dart"
assert_silent "datasource (storage allowed)"            "$TEST_DIR/lib/features/orders/data/datasources/orders_local_datasource.dart"
assert_silent "main.dart Hive.initFlutter (allowed)"    "$TEST_DIR/lib/main.dart"
assert_silent "test/ file Hive (allowed)"               "$TEST_DIR/test/foo_test.dart"
assert_silent "widget — only allowlist types"           "$TEST_DIR/lib/widget_clean.dart"
assert_silent "generated app localizations"             "$TEST_DIR/lib/l10n/app_localizations.dart"
assert_silent "test hardcoded UI text"                  "$TEST_DIR/test/hardcoded_text_test.dart"
assert_silent "generated typed route helper"            "$TEST_DIR/lib/direct_route_call.dart"
assert_block  "context route helper bypass"             "$TEST_DIR/lib/context_route_call.dart"
assert_block  "raw router string navigation"            "$TEST_DIR/lib/raw_router_string.dart"
assert_block  "raw appRouter string navigation"         "$TEST_DIR/lib/raw_app_router_string.dart"
assert_block  "router convenience navigation"           "$TEST_DIR/lib/router_go_home.dart"
assert_block  "route wrapper function navigation"       "$TEST_DIR/lib/route_wrapper_function.dart"
assert_block  "router navigator context navigation"     "$TEST_DIR/lib/router_navigator_context.dart"
assert_block  "ConsumerState provider-derived cache"    "$TEST_DIR/lib/consumer_state_cache.dart"
assert_block  "named router navigation"                 "$TEST_DIR/lib/raw_router_named.dart"
assert_silent "fallback route helper"                   "$TEST_DIR/lib/fallback_route_call.dart"
assert_silent "navigator local dismissal"               "$TEST_DIR/lib/direct_navigator_call.dart"
assert_silent "shell branch navigation"                 "$TEST_DIR/lib/direct_shell_call.dart"
assert_silent "local modal helper"                      "$TEST_DIR/lib/direct_modal_call.dart"
assert_block  "l10n path config guard"                  "$TEST_DIR/l10n.yaml"
cat > "$TEST_DIR/l10n.yaml" <<'EOF'
arb-dir: lib/l10n
output-localization-file: app_localizations.dart
EOF
assert_silent "l10n path config"                        "$TEST_DIR/l10n.yaml"

# --------- 5. Stop hook ---------
echo ""
echo "── 5. Stop hook (preflight_audit.sh) ──"
TEST_BIN="$TEST_DIR/test-bin"
DECIMATE_LOG="$TEST_DIR/dart-decimate.log"
mkdir -p "$TEST_BIN"
cat > "$TEST_BIN/dart" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat > "$TEST_BIN/npx" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DART_DECIMATE_LOG"
printf '{"verdict":"pass"}\n'
exit 0
EOF
chmod +x "$TEST_BIN/dart" "$TEST_BIN/npx"

PATH="$TEST_BIN:$PATH" DART_DECIMATE_LOG="$DECIMATE_LOG" CLAUDE_PROJECT_DIR="$TEST_DIR" "$PREFLIGHT" > /tmp/smoke_pf.json 2>/dev/null
if [[ -s /tmp/smoke_pf.json ]]; then
  report pass "dirty Flutter project → block"
else
  report fail "dirty Flutter project (expected block)"
fi
if grep -q -- '--yes dart-decimate@latest json .' "$DECIMATE_LOG" 2>/dev/null; then
  report pass "new/no-base Flutter project → Dart Decimate full scan"
else
  report fail "Dart Decimate full scan missing"
fi

NON_FL=$(mktemp -d)
PATH="$TEST_BIN:$PATH" DART_DECIMATE_LOG="$DECIMATE_LOG" CLAUDE_PROJECT_DIR="$NON_FL" "$PREFLIGHT" > /tmp/smoke_pf2.json 2>/dev/null
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
