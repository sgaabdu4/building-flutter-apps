# Setup

## Read first

1. Use this only for Flutter or Riverpod package setup, lint wiring, or broken analyzer plugin detection.
2. `flutter_skill_lints` and `riverpod_lint` belong only under top-level `analysis_options.yaml` `plugins:`.
3. Project setup = package-root `dart analyze` proves both lint plugins can fire + [Dart Decimate](dart-decimate.md) full scan passes.

## Trigger

Signals: new Flutter app, `analysis_options.yaml`, `pubspec.yaml`, `dart analyze`, missing lint diagnostics.

## Lint wiring

Copy [analysis_options.yaml](analysis_options.yaml) to the project root. It wires `flutter_skill_lints: ^0.10.0` and `riverpod_lint: ^3.1.9` under top-level `plugins:` and keeps strict casts, inference, and raw types enabled.

Pure-Dart CLI packages use their native Dart analysis profile; do not add either Flutter/Riverpod plugin.

Do not add either analyzer plugin to `pubspec.yaml`.

Run:

```bash
dart pub get
dart analyze
python3 "$HOME/.agents/skills/deterministic-checks/scripts/dart_decimate_gate.py" --package . --timeout 600
```

## Extension template

Copy [templates/flutter/lib/core/extensions/](../templates/flutter/lib/core/extensions/) into `lib/core/extensions/` for every new Flutter app. If the project already has extension files, merge the template instead of overwriting.

## Analyzer sanity checks

Temporarily introduce each violation, run package-root `dart analyze`, then restore the file:

```dart
// WRONG: sanity-check violation, then restore the file.
Widget _buildHeader() => const SizedBox();
```

Expected lint: `widget_top_level_function_boundary`.

```dart
// WRONG: sanity-check violation, then restore the file.
ModalRoute.isCurrentOf(context);
```

Expected lint outside `lib/core/extensions/context_extensions.dart`: `use_context_is_current_modal_route`.

## Git pre-push

Read [dart-decimate.md](dart-decimate.md#git-pre-push) → delegate to canonical `deterministic-checks` without replacing an existing hook owner or changing `core.hooksPath`.
