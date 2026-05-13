#!/usr/bin/env bash
# PostToolUse hook for Write|Edit|MultiEdit.
# Fires on .dart files and l10n.yaml inside a Flutter project (pubspec.yaml present in ancestor).
# Runs ERE grep + awk context checks to catch grep-able rule violations.
# Always exits 0. Violations emitted as JSON {"decision":"block","reason":"..."} on stdout,
# which Claude Code interprets as a block + feedback message.

set -uo pipefail

# Read hook input JSON from stdin (jq if available, fallback to env var)
INPUT_JSON=""
if [[ ! -t 0 ]]; then
  INPUT_JSON=$(cat || true)
fi

FILE_PATH="${CLAUDE_TOOL_INPUT_FILE_PATH:-}"
if [[ -z "$FILE_PATH" ]] && command -v jq >/dev/null 2>&1 && [[ -n "$INPUT_JSON" ]]; then
  FILE_PATH=$(printf '%s' "$INPUT_JSON" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)
fi

[[ -z "$FILE_PATH" ]] && exit 0

# Walk up to find pubspec.yaml. No pubspec = not a Flutter project = exit silently.
find_flutter_root() {
  local d
  d=$(dirname "$1")
  while [[ "$d" != "/" && -n "$d" ]]; do
    if [[ -f "$d/pubspec.yaml" ]]; then
      printf '%s' "$d"
      return 0
    fi
    d=$(dirname "$d")
  done
  return 1
}

PROJECT_ROOT=$(find_flutter_root "$FILE_PATH") || exit 0
[[ -z "$PROJECT_ROOT" ]] && exit 0

# File must exist for checks to run
[[ -f "$FILE_PATH" ]] || exit 0

emit_block() {
  local reason="$1"
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import json,sys; print(json.dumps({'decision':'block','reason':sys.stdin.read()}))" <<<"$reason"
  else
    local escaped="$reason"
    escaped=${escaped//\\/\\\\}
    escaped=${escaped//\"/\\\"}
    escaped=${escaped//$'\n'/\\n}
    printf '{"decision":"block","reason":"%s"}\n' "$escaped"
  fi
}

case "$FILE_PATH" in
  */l10n.yaml|l10n.yaml)
    MATCHES=$(awk '/^[[:space:]]*synthetic-package[[:space:]]*:/ { print NR ":" $0 }' "$FILE_PATH" 2>/dev/null)
    if [[ -n "$MATCHES" ]]; then
      REASON="building-flutter-apps gate blocked the write. Fix these before retrying:"
      while IFS=: read -r lineno content; do
        [[ -z "$lineno" ]] && continue
        content="${content#"${content%%[![:space:]]*}"}"
        REASON+=$'\n'"  $FILE_PATH:$lineno [gen-l10n-paths]: configure gen-l10n paths explicitly: ARB in arb-dir; generated Dart in arb-dir or output-dir; import app_localizations.dart from that directory."
      done <<< "$MATCHES"
      emit_block "$REASON"
    fi
    exit 0
    ;;
esac

# Bail fast when not a Dart source file.
case "$FILE_PATH" in
  *.dart) ;;
  *) exit 0 ;;
esac

# Skip generated files
case "$FILE_PATH" in
  *.g.dart|*.freezed.dart|*.gr.dart|*.config.dart|*.mocks.dart) exit 0 ;;
esac

VIOLATIONS=()

# add_match consumes `<lineno>:<content>` lines from $1 (a pipeline result captured into a variable)
# and appends each as a formatted violation. Runs in current shell — no subshell array loss.
add_match() {
  local rule="$1"
  local fix="$2"
  local matches="$3"
  local lineno content
  if [[ -z "$matches" ]]; then
    return 0
  fi
  while IFS=: read -r lineno content; do
    [[ -z "$lineno" ]] && continue
    # Trim leading whitespace from content
    content="${content#"${content%%[![:space:]]*}"}"
    VIOLATIONS+=("  $FILE_PATH:$lineno [$rule]: ${content:0:120}  → Fix: $fix")
  done <<< "$matches"
}

# ---------- Rule 1: _buildXxx() method declaration ----------
MATCHES=$(awk '
  # POSIX awk has no \b; use (^|[^A-Za-z0-9_]) for word-start.
  /(^|[^A-Za-z0-9_])_build[A-Z][A-Za-z0-9_]*[[:space:]]*\(/ {
    if ($0 ~ /\._build[A-Z]/) next
    if ($0 ~ /^[[:space:]]*return[[:space:]]+_build[A-Z]/) next
    if ($0 ~ /(=>|\{[[:space:]]*$|async[[:space:]]*\{?)/) {
      print NR ":" $0
    }
  }
' "$FILE_PATH" 2>/dev/null)
add_match "no-build-helpers" \
  "Extract to a public widget class (or @visibleForTesting if file-internal). State subclasses exempt." \
  "$MATCHES"

# ---------- Rule 2: Private widget class (excluding State<T>) ----------
MATCHES=$(grep -nE 'class[[:space:]]+_[A-Z][A-Za-z0-9_]*[[:space:]]+extends[[:space:]]+(StatelessWidget|StatefulWidget|ConsumerWidget|ConsumerStatefulWidget|HookWidget|HookConsumerWidget)' "$FILE_PATH" 2>/dev/null)
add_match "no-private-widget-class" \
  "Use a public widget class. Mark file-internal widgets @visibleForTesting. State<T> subclasses are exempt and stay private." \
  "$MATCHES"

# ---------- Rule 3: dynamic (excluding Map<String, dynamic> JSON shape) ----------
MATCHES=$(awk '
  /(^|[^A-Za-z0-9_])dynamic([^A-Za-z0-9_]|$)/ {
    line = $0
    if (line ~ /Map[[:space:]]*<[[:space:]]*[A-Za-z0-9_]+[[:space:]]*,[[:space:]]*dynamic[[:space:]]*>/) next
    if (line ~ /List[[:space:]]*<[[:space:]]*dynamic[[:space:]]*>/) next
    if (line ~ /^[[:space:]]*\/\//) next
    if (line ~ /typedef[[:space:]]+Json/) next
    if (line ~ /flutter-skill: allow-dynamic/) next
    print NR ":" $0
  }
' "$FILE_PATH" 2>/dev/null)
add_match "no-dynamic" \
  "Use Object? or a specific type. Map<String, dynamic> is allowed for JSON shapes." \
  "$MATCHES"

# ---------- Rule 4: shrinkWrap: true ----------
MATCHES=$(grep -nE 'shrinkWrap:[[:space:]]*true' "$FILE_PATH" 2>/dev/null)
add_match "no-shrinkwrap-true" \
  "Use slivers or fix the real viewport constraint. shrinkWrap forces expensive layout." \
  "$MATCHES"

# ---------- Rule 5: Manual legacy providers ----------
MATCHES=$(awk '
  /(^|[^A-Za-z0-9_])(FutureProvider|StreamProvider|StateProvider|StateNotifierProvider|NotifierProvider|AsyncNotifierProvider|ChangeNotifierProvider)[[:space:]]*\(/ {
    line = $0
    if (line ~ /(^|[^A-Za-z0-9_])(extends|implements|class|is|as)([^A-Za-z0-9_]|$)/) next
    if (line ~ /^[[:space:]]*\/\//) next
    if (line ~ /_\$[A-Z]/) next
    print NR ":" $0
  }
' "$FILE_PATH" 2>/dev/null)
add_match "use-riverpod-codegen" \
  "Use @riverpod or @Riverpod(keepAlive: true) codegen. Run dart run build_runner watch --delete-conflicting-outputs." \
  "$MATCHES"

# ---------- Rule 6: Hardcoded UI string in Text('...') ----------
MATCHES=$(grep -nE "Text[[:space:]]*\([[:space:]]*['\"][A-Z][A-Za-z][A-Za-z ]{2,}['\"]" "$FILE_PATH" 2>/dev/null)
add_match "use-applocalizations" \
  "Use AppLocalizations.of(context).key. Hardcoded UI strings are not localizable." \
  "$MATCHES"

# ---------- Rule 6b: Feature presentation notifiers should be keepAlive ----------
case "$FILE_PATH" in
  */lib/features/*/presentation/notifiers/*_notifier.dart)
    MATCHES=$(awk '
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

          print i ":" line[i]
        }
      }
    ' "$FILE_PATH" 2>/dev/null)
    add_match "riverpod-feature-notifier-keepalive" \
      "Feature presentation notifiers should use @Riverpod(keepAlive: true), or document why the state is ephemeral. Family notifiers and lifecycle-cleanup notifiers are exempt." \
      "$MATCHES"
    ;;
esac

# ---------- Rule 7: Inline string ValueKey ----------
MATCHES=$(grep -nE "ValueKey[[:space:]]*\([[:space:]]*['\"]" "$FILE_PATH" 2>/dev/null)
add_match "use-app-widget-keys" \
  "Use AppWidgetKeys.<name>. Inline string ValueKey defeats the central key registry." \
  "$MATCHES"

# ---------- Rule 8: raw or named route navigation ----------
CONTEXT_STRING_MATCHES=$(grep -nE "(^|[^A-Za-z0-9_])context[[:space:]]*\.[[:space:]]*(go|push|replace|pushReplacement)[[:space:]]*(<[^>]+>)?[[:space:]]*\([[:space:]]*r?['\"]" "$FILE_PATH" 2>/dev/null)
CONTEXT_NAMED_MATCHES=$(grep -nE "(^|[^A-Za-z0-9_])context[[:space:]]*\.[[:space:]]*(goNamed|pushNamed|replaceNamed)[[:space:]]*(<[^>]+>)?[[:space:]]*\(" "$FILE_PATH" 2>/dev/null)
GOROUTER_STRING_MATCHES=$(grep -nE "(^|[^A-Za-z0-9_])GoRouter[[:space:]]*\.[[:space:]]*of[[:space:]]*\([^)]*\)[[:space:]]*\.[[:space:]]*(go|push|replace|pushReplacement)[[:space:]]*(<[^>]+>)?[[:space:]]*\([[:space:]]*r?['\"]" "$FILE_PATH" 2>/dev/null)
GOROUTER_NAMED_MATCHES=$(grep -nE "(^|[^A-Za-z0-9_])GoRouter[[:space:]]*\.[[:space:]]*of[[:space:]]*\([^)]*\)[[:space:]]*\.[[:space:]]*(goNamed|pushNamed|replaceNamed)[[:space:]]*(<[^>]+>)?[[:space:]]*\(" "$FILE_PATH" 2>/dev/null)
ROUTER_STRING_MATCHES=$(grep -nE "(^|[^A-Za-z0-9_])(_?router|[A-Za-z_][A-Za-z0-9_]*Router[A-Za-z0-9_]*)[[:space:]]*\.[[:space:]]*(go|push|replace|pushReplacement)[[:space:]]*(<[^>]+>)?[[:space:]]*\([[:space:]]*r?['\"]" "$FILE_PATH" 2>/dev/null)
ROUTER_NAMED_MATCHES=$(grep -nE "(^|[^A-Za-z0-9_])(_?router|[A-Za-z_][A-Za-z0-9_]*Router[A-Za-z0-9_]*)[[:space:]]*\.[[:space:]]*(goNamed|pushNamed|replaceNamed)[[:space:]]*(<[^>]+>)?[[:space:]]*\(" "$FILE_PATH" 2>/dev/null)
INITIAL_LOCATION_MATCHES=$(grep -nE "(^|[^A-Za-z0-9_])initialLocation[[:space:]]*:[[:space:]]*r?['\"]" "$FILE_PATH" 2>/dev/null)
MATCHES="$CONTEXT_STRING_MATCHES"
for EXTRA_MATCHES in "$CONTEXT_NAMED_MATCHES" "$GOROUTER_STRING_MATCHES" "$GOROUTER_NAMED_MATCHES" "$ROUTER_STRING_MATCHES" "$ROUTER_NAMED_MATCHES" "$INITIAL_LOCATION_MATCHES"; do
  if [[ -n "$EXTRA_MATCHES" ]]; then
    MATCHES="${MATCHES:+$MATCHES$'\n'}$EXTRA_MATCHES"
  fi
done
add_match "use-typed-routes" \
  "Use generated typed route helpers. Route definitions own paths; raw string and named route navigation are forbidden." \
  "$MATCHES"

# ---------- Rule 9: raw page navigation should use generated helpers ----------
case "$FILE_PATH" in
  *.g.dart) ;;
  *)
    CONTEXT_MATCHES=$(grep -nE "(^|[^A-Za-z0-9_])context[[:space:]]*\.[[:space:]]*(go|push|replace|pushReplacement|goNamed|pushNamed|replaceNamed)[[:space:]]*(<[^>]+>)?[[:space:]]*\(" "$FILE_PATH" 2>/dev/null)
    ROUTER_MATCHES=$(grep -nE "(^|[^A-Za-z0-9_])(_?router|[A-Za-z_][A-Za-z0-9_]*Router[A-Za-z0-9_]*)[[:space:]]*\.[[:space:]]*(go|push|replace|pushReplacement|goNamed|pushNamed|replaceNamed)[[:space:]]*(<[^>]+>)?[[:space:]]*\(" "$FILE_PATH" 2>/dev/null)
    NAVIGATOR_MATCHES=$(grep -nE "(^|[^A-Za-z0-9_])Navigator[[:space:]]*(\.[[:space:]]*of[[:space:]]*\([^)]*\)[[:space:]]*)?\.[[:space:]]*(push|pushReplacement|pushAndRemoveUntil|pushNamed|pushReplacementNamed|restorablePush|restorablePushNamed)[[:space:]]*(<[^>]+>)?[[:space:]]*\(" "$FILE_PATH" 2>/dev/null)
    MATCHES=""
    for EXTRA_MATCHES in "$CONTEXT_MATCHES" "$ROUTER_MATCHES" "$NAVIGATOR_MATCHES"; do
      if [[ -n "$EXTRA_MATCHES" ]]; then
        MATCHES="${MATCHES:+$MATCHES$'\n'}$EXTRA_MATCHES"
      fi
    done
    add_match "use-typed-route-helpers" \
      "Call generated typed route helpers for page navigation. Local dialog/sheet dismissal may use Navigator.pop/maybePop." \
      "$MATCHES"
    ;;
esac

# ---------- Rule 10: abstract class + @freezed (multi-line context) ----------
MATCHES=$(awk '
  /@freezed/ { freezed = 1; next }
  freezed && /^[[:space:]]*abstract[[:space:]]+class[[:space:]]+/ {
    print NR ":" $0
    freezed = 0
  }
  freezed && /^[[:space:]]*(sealed|class)[[:space:]]+/ { freezed = 0 }
' "$FILE_PATH" 2>/dev/null)
add_match "use-sealed-freezed" \
  "Use sealed class with @freezed, never abstract class." \
  "$MATCHES"

# ---------- Rule 11: ScaffoldMessenger.of or SnackBarUtils.show in widget files ----------
case "$FILE_PATH" in
  */presentation/*|*/screens/*|*/widgets/*|*/views/*|*/pages/*)
    case "$FILE_PATH" in
      *_notifier.dart|*_service.dart|*_repository.dart|*_datasource.dart) ;;
      *)
        MATCHES=$(grep -nE "(ScaffoldMessenger\.of[[:space:]]*\(|SnackBarUtils\.show)" "$FILE_PATH" 2>/dev/null)
        add_match "no-snackbar-from-widget" \
          "Notifier or service owns snackbar dispatch. Widget calls notifier method." \
          "$MATCHES"
        ;;
    esac
    ;;
esac

# ---------- Rule 11: AppLocalizations.of(context)! ----------
MATCHES=$(grep -nE "AppLocalizations\.of\([^)]*\)!" "$FILE_PATH" 2>/dev/null)
add_match "no-applocalizations-bang" \
  "Configure gen-l10n with nullable-getter: false, then drop the !. Or use context.l10n extension." \
  "$MATCHES"

# ---------- Rule 12: MediaQuery.withClampedTextScaling at MaterialApp root ----------
if grep -qE 'MaterialApp' "$FILE_PATH" 2>/dev/null; then
  MATCHES=$(grep -nE 'MediaQuery\.withClampedTextScaling' "$FILE_PATH" 2>/dev/null)
  add_match "no-app-root-text-scale-clamp" \
    "Fix the local layout overflow. Do not clamp text scaling at the app root." \
    "$MATCHES"
fi

# ---------- Rule 13: Storage SDK outside Local Datasource ----------
# Fires EVERYWHERE except infrastructure files. Exempt list covers:
# - datasource files (by name or by path containing data/datasources, data/local, data/storage)
# - infrastructure / config: core/hive, core/storage, core/persistence, infrastructure/
# - main / main_*.dart (app boot — Hive.initFlutter etc.)
# - test files
# - explicit init / registration / adapter boilerplate
# - mixins that wrap datasource access (e.g. *_local_datasource_mixin.dart)
case "$FILE_PATH" in
  *_datasource.dart|*_datasource_impl.dart|*_datasource_mixin.dart|*local_datasource*.dart|*remote_datasource*.dart) ;;
  */data/datasources/*|*/data/local/*|*/data/storage/*|*/datasources/*) ;;
  */core/hive/*|*/core/storage/*|*/core/persistence/*|*/core/cache/*|*/infrastructure/*) ;;
  */main.dart|*/main_*.dart|main.dart|main_*.dart) ;;
  *_test.dart|*/test/*|*/test_*/*|*/integration_test/*) ;;
  *_setup.dart|*storage_init.dart|*hive_setup.dart|*_registrar.dart|*hive_adapters.dart|*hive_boxes.dart) ;;
  *)
    # Storage SDK package imports — file-storage-specific (NOT Platform / HttpStatus / HttpException
    # which live in dart:io but are legitimately used in services).
    MATCHES=$(grep -nE "^import[[:space:]]+['\"]package:(hive|hive_ce|hive_ce_flutter|shared_preferences|flutter_secure_storage|path_provider|sqflite|sembast|isar|drift)['\"/]" "$FILE_PATH" 2>/dev/null)
    add_match "no-storage-sdk-outside-datasource" \
      "Storage SDK import (hive / hive_ce / shared_preferences / flutter_secure_storage / path_provider / sqflite / sembast / isar / drift) outside Local<X>Datasource. Move to data/datasources/. Notifier and widget depend on the repository provider." \
      "$MATCHES"

    # File-ops calls (NOT Platform, HttpStatus, HttpException — those are legitimate dart:io APIs in services).
    MATCHES=$(grep -nE "(\bFile\([\"']|\bDirectory\([\"']|\bLink\([\"']|\bRandomAccessFile\b|\bFileSystemEntity\b|new[[:space:]]+File[[:space:]]*\()" "$FILE_PATH" 2>/dev/null)
    add_match "no-dart-io-file-ops-outside-datasource" \
      "Direct File / Directory / Link / FileSystemEntity ops outside Local<X>Datasource. Move to data/datasources/." \
      "$MATCHES"

    # Storage helper calls.
    MATCHES=$(grep -nE "(Hive\.openBox|Hive\.box[[:space:]]*\(|SharedPreferences\.getInstance|FlutterSecureStorage\(|getApplicationDocumentsDirectory|getApplicationSupportDirectory|getTemporaryDirectory|getExternalStorageDirectory)" "$FILE_PATH" 2>/dev/null)
    add_match "no-storage-call-outside-datasource" \
      "Direct storage call outside Local<X>Datasource. Move to data/datasources/; expose via repository." \
      "$MATCHES"
    ;;
esac

# ---------- Rule 14: Prop-drilling — widget constructor takes non-leaf type ----------
# Fires when a widget constructor parameter is typed as anything OTHER THAN the leaf allowlist.
# Allowlist covers Flutter SDK primitives, callbacks, keys, durations, intl types, and widget children.
case "$FILE_PATH" in
  *_test.dart|*/test/*) ;;
  *_datasource.dart|*_repository.dart|*_service.dart) ;;
  *)
    MATCHES=$(awk '
      BEGIN {
        # Allowlist of leaf types. Bracketed by commas so we match ",Type," exactly.
        allow = ",Key,GlobalKey,LocalKey,ValueKey,UniqueKey,ObjectKey,PageStorageKey,GlobalObjectKey,"
        allow = allow "String,int,double,bool,num,DateTime,Duration,Uri,RegExp,Object,Pattern,Symbol,BigInt,Comparable,"
        allow = allow "Color,IconData,EdgeInsets,EdgeInsetsGeometry,BorderRadius,BorderRadiusGeometry,BoxConstraints,BoxDecoration,Border,BorderSide,"
        allow = allow "Offset,Size,Rect,Radius,Alignment,AlignmentGeometry,Matrix4,Quaternion,Vector3,Vector4,"
        allow = allow "TextStyle,TextDirection,TextAlign,TextOverflow,TextScaler,TextSelection,TextSpan,TextWidthBasis,TextHeightBehavior,"
        allow = allow "FontWeight,FontStyle,FontFeature,Brightness,Clip,Axis,VerticalDirection,MainAxisAlignment,MainAxisSize,CrossAxisAlignment,"
        allow = allow "BuildContext,Locale,ThemeMode,ImageProvider,"
        allow = allow "Widget,WidgetBuilder,IndexedWidgetBuilder,SliverChildDelegate,PreferredSizeWidget,InlineSpan,GestureDetector,InheritedWidget,RenderBox,RenderObject,"
        allow = allow "VoidCallback,Function,AsyncCallback,ValueGetter,ValueSetter,Completer,"
        allow = allow "Future,Stream,Iterable,List,Map,Set,Iterator,FutureOr,Record,"
        allow = allow "ValueChanged,ValueNotifier,ChangeNotifier,Listenable,Animation,CurvedAnimation,Tween,Curve,"
        allow = allow "ScrollController,TextEditingController,FocusNode,PageController,TabController,AnimationController,OverlayPortalController,SearchController,"
        allow = allow "EventChannel,MethodChannel,BinaryMessenger,"
        allow = allow "Type,Enum,"
      }

      /class[[:space:]]+[A-Za-z0-9_]+[[:space:]]+extends[[:space:]]+(StatelessWidget|StatefulWidget|ConsumerWidget|ConsumerStatefulWidget|HookWidget|HookConsumerWidget)/ { in_widget = 1; next }
      /^}/ { in_widget = 0 }
      !in_widget { next }

      {
        line = $0
        norm = $0
        # Strip leading whitespace
        sub(/^[[:space:]]+/, "", norm)
        # Strip modifiers (any order)
        sub(/^final[[:space:]]+/, "", norm)
        sub(/^required[[:space:]]+/, "", norm)
        sub(/^final[[:space:]]+/, "", norm)
        sub(/^const[[:space:]]+/, "", norm)
        sub(/^static[[:space:]]+/, "", norm)

        # Skip if not "Type name" pattern
        if (norm !~ /^[A-Z][A-Za-z0-9_]*(<[^>]*>)?\??[[:space:]]+[a-z_]/) next

        # Skip method signatures (parens followed by { or =>)
        if (norm ~ /\([^)]*\)[[:space:]]*(\{|=>)/) next

        # Skip lines without a terminator (field/param/end-of-constructor)
        if (norm !~ /(;|,|\}\))[[:space:]]*(\/\/.*)?$/) next

        # Extract the type expression: everything from start up to the space before the variable name
        type_expr = norm
        sub(/[[:space:]]+[a-z_][A-Za-z0-9_]*.*$/, "", type_expr)
        # Strip trailing ? if nullable
        sub(/\?$/, "", type_expr)
        if (type_expr == "") next

        # Find ALL capitalized identifiers in the type expression and check each.
        # If any is NOT in allowlist, flag.
        remaining = type_expr
        bad_ident = ""
        while (match(remaining, /[A-Z][A-Za-z0-9_]*/)) {
          ident = substr(remaining, RSTART, RLENGTH)
          if (index(allow, "," ident ",") == 0) {
            bad_ident = ident
            break
          }
          remaining = substr(remaining, RSTART + RLENGTH)
        }
        if (bad_ident != "") {
          print NR ":" $0 "  (non-leaf type: " bad_ident ")"
        }
      }
    ' "$FILE_PATH" 2>/dev/null)
    add_match "no-prop-drilling" \
      "Widget constructor / field takes a non-leaf type. Children watch providers directly via ref.watch. Constructor params allowed: Key variants, primitives (String/int/double/bool/num/DateTime/Duration), callbacks (VoidCallback/ValueChanged/Function/AsyncCallback), Flutter style types (Color/EdgeInsets/TextStyle/BorderRadius/etc.), controllers (ScrollController/TextEditingController/etc.), child widgets (Widget/WidgetBuilder), Locale, BuildContext." \
      "$MATCHES"
    ;;
esac

# ---------- Emit result ----------
if [[ ${#VIOLATIONS[@]} -eq 0 ]]; then
  exit 0
fi

REASON="building-flutter-apps gate blocked the write. Fix these before retrying:"
for v in "${VIOLATIONS[@]}"; do
  REASON+=$'\n'"$v"
done

emit_block "$REASON"

exit 0
