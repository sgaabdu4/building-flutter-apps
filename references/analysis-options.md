# analysis_options.yaml

Copy `references/analysis_options.yaml` into every Flutter project root.

## Required Settings

- `strict-casts`, `strict-inference`, `strict-raw-types`: true
- Async: `unawaited_futures`, `discarded_futures`, `avoid_void_async`
- Resources/logging: `avoid_print`, `cancel_subscriptions`, `close_sinks`
- Codegen: `invalid_annotation_target: ignore`
- Exclude: `*.g.dart`, `*.freezed.dart`, `*.gr.dart`, `*.arb`

## Install

```bash
flutter pub add dev:flutter_lints
```

Canonical plugin block:

```yaml
plugins:
  flutter_skill_lints:
    version: ^0.2.0
  riverpod_lint: 3.1.4-dev.3
```

## Rules

- Keep analyzer plugins in top-level `plugins:`, not under `analyzer:` and not in `pubspec.yaml`.
- Use `flutter_skill_lints` and `riverpod_lint` exactly as shown.
- Do not write `git:` or `path:` under `plugins:` unless testing a local plugin checkout.

## Verify

1. **Pubspec generator path:** `flutter pub get`
2. **Top-level plugins path:** `flutter analyze --verbose`
3. Fail on `server.pluginError`
4. Require one `flutter_skill_lints` diagnostic
5. Require one `riverpod_lint` diagnostic

## Troubleshooting — Dart analysis server crash

Symptom: `flutter analyze` errors like `server.pluginError`, `analysis server crashed`, `plugin failed to load`, `IsolateSpawnException`, or analyzer hangs / IDE Dart Analysis pane dies.

Root cause: analyzer plugin packages (`riverpod_lint`, `custom_lint`, `flutter_skill_lints`, etc.) are listed in `pubspec.yaml` under `dependencies:` / `dev_dependencies:` AT THE SAME TIME as the top-level `plugins:` block in `analysis_options.yaml`. Two registration paths conflict → server crash.

Fix:
1. Open `pubspec.yaml`.
2. Remove from `dependencies:` and `dev_dependencies:` any of: `riverpod_lint`, `custom_lint`, `custom_lint_builder`, `flutter_skill_lints`, `flutter_lints` (when using top-level plugins), and any other analyzer plugin.
3. Keep them ONLY in `analysis_options.yaml` `plugins:` block.
4. `flutter pub get` → restart analysis server (IDE: "Restart Analysis Server"; CLI: re-run `flutter analyze`).

Rule: analyzer plugins live in `analysis_options.yaml plugins:`. Never both places.
