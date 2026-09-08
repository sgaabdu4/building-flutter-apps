# Core Stack

## Read first

1. Package constraints = this file only.
2. Constraint change → `flutter pub get` → `dart run build_runner build` → `dart analyze` → `flutter test`.
3. Run a normal, flag-free code-generation command first. Clean only after that command fails.

## Verified application family

The compatibility fixture requires Dart `>=3.13.0 <4.0.0` and Flutter
`>=3.47.0`. It solves this application and generator family together:

| Package | Constraint | Purpose |
|---|---:|---|
| `flutter_riverpod` | `3.4.3` | State management |
| `riverpod_annotation` | `4.0.7` | Provider annotations |
| `riverpod_generator` | `4.0.9` | Provider generation |
| `freezed_annotation` | `3.1.0` | Immutable models |
| `freezed` | `4.0.1` | Immutable-model generation |
| `json_annotation` | `^4.12.0` | JSON annotations |
| `json_serializable` | `6.14.1` | JSON generation |
| `go_router` | `^18.0.1` | Routing |
| `go_router_builder` | `4.5.0` | Typed-route generation |
| `hive_ce` | `^2.19.3` | Local persistence |
| `hive_ce_flutter` | `^2.3.4` | Flutter persistence integration |
| `hive_ce_generator` | `1.11.3` | Hive adapter generation |
| `build_runner` | `2.16.1` | Build orchestration |
| `analyzer` | `14.3.0` | Analyzer |
| `flutter_lints` | `6.0.0` | Base Flutter lints |

## Analyzer plugins

Flutter/Riverpod packages use both plugins in the root
`analysis_options.yaml`. They are analyzer-plugin configuration, not
`pubspec.yaml` dependencies.

```yaml
plugins:
  riverpod_lint: ^3.1.9
  flutter_skill_lints: ^0.10.0
```

`flutter_skill_lints ^0.10.0` is built against analyzer `^14.3.0`,
`analyzer_plugin ^0.14.16`, and `analysis_server_plugin ^0.3.22`.
`riverpod_lint ^3.1.9` shares the analyzer-plugin configuration above.

Pure-Dart CLI packages keep their native Dart analysis profile and do not add
these Flutter/Riverpod plugins.

## Compatibility proof

`tool/run_compatibility_fixture.py` resolves the application family, generates
Riverpod, Freezed, Hive, JSON, and typed-route code, confirms analyzer
`14.3.0`, then runs the analyzer with both plugins. Its deliberate probe
requires a `flutter_skill_lints` `avoid_null_bang` diagnostic and a
`riverpod_lint` `missing_provider_scope` diagnostic while rejecting
`server.pluginError`. It removes the probe before the Flutter test and web
build.

The fixture uses the top-level hosted plugin configuration without a local path
or dependency override. Its analyzer probe proves that both plugins load and
report their expected diagnostics without `server.pluginError`.

Re-run the fixture after any package, Flutter, Dart, analyzer, or plugin
configuration upgrade. Do not use dependency overrides as compatibility proof.

## Package sources

- [Dart package dependencies](https://dart.dev/tools/pub/dependencies)
- [Dart analyzer plugins](https://dart.dev/tools/analyzer-plugins)
- [analyzer](https://pub.dev/packages/analyzer)
- [analyzer_plugin](https://pub.dev/packages/analyzer_plugin)
- [analysis_server_plugin](https://pub.dev/packages/analysis_server_plugin)
- [riverpod_lint](https://pub.dev/packages/riverpod_lint)
- [riverpod_generator](https://pub.dev/packages/riverpod_generator)
- [freezed](https://pub.dev/packages/freezed)
- [hive_ce_generator](https://pub.dev/packages/hive_ce_generator)
- [go_router_builder](https://pub.dev/packages/go_router_builder)
- [build_runner](https://pub.dev/packages/build_runner)
- [json_serializable](https://pub.dev/packages/json_serializable)

## Code generation

```bash
dart run build_runner build
```

- Use the flag-free command above.
- Run `dart run build_runner clean` only as a separate recovery step after a
  failed normal build, then run the flag-free build again.
- `-d`, `--delete-conflicting-output`, and `--delete-conflicting-outputs` are
  forbidden in active guidance, scripts, fixtures, and examples.
- Version change → installed command help + [official changelog](https://pub.dev/packages/build_runner/changelog).
