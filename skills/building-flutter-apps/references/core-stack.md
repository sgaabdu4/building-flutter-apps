# Core Stack

## Read first

1. Package constraints = this file only.
2. Constraint change → real project `dart pub get` → `dart pub deps -s compact` → `dart analyze`.
3. Code generation = current flag-free command; clean only after a failed normal build.

| Package | Constraint | Purpose |
|---|---:|---|
| `flutter_riverpod` | `3.3.2` | State management |
| `riverpod_annotation` | `4.0.3` | Codegen annotations |
| `riverpod_generator` | `4.0.4` | Provider codegen |
| `freezed_annotation` | `^3.1.0` | Sealed-union annotations |
| `freezed` | `3.2.6-dev.1` | Immutable classes; exact analyzer-12 compatibility pin; Dart SDK >= 3.8 |
| `json_annotation` | `^4.12.0` | JSON annotations |
| `json_serializable` | `6.14.1` | JSON codegen; exact analyzer-12-compatible pin |
| `go_router` | `^17.5.0` | Declarative routing |
| `go_router_builder` | `4.4.0` | Typed route codegen; exact analyzer-12-compatible pin |
| `hive_ce` | `^2.19.3` | Binary local persistence |
| `hive_ce_flutter` | `^2.3.4` | Flutter integration |
| `hive_ce_generator` | `1.11.2` | Hive adapters; exact pin |
| `build_runner` | `2.15.1` | Code generation; exact analyzer-compatible pin |

## Verified compatibility matrix

Checked on 2026-08-15 with Flutter `3.47.0` stable and Dart `3.13.0`:

| Surface | Package | Verified version or resolution |
|---|---|---:|
| Application | `analyzer` | `12.1.0` resolved by the fixture |
| Application | `riverpod` | `3.3.2` |
| Application | `flutter_riverpod` | `3.3.2` |
| Application | `riverpod_annotation` | `4.0.3` |
| Application | `riverpod_generator` | `4.0.4` |
| Application | `freezed` | `3.2.6-dev.1` |
| Application | `freezed_annotation` | `3.1.0` |
| Application | `hive_ce` | `2.19.3` resolved by the fixture |
| Application | `hive_ce_generator` | `1.11.2` |
| Application | `json_serializable` | `6.14.1` |
| Application | `go_router_builder` | `4.4.0` |
| Application | `build_runner` | `2.15.1` |
| Shared plugin | `riverpod_lint` | `3.1.8` |
| Lint package | `analyzer` | `13.3.0` |
| Lint package | `analyzer_plugin` | `0.14.12` |
| Lint package | `analysis_server_plugin` | `0.3.18` |
| Lint package | `analyzer_testing` | `0.3.2` |
| Lint package | `test` | `1.31.2` |
| Lint package | `lints` | `6.1.0` |

The application generator, shared analysis-server plugin, and standalone lint
package are separate compatibility families. The fixture proves the
application family with generated Riverpod, Freezed, Hive, JSON, and GoRouter
code. The real analysis-server smoke test proves the lint package alongside
`riverpod_lint 3.1.8` on analyzer 13.3.0.

- The fixture resolves analyzer `12.x` without an override. The coupled exact pins are `riverpod_generator` + `freezed` + `json_serializable` + `go_router_builder` + `hive_ce_generator` + `build_runner`.
- Stable `freezed 3.2.5` requires analyzer `<11.0.0`; `freezed 3.2.6-dev.1` requires analyzer `>=12.0.0 <13.0.0`. Keep the exact prerelease pin until a stable release supports this family.
- `hive_ce_generator 1.11.2` requires analyzer `^12.0.0`; `1.11.3` requires analyzer `^14.0.0`.
- `build_runner 2.15.1` supports analyzer `<14.0.0`; `2.15.2` starts at analyzer `13.3.0`. Keep `2.15.1` exact with the analyzer-12 family.
- `go_router_builder 4.4.0` requires analyzer `<14.0.0`. `json_serializable 6.14.1` supports analyzer `<15.0.0`, so it remains usable with analyzer 12.
- `analyzer 14.1.0` is the newer standalone analyzer release, but it does not solve with `riverpod_lint 3.1.8`, whose current package metadata requires analyzer `^13.0.0`. The lint package therefore uses the newest shared analyzer-13 family proven by its real plugin smoke test.
- The latest package metadata checked on the same date also listed
  `analyzer_plugin 0.14.14`, `analysis_server_plugin 0.3.20`, and
  `analyzer_testing 0.3.4`; these follow analyzer `14.1.0`, so they were
  rejected for the shared lint family. The selected versions are the newest
  family that solves with `riverpod_lint` and passes the plugin smoke test.
- Exact-pin lift gate = full Riverpod + Freezed + Hive solver proof + analyzer proof.

## Verified package sources

- [Dart package dependencies](https://dart.dev/tools/pub/dependencies)
- [Dart pub workspaces](https://dart.dev/tools/pub/workspaces)
- [analyzer](https://pub.dev/packages/analyzer)
- [analyzer_plugin](https://pub.dev/packages/analyzer_plugin)
- [analysis_server_plugin](https://pub.dev/packages/analysis_server_plugin)
- [analyzer_testing](https://pub.dev/packages/analyzer_testing)
- [riverpod_lint](https://pub.dev/packages/riverpod_lint)
- [riverpod_generator](https://pub.dev/packages/riverpod_generator)
- [freezed](https://pub.dev/packages/freezed)
- [hive_ce_generator](https://pub.dev/packages/hive_ce_generator)
- [go_router_builder](https://pub.dev/packages/go_router_builder)
- [build_runner](https://pub.dev/packages/build_runner)
- [json_serializable](https://pub.dev/packages/json_serializable)
- [test](https://pub.dev/packages/test)
- [lints](https://pub.dev/packages/lints)

Re-run the compatibility fixture after any package, Flutter, or Dart upgrade.

## Code generation

```bash
dart run build_runner build
```

- Use the flag-free command above. Current `build_runner` versions handle conflicting outputs through their normal build contract.
- Run `dart run build_runner clean` only as a separate recovery step after a failed normal build, then run the flag-free build again.
- `-d`, `--delete-conflicting-output`, and `--delete-conflicting-outputs` are forbidden in active guidance, scripts, fixtures, and examples.
- Version change → installed command help + [official changelog](https://pub.dev/packages/build_runner/changelog).
