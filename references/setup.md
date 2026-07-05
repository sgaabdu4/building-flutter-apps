# Setup

## Read first

1. Use this only for new app setup, lint wiring, plugin install routing, or broken analyzer plugin detection.
2. `flutter_skill_lints` is an analyzer plugin and belongs only under top-level `analysis_options.yaml` `plugins:`.
3. Project setup is not complete until package-root `dart analyze` proves both `flutter_skill_lints` and `riverpod_lint` can fire.

## Trigger

Signals: new Flutter app, `analysis_options.yaml`, `pubspec.yaml`, `dart analyze`, plugin install, missing lint diagnostics.
Before code: output `Reading: setup.md`.

## Lint wiring

Copy [analysis_options.yaml](analysis_options.yaml) to the project root. It wires `flutter_skill_lints` and `riverpod_lint` under top-level `plugins:` and keeps strict casts, inference, and raw types enabled.

Do not add `flutter_skill_lints` to `pubspec.yaml`.

Run:

```bash
dart pub get
dart analyze
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

## Per-tool hooks

| Tool | Auto-install command | Hook source |
|---|---|---|
| Claude Code | `/plugin marketplace add sgaabdu4/building-flutter-apps` then `/plugin install building-flutter-apps@building-flutter-apps`; run `/reload-plugins` in the active session | `hooks/hooks.json` |
| Codex CLI | `codex features enable hooks`, `codex features enable plugin_hooks`, `codex plugin marketplace add sgaabdu4/building-flutter-apps`, then `codex` -> `/plugins` -> install | `hooks/hooks.json` |
| Copilot CLI | `copilot plugin marketplace add sgaabdu4/building-flutter-apps` then `copilot plugin install building-flutter-apps@building-flutter-apps` | `hooks/hooks.copilot.json` |

Raw skill installs are guidance-only. They load `SKILL.md` but cannot register runtime hooks or run scanners. Use plugin installs when enforcement matters.
