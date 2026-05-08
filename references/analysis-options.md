# analysis_options.yaml

Copy `references/analysis_options.yaml` to every Flutter project root.

## Required

- `strict-casts`, `strict-inference`, `strict-raw-types`: true
- Async: `unawaited_futures`, `discarded_futures`, `avoid_void_async`
- Resources: `avoid_print`, `cancel_subscriptions`, `close_sinks`
- Codegen: `invalid_annotation_target: ignore`
- Exclude: `*.g.dart`, `*.freezed.dart`, `*.gr.dart`, `*.arb`

## Install

```bash
flutter pub add dev:flutter_lints
```

Plugin block:

```yaml
plugins:
  flutter_skill_lints:
  # Pre-release pin: lift when riverpod_lint 3.2.0 stable lands.
  riverpod_lint: 3.1.4-dev.3
```

Match bundled [`references/analysis_options.yaml`](analysis_options.yaml)
exactly. Both pin `flutter_skill_lints` version OR neither — keep aligned.

## Rules

- Plugins go top-level `plugins:`. Not under `analyzer:`. Not in `pubspec.yaml`.
- Use `flutter_skill_lints` + `riverpod_lint` as shown.
- No `git:`/`path:` under `plugins:` unless local checkout.

## Verify

1. `flutter pub get`
2. `dart analyze --verbose` (package root, no path arg)
3. Fail on `server.pluginError`
4. One `flutter_skill_lints` diagnostic
5. One `riverpod_lint` diagnostic

## Use `dart analyze`, NOT `flutter analyze`

Run `dart analyze` from package root. No path arg. Avoid `flutter analyze` + `flutter analyze lib` + `dart analyze lib`.

Why: `flutter analyze lib` exits before plugin diagnostics report → plugin lints silently dropped. Repro Flutter 3.41.9 / Dart 3.11.5: `flutter analyze` → 12 plugin diagnostics; `flutter analyze lib` → `No issues found`. Tracking: https://github.com/flutter/flutter/issues/184190.

CI/scripts: `dart analyze`. Never `flutter analyze lib`.

## Troubleshoot — analysis server crash

Symptom: `server.pluginError`, `analysis server crashed`, `plugin failed to load`, `IsolateSpawnException`, hang, IDE Dart pane dies.

Cause: plugin packages (`riverpod_lint`, `custom_lint`, `flutter_skill_lints`, ...) listed in `pubspec.yaml` `dependencies:`/`dev_dependencies:` AND top-level `plugins:` block. Two paths conflict → crash.

Fix:
1. Open `pubspec.yaml`.
2. Remove from `dependencies:`/`dev_dependencies:`: `riverpod_lint`, `custom_lint`, `custom_lint_builder`, `flutter_skill_lints`, `flutter_lints` (when top-level plugins used), any other analyzer plugin.
3. Keep ONLY in `analysis_options.yaml` `plugins:`.
4. `flutter pub get` → restart analysis server (IDE: "Restart Analysis Server"; CLI: re-run `dart analyze`).

Rule: plugins live in `analysis_options.yaml plugins:`. Never both places.

## Troubleshoot — stale `~/.dartServer` cache crash

Symptom: `Bad state: The analysis server crashed unexpectedly` on every `dart analyze` invocation, even single-file. Plugin loads fine; `flutter analyze lib/main.dart` works.

Repro:

```bash
dart analyze --format=machine lib/main.dart
# Bad state: The analysis server crashed unexpectedly

dart analyze --cache=$HOME/.dartServer --format=machine lib/main.dart
# Bad state: The analysis server crashed unexpectedly

dart analyze --cache=/tmp/dart_analysis_cache_fresh --format=machine lib/main.dart
# works — normal diagnostics
```

Cause: stale/corrupt analyzer cache + plugin-manager state under `~/.dartServer`. Triggered by recent plugin/dependency churn (add/remove `custom_lint`, `riverpod_lint`, version bumps).

Fix:

```bash
mv ~/.dartServer ~/.dartServer.bak-$(date +%Y%m%d%H%M%S)
dart analyze
```

Caveat: never use relative `--cache=` (e.g. `--cache=.dart_tool/cache`). Dart 3.11 resolves it relative to the SDK analysis-server snapshot dir → `invalid plugin.aot`. Absolute paths only.

After fresh cache: remaining diagnostics are real plugin lints, not crashes.
