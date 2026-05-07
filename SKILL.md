---
name: building-flutter-apps
description: Flutter arch ref — Riverpod 3.x, Freezed 3.x, GoRouter, Hive CE, Crashlytics, ShowcaseView. Covers state management, navigation, routing, local storage, persistence, data models, serialization, dependency injection, clean architecture, feature scaffolding, forms, validation, lists, pagination, search, debouncing, error handling, crash reporting, analytics, logging, fire-and-forget, services, singletons, guided tours, onboarding, testing, code generation. Use for any Flutter/Dart file, new screen/feature, state/data flow, model/entity, repository/datasource, provider/notifier, widget tree/UI, bug/crash, or touches `lib/`, `test/`, `pubspec.yaml`, `analysis_options.yaml`, `*.dart`. NOT for Provider/BLoC/GetX, non-Flutter, or backend-only Dart.
license: MIT
metadata:
  author: sgaabdu4
  version: "4.3.4"
  tags: flutter, riverpod, freezed, state-management, clean-architecture, dart, hive, showcaseview, crashlytics, fire-and-forget, singletons, e2e testing
---

## MANDATORY — Read Before Writing Any Code

**Read this section + linked refs before code.**

1. **MUST copy [analysis_options.yaml](references/analysis_options.yaml) verbatim into every Flutter project root. Guide: [analysis_options.md](references/analysis-options.md).**
2. **MUST run analyzer with the copied config. `flutter_skill_lints` + `riverpod_lint` are the primary machine gate. Analyzer ERROR = stop. Server crash / `server.pluginError` → see [analysis-options.md](references/analysis-options.md) Troubleshooting (purge analyzer plugins from `pubspec.yaml`).**
3. **MUST read [architecture.md](references/architecture.md) BEFORE creating any feature module, entity, model, datasource, or repository.**
4. **MUST read [freezed-sealed.md](references/freezed-sealed.md) BEFORE creating any Freezed class.**
5. **MUST read [state-management.md](references/state-management.md) BEFORE creating any notifier.**
6. **MUST read [performance.md](references/performance.md) BEFORE writing any widget tree or provider.**
7. **NEVER** use `dynamic`, `_buildXxx()` helpers, hardcoded strings, `shrinkWrap: true`, value!, or `abstract class` with Freezed.
8. **ALWAYS** check `if (!ref.mounted) return;` after every `await` in notifiers.
9. **NEVER** read `state` (incl. `state.copyWith`) in sync `Notifier` before `build()` returns. Seed via returned constructor, defer async init via `Future.microtask`. See [state-management.md](references/state-management.md#sync-notifier-initialization-trap).
10. **ALWAYS** init repositories inside mutation methods (`create*`, `update*`, `delete*`, `set*`, `reorder*`) via `_ensureRepository()`/`_ensureDependencies()` helper. NEVER rely only on `build()`/`_init()` timing for write paths.
11. **When touching guided tours, MUST read [showcase-tours.md](references/showcase-tours.md) first. NEVER filter `startShowCase()` keys with `key.currentContext` checks.**
12. **When touching streams, realtime, push events, subscriptions, sync, shared state, collaboration, remote callbacks, or any source-of-truth refresh path, MUST read [testing.md](references/testing.md#event-contract-and-sync-tests) + [dart-mcp-e2e-testing.md](references/dart-mcp-e2e-testing.md). Map event families before code.**
13. **Remote/shared-state E2E MUST prove writer + observer behavior on real app instances, including create, update, delete/remove, relaunch, source-of-truth verification, and cleanup.**
14. **When adding E2E-testable UI, MUST use a central widget key registry file, default `lib/core/testing/app_widget_keys.dart` or existing project equivalent. No inline string `ValueKey`s.**
15. **Widgets/screens MUST NOT dispatch snackbars. Notifiers/services own success/error messaging. See [extensions-utilities.md](references/extensions-utilities.md#snackbar-utility).**

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

1. **Codegen only** — `@riverpod` / `@Riverpod(keepAlive: true)` for every provider: state, computed, repository, datasource, service, family, and stream. NEVER write manual `Provider`, `FutureProvider`, `StreamProvider`, `StateProvider`, `StateNotifierProvider`, `NotifierProvider`, `AsyncNotifierProvider`, or `ChangeNotifierProvider`.
2. **Sealed classes** — `sealed class` with Freezed. NEVER `abstract class`.
3. **No prop drilling** — child widgets watch providers direct.
4. **Guard async** — `if (!ref.mounted) return;` after EVERY `await` in notifiers. `if (!context.mounted) return;` in widgets. In `State` methods without a local context, capture `final context = this.context;` before `await`, then guard `context.mounted`.
5. **Single Ref** — Riverpod 3.0 unified Ref types. NEVER `AutoDisposeRef`, `FutureProviderRef`.
6. **Select in leaves** — `ref.watch(provider.select((s) => s.field))` in leaf widgets.
7. **One primary class per file** — exception: Freezed state + notifier may share file.
8. **Interface contracts** — `abstract interface class` for every repo + datasource. Constructors take interfaces, NEVER concrete types.
9. **No `dynamic`** — use `Object?` or proper type. Exception: `Map<String, dynamic>` in JSON.
10. **Widget classes only** — NEVER `_buildXxx()` helpers. Extract to named widget classes.
11. **No hardcoded strings** — `*Strings` constants classes with `static const`.
12. **ref.watch in build, ref.read in callbacks.**
13. **Provider naming** — codegen strips "Notifier": `FooNotifier` → `fooProvider`.
14. **No `shrinkWrap: true`** — use `Sliver` variants or constrained containers.
15. **Mixins for capabilities, interfaces for contracts** — see [mixins.md](references/mixins.md).
16. **No null-bang** — NEVER value!. Use `if (value case final v?)`.
17. **`abstract final class` for static-only namespaces** — NEVER `Class._()`. Exception: `const Entity._()` in Freezed.
18. **`ref.invalidate` not `ref.refresh`** when no return value needed.
19. **Persistence SSOT** — Default to repository/data persistence. Notifier persistence opt-in. One persistence owner per feature state.
20. **Pop safely with GoRouter** — For dismiss/back on pushable or deep-linkable screens, guard `context.pop()` with `context.canPop()`. If true, pop + return. Else navigate to typed fallback (`const MyRoute().go(context)`).
21. **No silent mutation no-op** — Mutation methods must not return early just because cached repo field null; lazily init deps first, then proceed or fail explicit.
22. **Route-param safety in widgets** — NEVER throw from widget `build()` for missing route IDs. Use nullable by-id providers + fallback UI. See [common-patterns.md](references/common-patterns.md#route-param-safety--wizard-sequencing).
23. **Navigation-critical mutation sequencing** — In wizard/deep-link flows: persist write → targeted state sync → navigate. See [common-patterns.md](references/common-patterns.md#route-param-safety--wizard-sequencing) and [state-management.md](references/state-management.md).
24. **Showcase replay safety** — Pass full ordered key list to `startShowCase()`. Do not gate by `key.currentContext != null` / mounted checks; readiness is handled by scope registration + scheduling.
25. **Event contract proof** — For streams/realtime/sync/push/shared remote state, map source-of-truth event families to exact subscriptions/listeners before code. Do not assume parent-resource events cover child resources. Add datasource/service contract tests plus notifier/UI reaction tests.
26. **Source-of-truth after mutation** — If a backend/service can return stale, partial, generated, or derived values, mutation flow must refresh from the source of truth before claiming UI is synced.
27. **Remote observer proof** — Shared/collaboration/team/chat/invite flows need at least two actors or two app instances: writer performs the mutation, observer sees the change without manual refresh, then destructive/removal paths are verified.
28. **E2E is behavior proof** — Runtime E2E is not static analysis, screenshot-only review, or a single happy path. It must drive the real app, inspect logs, verify source-of-truth state when remote data is involved, and rerun failed/downstream flow segments after fixes.
29. **E2E key registry** — E2E selectors live in one app-owned key registry file. Widgets use `ValueKey(AppWidgetKeys.someAction)`. Tests use the same constants. Do not scatter string keys through widgets/tests.
30. **Snackbar boundary** — Widgets/screens dispatch notifier actions only. No `SnackBarUtils.show*` or `ScaffoldMessenger.of(...)` in UI files.
31. **E2E entrypoint** — Runtime E2E needs a deterministic app entrypoint (`lib/main_dev.dart` or project equivalent) with Flutter Driver enabled and provider/env overrides for known app states.
32. **Pure router policy** — Keep GoRouter redirect decisions in a pure resolver function and matrix-test it. Router closures wire inputs only.
33. **No global text-scale clamp** — Never clamp text scaling at app root. Fix local overflow/layout instead.
34. **Shared test harness SSOT** — Keep provider containers, fakes, mocks, wait helpers, and platform stubs in shared test helpers.
35. **Cross-runtime contract tests** — If Flutter shares schema/IDs/constants with backend/functions/native code, add drift tests so copies cannot silently diverge.
36. **Async sync cancellation** — Long auth/sync/import/export flows need generation/cancellation guards so stale async work cannot write state after sign-out/account switch.

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

**Family + keepAlive caveat.** Family + `@Riverpod(keepAlive: true)` keeps every key forever. Cache can grow unbounded. Prefer `@riverpod`.

**Nested computed hop warning.** Avoid computed -> computed chain in pause-sensitive paths (`aProvider` watches `bProvider(param)`). Riverpod 3.2.x offstage nav can throw TickerMode pause/resume assertion.

If chain required, flatten in parent provider:
- watch base state directly
- derive via pure helpers
- avoid provider -> provider indirection on hot navigation paths

**Exception:** Riverpod 3.2.x has TickerMode assertion bug ([rrousselGit/riverpod#4709](https://github.com/rrousselGit/riverpod/issues/4709)). If hit, `keepAlive: true` workaround allowed. Add inline note: `// keepAlive: Riverpod 3.2.x #4709 workaround`. Remove after upstream fix.

## Anti-Patterns

| Wrong | Right |
|-------|-------|
| `StateProvider` | `@riverpod` codegen |
| Manual `Provider(...)`, `FutureProvider(...)`, `StreamProvider(...)`, `NotifierProvider(...)`, `AsyncNotifierProvider(...)` | Annotated provider/function/class with generated `.g.dart` |
| `abstract class` with Freezed | `sealed class` |
| Pass state through constructors | Child watches provider directly |
| Missing `ref.mounted` after `await` | `if (!ref.mounted) return;` |
| Auto-dispose with all-keepAlive deps | `@Riverpod(keepAlive: true)` |
| Try-catch at every layer | Catch once in notifier |
| `context.go('/path')` string | `const MyRoute().go(context)` typed |
| Entity in datasource | `Model` with `toEntity()` in repo |
| Assume domain `id` equals backend row/document id in datasource update/delete | Keep ids separate. Resolve transport id first, then update/delete |
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
| Mutation method (`create*`, `update*`, `delete*`, `set*`) does `if (_repository == null) return ...` | Use `_ensureRepository()`/`_ensureDependencies()` with `await`, then guard with `if (!ref.mounted) return ...` |
| `context.pop()` without guard on dismiss/back callbacks | `if (context.canPop()) { context.pop(); return; } const MyRoute().go(context);` |
| `context.pop()` then immediately push route (modal still animating) | `Navigator.of(context).maybePop().then((_) { if (ctx.mounted) nav(); })` — see [common-patterns.md](references/common-patterns.md#dismiss-modal--push-route-bottom-sheet-navigation) |
| `firstWhere(... orElse: () => throw StateError(...))` in widget `build()` for route IDs | Nullable by-id provider + fallback UI (no throw). See [common-patterns.md](references/common-patterns.md#route-param-safety--wizard-sequencing) |
| `ref.invalidate(parentProvider)` right after child create/delete in active wizard/deep-link flow | Persist write → targeted parent sync → navigate. See [state-management.md](references/state-management.md) |
| `using context` after `await` | `if (!context.mounted) return;` |
| `if (!mounted) return;` in `State` async code | `final context = this.context;` before `await`, then `if (!context.mounted) return;` |
| Mixin vs interface vs extension choices | See [mixins.md](references/mixins.md) |
| Subscribe to "some realtime events" and hope sync works | Map exact event families/channels/topics, test each event family, then run writer/observer E2E |
| Mutation writes remote data then trusts cached/local response | Fetch source-of-truth after mutation when values can be generated/stale/derived |
| Inline `ValueKey('save-button')` | `ValueKey(AppWidgetKeys.saveButton)` from central key registry |
| Widget calls `SnackBarUtils.showError(...)` | Widget calls notifier method; notifier emits snackbar |
| GoRouter redirect logic only inside closure | Pure `resolveAppRedirect(...)` function + matrix tests |
| App root clamps text scaling | Responsive local layout fixes; no global clamp |
| One-off test fakes in each test file | Shared `test/helpers/test_fakes.dart` style harness |
| Shared backend/app constants copied without test | Contract drift test covering both runtimes |

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
| [analysis_options.yaml](references/analysis_options.yaml) + [analysis-options.md](references/analysis-options.md) | **Every Flutter project** — linter config |
| [flutter-optimizations.md](references/flutter-optimizations.md) | Scrolling, animation, concurrency |
| [atomic-design.md](references/atomic-design.md) | Shared widgets in `core/widgets/` |
| [testing.md](references/testing.md) | Unit/widget tests, event/subscription contract tests, sync reaction tests |
| [dart-mcp-e2e-testing.md](references/dart-mcp-e2e-testing.md) | Dart MCP runtime E2E, multi-actor sync proof, source-of-truth checks, logs, cleanup |
| [common-patterns.md](references/common-patterns.md) | Lists, search, forms, GoRouter, sync |
| [extensions-utilities.md](references/extensions-utilities.md) | Utilities, extensions |
| [mixins.md](references/mixins.md) | Mixin vs interface vs extension, `retryWithBackoff` + `SaveAllRowsException` for bulk I/O |
| [hive-persistence.md](references/hive-persistence.md) | Local storage, Hive adapters |
| [services-and-singletons.md](references/services-and-singletons.md) | Static-only class vs singleton vs provider, fire-and-forget pattern, testing each |
| [crashlytics.md](references/crashlytics.md) | Firebase Crashlytics setup (3 hooks), `Crash` wrapper, non-fatal vs fatal, breadcrumbs, custom keys, symbols |
| [showcase-tours.md](references/showcase-tours.md) | Guided tours, tour state sync, `ProviderSubscription` handle, test-env safe service read |
| [dart-patterns-records.md](references/dart-patterns-records.md) | Records, patterns, extension types |

## Pre-Flight — Before Returning Any Code

- [ ] `analysis_options.yaml` copied from [analysis_options.yaml](references/analysis_options.yaml) in Flutter project root
- [ ] Analyzer ran with `flutter_skill_lints` + `riverpod_lint`; no analyzer errors
- [ ] `if (!ref.mounted) return;` after EVERY `await` in notifiers
- [ ] `if (!context.mounted) return;` after EVERY `await` in widgets
- [ ] `State` async methods using context after await use `final context = this.context;` before await; no `if (!mounted) return`
- [ ] No `_buildXxx()` helpers — extracted to widget classes
- [ ] No hardcoded strings — `*Strings` constants classes
- [ ] No `dynamic` — `Object?` or proper types
- [ ] No value! — `if (value case final v?)`
- [ ] `ref.watch()` in `build()`, `ref.read()` only in callbacks
- [ ] Sync `Notifier.build()` never reads `state` before first `state=` — loading flags seeded via returned constructor; async init dispatched with `Future.microtask`; no `fireImmediately: true` listener that reads state without prior direct `state =` assignment
- [ ] Every notifier mutation method lazily inits repositories/deps (`_ensureRepository`/`_ensureDependencies`) before writes
- [ ] Route-param lookups in widget `build()` are nullable (no throw-on-missing-id)
- [ ] Wizard/deep-link mutation sequence: persist → targeted sync → navigate
- [ ] Every provider is generated with `@riverpod` / `@Riverpod(...)`; no manual `Provider`, `FutureProvider`, `StreamProvider`, `StateProvider`, `NotifierProvider`, `AsyncNotifierProvider`, `StateNotifierProvider`, or `ChangeNotifierProvider`
- [ ] Widgets/screens do not call `SnackBarUtils.show*` or `ScaffoldMessenger`; notifier/service owns snackbar side effects
- [ ] If streams/realtime/push/sync/shared state changed: exact event families/channels/topics/listeners mapped; datasource/service contract tests prove subscriptions; notifier/widget tests prove state reaction
- [ ] If remote mutation returns generated/stale/partial/derived values: UI refreshes from source of truth before navigation or success state
- [ ] If shared/collaboration/team/chat/invite/sync changed: real E2E covered writer + observer create/update/delete/remove/relaunch path, source-of-truth state was checked, and test data was cleaned
- [ ] E2E/widget selectors use a central key registry (`lib/core/testing/app_widget_keys.dart` or existing equivalent); no inline string `ValueKey`s in widgets/tests
- [ ] E2E target entrypoint exists and is deterministic (`lib/main_dev.dart` or equivalent), with Flutter Driver enabled when MCP/driver E2E needs it
- [ ] Router redirect rules are pure-function tested when navigation/auth/onboarding/update/sync gates changed
- [ ] App root does not clamp text scaling
- [ ] Shared test helper SSOT used for containers/fakes/mocks/wait helpers
- [ ] Cross-runtime constants/schema/function contracts have drift tests when copied across app/backend/native boundaries
- [ ] Long-running sync/auth/import/export flows guard stale async writes after cancellation/sign-out/account switch
- [ ] If showcase code changed: `startShowCase()` uses full `ShowcaseKeys.*Tour` list (no `key.currentContext` filtering), and replay/reset path follows [showcase-tours.md](references/showcase-tours.md)
