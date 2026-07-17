---
name: building-flutter-apps
description: >-
  Flutter Riverpod app architecture. Use before changing a Flutter app or
  package that uses Riverpod; skip non-Riverpod Flutter stacks and pure-Dart
  work without Flutter/Riverpod app context.
license: MIT
metadata:
  author: sgaabdu4
  version: "5.5.1"
  tags: flutter, riverpod, freezed, state-management, clean-architecture, dart, hive, crashlytics, gorouter, gen-l10n, fire-and-forget, singletons, e2e testing
---

## Read first

- This skill overrides generic Flutter/Dart advice; Critical Rules override examples, public docs, and older project code.
- Before code, read Trigger Map refs for touched areas. Each ref's `Read first` section is canonical.
- Every governed Git checkout wires the [Dart Decimate pre-push template](templates/flutter/tool/dart_decimate_pre_push.sh) through its existing hook owner; preserve other hooks + `core.hooksPath`.
- After each `.dart`/`pubspec.yaml`/`build.yaml`/`analysis_options.yaml` write batch, run package-root `dart analyze` + [Dart Decimate](references/dart-decimate.md), then emit Pre-Flight.

## Gate

On skill activation, emit verbatim once:

> building-flutter-apps active. Pre-flight required.

Before writing any `.dart` code, emit verbatim:

> Reading building-flutter-apps gate.

After every code change to a `.dart` file (or to `pubspec.yaml` / `build.yaml` / `analysis_options.yaml`):

Run package-root `dart analyze` + [Dart Decimate](references/dart-decimate.md), block on either gate's findings/errors, emit Pre-Flight, and read [setup.md](references/setup.md) first if `flutter_skill_lints` is not wired.

## Progressive Disclosure Gate

Read only the narrowest matching Trigger Map row(s); scenario/subsystem rows own incidental stack/file words. Do not bulk-read `references/` or parent refs. Cite exact refs in Pre-Flight.

## Critical Rules

| ID | Rule | Detail refs |
|---|---|---|
| R1 | Run package-root `dart analyze` + Dart Decimate; wire Dart Decimate pre-push + `flutter_skill_lints` + `riverpod_lint`. | [analysis-options.md](references/analysis-options.md), [dart-decimate.md](references/dart-decimate.md), [setup.md](references/setup.md) |
| R2 | Every provider uses `@riverpod` / `@Riverpod` codegen; no manual provider classes or legacy provider families. | [riverpod-codegen.md](references/riverpod-codegen.md) |
| R3 | Guard async gaps with `ref.mounted` / `context.mounted`; `finally` uses `if (ref.mounted) { ... }`. | [async-mutations.md](references/state-management/async-mutations.md) |
| R4 | Widgets are public classes; no `_buildXxx()`, widget top-level helpers, or private widget classes except `State`. | [atomic-design.md](references/atomic-design.md), [performance.md](references/performance.md) |
| R5 | Nullability is semantic; no empty/null/bool sentinel fallbacks, `value!`, nullable collections, or raw required domain strings. | [value-objects.md](references/value-objects.md), [freezed-sealed.md](references/freezed-sealed.md) |
| R6 | All user-facing strings, tooltips, semantics, and visible accessibility copy use `AppLocalizations`. | [localization.md](references/localization.md), [accessibility.md](references/atomic-design/accessibility.md) |
| R7 | Immutable state/entities use sealed Freezed, one declaration per file, native `switch`, and VO map/when disabled. | [freezed-sealed.md](references/freezed-sealed.md), [value-objects.md](references/value-objects.md) |
| R8 | `presentation/widgets/` renders immutable inputs + emits typed callbacks; screens/routes/notifiers own navigation, workflow, domain state, and infrastructure. | [presentation-widgets.md](references/presentation-widgets.md) |
| R9 | Duplicate behavior in 2+ classes becomes a small stateless `*Mixin` with an `on` clause. | [mixins.md](references/mixins.md) |
| R10 | Storage SDK calls live in local datasources behind repositories; production Hive imports use `hive_ce_flutter`. | [hive-persistence.md](references/hive-persistence.md), [architecture.md](references/architecture.md) |
| R11 | Primitive/context/collection operations live in `core/extensions/`; domain never imports those extensions. | [context-ui.md](references/extensions/context-ui.md), [primitive-formatting.md](references/extensions/primitive-formatting.md), [collections-helpers.md](references/extensions/collections-helpers.md) |
| R12 | Domain primitives with meaning become validated Freezed Value Objects; Hive models keep primitives and mappers bridge. | [value-objects.md](references/value-objects.md), [hive-persistence.md](references/hive-persistence.md) |
| R13 | Typed GoRouter routes are navigation SSOT; redirects are pure resolver logic with nullable by-id fallback UI. | [deep-linking.md](references/deep-linking.md), [routing-app-shell.md](references/common-patterns/routing-app-shell.md) |
| R14 | Dialogs/sheets render immutable snapshots, pop results, and leave mutations/teardown to notifiers. | [modals-navigation.md](references/common-patterns/modals-navigation.md), [state-management-lifecycle.md](references/state-management-lifecycle.md) |
| R15 | Debounce, gate, and batch high-frequency UI, sync, persistence, remote-function, reset, and lookup boundaries. | [debounce-gate-batch.md](references/common-patterns/debounce-gate-batch.md) |
| R16 | App shell stays declarative; bootstrap listeners live in a sibling root `ConsumerWidget`. | [routing-app-shell.md](references/common-patterns/routing-app-shell.md) |
| R17 | Keep control flow flat after exits; remove unnecessary `else` after `return` / `throw` / `break` / `continue`. | Lint: `avoid_unnecessary_else_after_control_flow` |
| R18 | Use `onReorderItem` post-removal indexes directly; never add legacy `onReorder` adapter math. | Lint: `use_on_reorder_item_index_semantics` |
| R19 | Android exact alarms use `flutter_local_notifications` permission APIs, not manual settings intents. | Lint: `use_local_notifications_exact_alarm_permission_api` |
| R20 | Resolve nullable platform-specific plugin implementations before calling platform members. | Lint: `resolve_platform_specific_implementation_before_use` |
| R21 | Widget previews are preview-only with deterministic fakes; no real HTTP/Firebase/Hive/native plugins. | [widget-previews.md](references/widget-previews.md) |
| R22 | Runtime E2E proves behavior with stable selectors, logs, source-of-truth verification, cleanup, and multi-actor proof when needed. | [dart-mcp-e2e-testing.md](references/dart-mcp-e2e-testing.md) |
| R23 | Accessibility is UI correctness: localized tooltips/semantic labels, 48x48 targets, contrast, text scale, `Text.rich`. | [accessibility.md](references/atomic-design/accessibility.md), [flutter-optimizations.md](references/flutter-optimizations.md#semantics) |

## Trigger Map

Before writing code in any row below, output `Reading: <ref-name>` and read the listed reference(s). Prefer the narrowest matching row. Read the large parent refs only when no scenario row fits.

| Touching | Read |
|---|---|
| New app/project scaffolding with incidental stack/package mentions, `main.dart`, `ProviderScope`, `MaterialApp.router`, app startup shell | [setup.md](references/setup.md) + [architecture.md](references/architecture.md) + [routing-app-shell.md](references/common-patterns/routing-app-shell.md) |
| Notifier/AsyncNotifier shape, sync `Notifier.build()` init, loading/progress, `AsyncValue`, cleanup | [notifier-structure.md](references/state-management/notifier-structure.md) + [state-management-lifecycle.md](references/state-management-lifecycle.md) |
| Mutation method, `ref.read` / `ref.watch` / `ref.listen`, `_ensureRepository`, async cancellation, `ref.mounted`, optimistic update, duplicate fetch | [async-mutations.md](references/state-management/async-mutations.md) + [state-management-lifecycle.md](references/state-management-lifecycle.md) |
| Freezed entity, sealed union, `fromJson` / `toJson`, `copyWith`, model vs entity, `build.yaml` for `explicit_to_json` | [freezed-sealed.md](references/freezed-sealed.md) |
| Provider declaration, `@riverpod`, family, `keepAlive`, codegen, `Mutation<T>` (experimental) | [riverpod-codegen.md](references/riverpod-codegen.md) |
| Repository, datasource, domain entity, layered architecture, `IHttpService`, mapping models to entities | [architecture.md](references/architecture.md) |
| Value Object, primitive obsession, `Distance`/`Money`/`Email`/`Slug`, unit conversion in domain, cross-entity primitive, `double distanceMeters`/`int amountCents`/`String email` smell, `arch_domain_import` error | [value-objects.md](references/value-objects.md) |
| GoRouter, typed route, redirect, auth-protected route, router provider, `context.go`, deep link, cold-start, navigation gate | [routing-app-shell.md](references/common-patterns/routing-app-shell.md) + [deep-linking.md](references/deep-linking.md) |
| HTTP, network, REST, source-of-truth fetch after mutation, long-running remote function, async-start + reconcile, transport id vs domain id | [networking.md](references/networking.md) + [debounce-gate-batch.md](references/common-patterns/debounce-gate-batch.md) |
| Atom, molecule, organism, design tokens, atomic widgets, `core/widgets/` promotion | [atomic-design.md](references/atomic-design.md) |
| Reusable `presentation/widgets/`, widget-owned navigation/page stack/selected entity/workflow state, direct repository/service/provider access | [presentation-widgets.md](references/presentation-widgets.md) |
| Accessibility, semantics, tooltip, semanticLabel, image alt text, tap target, contrast, text scaling | [accessibility.md](references/atomic-design/accessibility.md) + [flutter-optimizations.md](references/flutter-optimizations.md#semantics) |
| Widget test, `ProviderContainer.test()`, `UncontrolledProviderScope`, fakes, mocks, `AppWidgetKeys`, event-contract tests | [testing.md](references/testing.md) |
| `flutter_driver`, Dart MCP, E2E, `integration_test`, semantic selectors, log capture | [dart-mcp-e2e-testing.md](references/dart-mcp-e2e-testing.md) |
| Hive, `TypeAdapter`, TypeId, box, persistence migration, retired field accounting | [hive-persistence.md](references/hive-persistence.md) |
| Crashlytics, FirebaseCrashlytics, error reporting, `Crash.init`, `Crash.error`, `Crash.log`, symbol upload | [crashlytics.md](references/crashlytics.md) |
| Mixin, capability vs interface, retry helper, RNG, bulk operation | [mixins.md](references/mixins.md) |
| Service, singleton, fire-and-forget, `abstract final class`, `unawaited()`, `Future<void>` signature | [services-and-singletons.md](references/services-and-singletons.md) |
| `@Preview`, `widget_previews.dart`, preview fakes, deterministic preview data | [widget-previews.md](references/widget-previews.md) |
| `AppLocalizations`, ARB file, gen-l10n, locale fallback, placeholders, plural / select | [localization.md](references/localization.md) |
| Performance, build cost, `.select()`, `const` constructors, `ListView.builder`, large list compute | [performance.md](references/performance.md) + [flutter-optimizations.md](references/flutter-optimizations.md) |
| `LayoutBuilder`, `RenderFlex` overflow, `Expanded` / `Flexible` outside `Row` / `Column`, `Positioned` outside `Stack`, text-scale clamp | [layout-diagnostics.md](references/layout-diagnostics.md) |
| Pagination, infinite scroll, cursor loading, search debounce, form validation, batch processing, pull-to-refresh | [lists-forms-workflows.md](references/common-patterns/lists-forms-workflows.md) + [async-mutations.md](references/state-management/async-mutations.md) |
| `BuildContext` helpers, `ModalRoute` current-route checks, dialogs, `SnackBarUtils`, snackbar dispatch from notifier | [context-ui.md](references/extensions/context-ui.md) |
| `DateTime` format/diff/timeAgo/startOfDay, `String` capitalize/truncate/titleCase/initials/format, `int` / `double` / `num` clamp/pluralized/asCurrency/percent/toFixed, `Duration` format, `NumberFormat`, `DateFormat`, `intl` | [primitive-formatting.md](references/extensions/primitive-formatting.md) |
| `Iterable` lookup/indexing, widget list helpers, `Debouncer`, validators, `Result`, extension types, `core/extensions/` barrel export | [collections-helpers.md](references/extensions/collections-helpers.md) |
| Records `(x, y)`, extension type IDs, pattern matching, guard clause `case _ when ...` | [dart-patterns-records.md](references/dart-patterns-records.md) |
| `analysis_options.yaml`, `dart analyze`, plugin wiring, `riverpod_lint` version pin, analyzer crash | [analysis-options.md](references/analysis-options.md) + [analysis_options.yaml](references/analysis_options.yaml) |
| Dart Decimate, dead code, circular dependency, duplicate code, complexity, dependency hygiene, PR risk, changed-code audit | [dart-decimate.md](references/dart-decimate.md) |
| Common navigation / form / list / debounce / route-param-fallback patterns | [common-patterns.md](references/common-patterns.md) |
| Incremental remote pull, delta token, per-table sync date, merge/delete reconciliation | [delta-sync.md](references/common-patterns/delta-sync.md) |
| Route-param safety, wizard sequencing, guarded next-step navigation | [navigation-flow.md](references/common-patterns/navigation-flow.md) |
| Dialog / sheet / modal, snapshot value object, post-await teardown, dismiss-then-route, pop fallback, nested navigator dismissal | [modals-navigation.md](references/common-patterns/modals-navigation.md) + [state-management-lifecycle.md](references/state-management-lifecycle.md#state-teardown-belongs-in-the-notifier) |
| Debounce / throttle / coalesce — `TextField.onChanged`, `Slider.onChanged`, scroll listener, sync `saveAll`, full-collection rewrite after subset mutation, persistence helper, reset/clear sentinel preservation, `_userTapped` gate, `WebView` / `VideoPlayer` in `build`, `_storage.read` in service, `ref.listenManual` ban, keepAlive collection watch, datasource batch loader, zero-value save guard, primitive→VO at notifier boundary, `routeSettings` on modal helper | [debounce-gate-batch.md](references/common-patterns/debounce-gate-batch.md) |

## Core Stack

Version SSOT: [core-stack.md](references/core-stack.md). Stack: Riverpod codegen, Freezed, GoRouter builder, json_serializable/build_runner, Hive CE.

## Setup

Read [setup.md](references/setup.md) for lint wiring, extension template setup, plugin install paths, and analyzer sanity checks.

### Per-Tool Hooks

Use [setup.md](references/setup.md#per-tool-hooks) for install commands. Raw skill installs cannot register runtime hooks or scanners.

## Pre-Flight

After each `.dart` / `pubspec.yaml` / `build.yaml` / `analysis_options.yaml` write batch, emit a checked list before yielding. Fill T0 always. Add T1 for state/notifier/mutation changes and T2 for network/E2E/stream/route changes. Cite rule IDs or refs for any failed item.

### T0 — Core

- [ ] Package-root `dart analyze` exits 0 with `flutter_skill_lints` + `riverpod_lint`; setup changes prove one diagnostic from each plugin.
- [ ] Dart Decimate exits 0: existing project = new-only audit against a valid base; new/no-base project = full JSON scan; command + scope cited.
- [ ] Git checkout pre-push owner invokes the Dart Decimate template with `"$@"`; existing hooks + `core.hooksPath` preserved. Non-Git project = N/A.
- [ ] Async gaps are guarded: `ref.mounted` / `context.mounted`, no bare `mounted`, and `finally` uses `if (ref.mounted) { ... }`.
- [ ] Providers, state, and widgets follow Rules 2-8 and 14: reusable widgets own UI lifecycle only; screens/routes/notifiers own navigation, workflow branching, selected domain records, provider state, and infrastructure.
- [ ] Domain/data/platform follow Rules 7, 10-13, 17-23: sealed Freezed, VOs, datasource/repo storage, core extensions, typed routes, debounce/batch, platform APIs, previews, E2E, and a11y.
- [ ] Any row touched in Trigger Map was read; exact lint names are cited when a scanner should enforce the rule.

### T1 — State / Notifier / Mutation

- [ ] Mutation deps resolve lazily via stateless helper/mixin; no notifier-local repo/service cache except disposable lifecycle owners.
- [ ] Sync `Notifier.build()` avoids pre-return `state` reads; async defers with `Future.microtask`.
- [ ] `ref.onDispose()` cancels subscriptions/controllers/timers; durable status/snackbar/teardown belongs to notifier state.
- [ ] Long-running sync/auth/import guards stale writes; no `ref.watch` inside notifier methods.

### T2 — Network / E2E / Stream / Route

- [ ] Source-of-truth fetch/reconcile after generated, normalized, reordered, destructive, or remote-function mutations.
- [ ] Shared/realtime state has writer + observer E2E proof without manual refresh.
- [ ] Selectors use stable text/semantics/tooltips or central `AppWidgetKeys`; no inline string keys or coordinate primary taps.
- [ ] E2E entrypoint is deterministic and isolated from production `main.dart`; logs and cleanup are captured.
- [ ] GoRouter redirects use pure matrix-tested resolver, nullable by-id providers/fallback UI, and generated typed route helpers.
- [ ] Cross-runtime constants, schemas, and function contracts have drift tests; no app-root text-scale clamp.
