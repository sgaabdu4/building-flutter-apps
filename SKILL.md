---
name: building-flutter-apps
description: Flutter clean architecture with Riverpod 3.x codegen, Freezed 3.x sealed classes, GoRouter, Hive CE persistence, and ShowcaseView guided tours. Use when building, reviewing, refactoring, or generating any Flutter code — including widgets, providers, repositories, models, datasources, tests, features, screens, forms, lists, navigation, or project setup. Covers feature module scaffolding, AsyncNotifier patterns, provider select optimization, Freezed unions and JSON serialization, GoRouter redirects, Hive repositories, pagination, forms, anti-patterns, and testing. Does NOT apply to Provider/BLoC/GetX, non-Flutter frameworks, backend-only Dart, or Firebase-only questions.
license: MIT
metadata:
  author: sgaabdu4
  version: "4.2.0"
  tags: flutter, riverpod, freezed, state-management, clean-architecture, dart, hive, persistence, local-storage, showcaseview, guided-tours, onboarding
---

## MANDATORY — Read Before Writing Any Code

**Read this section and linked references before producing code.**

1. **MUST copy [analysis-options.md](references/analysis-options.md) `analysis_options.yaml` verbatim into every project root.**
2. **MUST read [architecture.md](references/architecture.md) BEFORE creating any feature module, entity, model, datasource, or repository.**
3. **MUST read [freezed-sealed.md](references/freezed-sealed.md) BEFORE creating any Freezed class.**
4. **MUST read [state-management.md](references/state-management.md) BEFORE creating any notifier.**
5. **MUST read [performance.md](references/performance.md) BEFORE writing any widget tree or provider.**
6. **NEVER** use `dynamic`, `_buildXxx()` helpers, hardcoded strings, `shrinkWrap: true`, value!, or `abstract class` with Freezed.
7. **ALWAYS** check `if (!ref.mounted) return;` after every `await` in notifiers.
8. **NEVER** read `state` (including `state.copyWith`) in a sync `Notifier` before `build()` returns. Seed via returned constructor and defer async init with `Future.microtask`. See [state-management.md](references/state-management.md#sync-notifier-initialization-trap).

## Core Stack

| Package | Purpose |
|---------|----------|
| flutter_riverpod + riverpod_annotation + riverpod_generator | State management (codegen) |
| freezed + freezed_annotation | Immutable data classes, unions |
| go_router + go_router_builder | Declarative, type-safe routing |
| json_serializable + build_runner | JSON serialization + code generation |
| showcaseview | First-run guided tours |
| hive_ce + hive_ce_flutter | Local persistence |

## Architecture

```mermaid
graph LR
  P[Presentation] --> R[Repository]
  R --> Do[Domain]
  R --> Da[Data]
  Da -.-> Do
```

```
lib/
├── core/           # Shared: theme, utils, widgets, navigation, services
├── features/
│   └── feature_x/
│       ├── data/           # Models, datasources (API/local)
│       ├── domain/         # Entities (pure Dart, no dependencies)
│       ├── repositories/   # Map models → entities
│       └── presentation/   # Notifiers, screens, widgets
└── main.dart
```

## Critical Rules

1. **Codegen only** — `@riverpod` / `@Riverpod(keepAlive: true)`. NEVER legacy `StateProvider`, `StateNotifierProvider`.
2. **Sealed classes** — `sealed class` with Freezed. NEVER `abstract class`.
3. **No prop drilling** — child widgets watch providers directly.
4. **Guard async** — `if (!ref.mounted) return;` after EVERY `await` in notifiers. `if (!context.mounted) return;` in widgets.
5. **Single Ref** — Riverpod 3.0 unified all Ref types. NEVER `AutoDisposeRef`, `FutureProviderRef`.
6. **Select in leaves** — `ref.watch(provider.select((s) => s.field))` in leaf widgets.
7. **One primary class per file** — exception: Freezed state + notifier may share a file.
8. **Interface contracts** — `abstract interface class` for every repo and datasource. Constructors accept interfaces, NEVER concrete types.
9. **No `dynamic`** — use `Object?` or proper type. Exception: `Map<String, dynamic>` in JSON.
10. **Widget classes only** — NEVER `_buildXxx()` helpers. Extract to named widget classes.
11. **No hardcoded strings** — `*Strings` constants classes with `static const`.
12. **ref.watch in build, ref.read in callbacks.**
13. **Provider naming** — codegen strips "Notifier": `FooNotifier` → `fooProvider`.
14. **No `shrinkWrap: true`** — use `Sliver` variants or constrained containers.
15. **Mixins for capabilities, interfaces for contracts** — see [mixins.md](references/mixins.md).
16. **No null-bang** — NEVER value!. Use `if (value case final v?)`.
17. **`abstract final class` for static-only namespaces** — NEVER `Class._()`. Exception: `const Entity._()` in Freezed.
18. **`ref.invalidate` not `ref.refresh`** when no return value is needed.
19. **Persistence SSOT** — Default to repository/data persistence. Notifier persistence is opt-in. One persistence owner per feature state.

## Provider Decision Tree

```mermaid
graph TD
  Q1{Repository, datasource, or service?} -->|Yes| A1["@Riverpod(keepAlive: true)"]
  Q1 -->|No| Q2{Feature notifier with mutable state?}
  Q2 -->|Yes| A2["@Riverpod(keepAlive: true) class XNotifier"]
  Q2 -->|No| Q3{Computed value or one-time fetch?}
  Q3 -->|Yes| Q5{All deps keepAlive?}
  Q5 -->|Yes| A5["@Riverpod(keepAlive: true)"]
  Q5 -->|No| A3["@riverpod — auto-disposes"]
  Q3 -->|No| Q4{Needs parameters?}
  Q4 -->|Yes| A4["Add params to function — family via codegen"]
```

## Anti-Patterns

| Wrong | Right |
|-------|-------|
| `StateProvider` | `@riverpod` codegen |
| `abstract class` with Freezed | `sealed class` |
| Pass state through constructors | Child watches provider directly |
| Missing `ref.mounted` after `await` | `if (!ref.mounted) return;` |
| Auto-dispose with all-keepAlive deps | `@Riverpod(keepAlive: true)` |
| Try-catch at every layer | Catch once in notifier |
| `context.go('/path')` string | `const MyRoute().go(context)` typed |
| Entity in datasource | `Model` with `toEntity()` in repo |
| `@JsonSerializable(explicitToJson: true)` per class | `explicit_to_json: true` in `build.yaml` |
| `@Freezed(toJson: true)` when `fromJson` exists | Plain `@freezed` |
| Concrete type in constructor | `abstract interface class` |
| value! null-bang | `if (value case final v?)` |
| `class Foo { Foo._(); }` | `abstract final class Foo` |
| `ref.refresh(provider)` discarding return | `ref.invalidate(provider)` |
| `@Riverpod(keepAlive: true)` on family provider | `@riverpod` (auto-dispose) |
| Side-effect loading/error in notifier state | `Mutation<T>()` — see [riverpod-codegen.md](references/riverpod-codegen.md) |
| `ref.read` in `initState` | `addPostFrameCallback` then read |
| `state.copyWith(...)` before first `state=` in sync `Notifier.build()` (incl. `_load()` called sync from build, or `ref.listen(..., fireImmediately: true)` callback that reads state) | Seed via returned constructor + `Future.microtask(_load)`, OR `state = const FooState()` before `fireImmediately` listener. See [state-management.md](references/state-management.md#sync-notifier-initialization-trap) |
| `using context` after `await` | `if (!context.mounted) return;` |
| Mixin vs interface vs extension choices | See [mixins.md](references/mixins.md) |

Full patterns: [common-patterns.md](references/common-patterns.md) | [extensions-utilities.md](references/extensions-utilities.md)

## Class Modifiers

| Modifier | Extend outside lib | Implement outside lib | Instantiate | Mixin |
|---|:---:|:---:|:---:|:---:|
| `abstract class` | ✓ | ✓ | ✗ | ✗ |
| `abstract interface class` | ✗ | ✓ | ✗ | ✗ |
| `abstract final class` | ✗ | ✗ | ✗ | ✗ |
| `sealed class` | ✗ | ✗ | ✗ | ✗ |
| `base class` | ✓ | ✗ | ✓ | ✗ |
| `interface class` | ✗ | ✓ | ✓ | ✗ |
| `final class` | ✗ | ✗ | ✓ | ✗ |
| `mixin class` | ✓ | ✓ | ✓ | ✓ |

## Code Generation

```bash
dart run build_runner watch -d   # Watch mode (recommended)
dart run build_runner build -d   # One-time build
dart run build_runner clean && dart run build_runner build -d  # Clean build
```

## References

Read before generating code for that topic.

| File | When |
|------|------|
| [performance.md](references/performance.md) | **Always** — any widget or provider |
| [architecture.md](references/architecture.md) | Feature modules, layers, interfaces |
| [riverpod-codegen.md](references/riverpod-codegen.md) | Providers, mutations, lifecycle |
| [freezed-sealed.md](references/freezed-sealed.md) | Entities, models, unions, serialization |
| [state-management.md](references/state-management.md) | Notifiers, error handling, cross-provider |
| [analysis-options.md](references/analysis-options.md) | **Every project** — linter config |
| [flutter-optimizations.md](references/flutter-optimizations.md) | Scrolling, animation, concurrency |
| [atomic-design.md](references/atomic-design.md) | Shared widgets in `core/widgets/` |
| [testing.md](references/testing.md) | Unit/widget tests |
| [common-patterns.md](references/common-patterns.md) | Lists, search, forms, GoRouter, sync |
| [extensions-utilities.md](references/extensions-utilities.md) | Utilities, extensions |
| [mixins.md](references/mixins.md) | Mixin vs interface vs extension |
| [hive-persistence.md](references/hive-persistence.md) | Local storage, Hive adapters |
| [showcase-tours.md](references/showcase-tours.md) | Guided tours, tour state sync |
| [dart-patterns-records.md](references/dart-patterns-records.md) | Records, patterns, extension types |

## Pre-Flight — Before Returning Any Code

- [ ] `analysis_options.yaml` from [analysis-options.md](references/analysis-options.md) in project root
- [ ] `if (!ref.mounted) return;` after EVERY `await` in notifiers
- [ ] `if (!context.mounted) return;` after EVERY `await` in widgets
- [ ] No `_buildXxx()` helpers — extracted to widget classes
- [ ] No hardcoded strings — `*Strings` constants classes
- [ ] No `dynamic` — `Object?` or proper types
- [ ] No value! — `if (value case final v?)`
- [ ] `ref.watch()` in `build()`, `ref.read()` only in callbacks
- [ ] Sync `Notifier.build()` never reads `state` before first `state=` — loading flags seeded via returned constructor; async init dispatched with `Future.microtask`; no `fireImmediately: true` listener that reads state without a prior direct `state =` assignment
