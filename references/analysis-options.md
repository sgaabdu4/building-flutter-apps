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
