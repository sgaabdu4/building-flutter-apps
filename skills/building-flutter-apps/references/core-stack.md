# Core Stack

## Read first

1. Package constraints = this file only.
2. Constraint change → real project `dart pub get` → `dart pub deps -s compact` → `dart analyze`.
3. Code generation = long conflict-resolution flag; clean only after a failed normal build.

| Package | Constraint | Purpose |
|---|---:|---|
| `flutter_riverpod` | `^3.3.2` | State management |
| `riverpod_annotation` | `^4.0.3` | Codegen annotations |
| `riverpod_generator` | `^4.0.4` | Provider codegen |
| `freezed_annotation` | `^3.1.0` | Sealed-union annotations |
| `freezed` | `3.2.6-dev.1` | Immutable classes; exact analyzer-12 compatibility pin; Dart SDK >= 3.8 |
| `json_annotation` | `^4.12.0` | JSON annotations |
| `json_serializable` | `6.14.0` | JSON codegen; exact pin |
| `go_router` | `^17.3.0` | Declarative routing |
| `go_router_builder` | `^4.3.1` | Typed route codegen |
| `hive_ce` | `^2.19.3` | Binary local persistence |
| `hive_ce_flutter` | `^2.3.4` | Flutter integration |
| `hive_ce_generator` | `1.11.2` | Hive adapters; exact pin |
| `build_runner` | `2.15.1` | Code generation; exact analyzer-compatible pin |

- Coupled exact pins = `freezed` + `json_serializable` + `hive_ce_generator` + `build_runner`.
- Stable `freezed 3.2.5` requires analyzer <11; `hive_ce_generator 1.11.2` requires analyzer 12.x. Pin `freezed 3.2.6-dev.1` explicitly until a compatible stable release exists.
- `build_runner 2.15.2` requires analyzer >=13.3; `hive_ce_generator 1.11.2` requires analyzer 12.x. Keep `build_runner` exact until the generator widens its analyzer range.
- Exact-pin lift gate = full Riverpod + Freezed + Hive solver proof + analyzer proof.

## Code generation

```bash
dart run build_runner watch --delete-conflicting-outputs
dart run build_runner build --delete-conflicting-outputs
dart run build_runner clean && dart run build_runner build --delete-conflicting-outputs
```
