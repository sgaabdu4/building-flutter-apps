# Core Stack

- Exact package-constraint SSOT = this file.
- Constraint change → real project `dart pub get` → `dart pub deps -s compact` → `dart analyze`.

| Package | Constraint | Purpose |
|---|---:|---|
| `flutter_riverpod` | `^3.3.2` | State management |
| `riverpod_annotation` | `^4.0.3` | Codegen annotations |
| `riverpod_generator` | `^4.0.4` | Provider codegen |
| `freezed_annotation` | `^3.1.0` | Sealed-union annotations |
| `freezed` | `^3.2.5` | Immutable classes; Dart SDK >= 3.8 |
| `json_annotation` | `^4.12.0` | JSON annotations |
| `json_serializable` | `6.14.0` | JSON codegen; exact pin |
| `go_router` | `^17.3.0` | Declarative routing |
| `go_router_builder` | `^4.3.0` | Typed route codegen |
| `hive_ce` | `^2.19.3` | Binary local persistence |
| `hive_ce_flutter` | `^2.3.4` | Flutter integration |
| `hive_ce_generator` | `1.11.2` | Hive adapters; exact pin |
| `build_runner` | `^2.15.0` | Code generation |

- Coupled exact pins = `json_serializable` + `hive_ce_generator`.
- Exact-pin lift gate = full Riverpod + Freezed + Hive solver proof + analyzer proof.
