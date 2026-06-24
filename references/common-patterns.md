# Common Patterns

## Read first

1. Typed GoRouter helpers only. No raw route strings at call sites.
2. `ref.mounted` after every notifier await; `context.mounted` after widget await.
3. GoRouter redirect uses `ref.listen` + `refreshListenable`, never `ref.watch`; loading returns `null`.
4. Route-id lookups in `build()` are nullable + fallback UI; never throw.
5. Modals pop results only. Teardown lives in notifier. High-frequency boundaries debounce/gate/batch.
6. Splash/cover routing does not wait for background initial sync; route to the shell once auth/setup are known.
7. Provider-derived caches have one SSOT: computed provider, notifier/repo state, or memoized service/repo/datasource cache.
8. Widgets dispatch only. No `try/catch`, awaited notifier-result branching, top-level/global helper functions, `*Data` collection helper namespaces, or private collection derivation helpers.
9. Route-current guards use `context.isCurrentModalRoute`; never inline raw `ModalRoute` current-route checks.

## Trigger

Signals: pagination, search debounce, form validation, GoRouter redirect, typed routes
Before code: output `Reading: common-patterns.md`


## Rules — NEVER Violate

1. **MUST** use generated typed GoRouter route helpers as the navigation SSOT. Call `SomeRoute(...).go(context)` / `.push<T>(context)` directly. Route definitions own paths and params. Local sheet/dialog helpers own modal presentation and dismissal.
2. **NEVER** use `ref.watch()` inside GoRouter `redirect` — recreates router every state change.
3. **MUST** guard `if (!ref.mounted) return;` after EVERY `await` in notifiers (pagination, search, forms, sync).
4. **MUST** use `ref.listen()` + `refreshListenable` for GoRouter redirect triggers — NEVER `ref.watch()`.
5. **MUST** debounce search inputs (500ms min) — NEVER call API on every keystroke.
6. **During loading, stay put.** Return `null` from redirect — NEVER bounce to splash on web refresh.
7. **MUST** guard page back with a typed fallback route for deep-link/resume safety.
8. **NEVER** keep splash/cover routes mounted while initial sync runs. After auth/setup state resolves, route to the shell and let sync hydrate local data in the background. Lint: `router_splash_waits_for_initial_sync`.
9. **Route-id lookups in widget `build()` MUST be nullable.** Use by-id provider + fallback UI. Never throw in `build()`.
10. **Wizard/deep-link mutation order MUST be:** persist write → targeted parent sync → navigate.
11. **Repo mounted rule:** keep `context.mounted` in widget async flows. Never swap to `mounted` to silence lint; refactor flow instead.
12. **NEVER** wrap `runApp` in a guarded zone. Keep app startup simple: `WidgetsFlutterBinding.ensureInitialized(); await Crash.init(); runApp(...)`. See [crashlytics.md](crashlytics.md).
13. **MUST** keep the app shell declarative. The widget that returns `MaterialApp`, `CupertinoApp`, or `WidgetsApp` owns shell config only. Put root bootstrap listeners in a sibling/dedicated `ConsumerWidget` under `ProviderScope`; use `ref.watch` for eager initialization and `ref.listen` for UI side effects. Lint: `app_shell_bootstrap_side_effects`.
14. **NEVER** put controller logic or provider-derived caches in widgets. No widget `try/catch`, no `final ok = await ref.read(xProvider.notifier).save(); if (ok) ...`, no local `_isSaving` / `_isSubmitting` flags beside provider mutations, no top-level/global widget helper functions, no `ProviderSubscription` fields, no `ref.listenManual`, no `*Data` helper namespaces that filter/map/sort/index collections, and no private widget filtering/sorting/cache helpers. Cache/index/snapshot/mutation state belongs to one provider/notifier/repo/service SSOT. Lints: `riverpod_consumer_state_derived_cache`, `riverpod_consumer_state_provider_subscription`, `riverpod_listen_manual_forbidden`, `widget_top_level_function_boundary`, `widget_try_catch_boundary`, `widget_awaits_notifier_result`, `widget_local_mutation_flag`, `widget_derived_collection_logic`.
15. **MUST** use `context.isCurrentModalRoute` for route-current guards. Do not inline `ModalRoute.of(context).isCurrent`, local `route.isCurrent`, or `ModalRoute.isCurrentOf(context)` outside `core/extensions/context_extensions.dart`. Lint: `use_context_is_current_modal_route`.

## Pattern Sections

- [Navigation Flow](common-patterns/navigation-flow.md)
- [Lists, Forms, and Workflows](common-patterns/lists-forms-workflows.md)
- [Routing and App Shell](common-patterns/routing-app-shell.md)
- [Delta Sync](common-patterns/delta-sync.md)
- [Modals and Navigation](common-patterns/modals-navigation.md)
- [Debounce, Gate, and Batch](common-patterns/debounce-gate-batch.md)

## Route-Param Safety + Wizard Sequencing

Read [Navigation Flow](common-patterns/navigation-flow.md#route-param-safety-wizard-sequencing).

## Pagination

Read [Lists, Forms, and Workflows](common-patterns/lists-forms-workflows.md#pagination).

## Search with Debounce

Read [Lists, Forms, and Workflows](common-patterns/lists-forms-workflows.md#search-with-debounce).

## Local Filter (No API Call)

Read [Lists, Forms, and Workflows](common-patterns/lists-forms-workflows.md#local-filter-no-api-call).

## Form Validation

Read [Lists, Forms, and Workflows](common-patterns/lists-forms-workflows.md#form-validation).

## Batch Processing

Read [Lists, Forms, and Workflows](common-patterns/lists-forms-workflows.md#batch-processing).

## Pull-to-Refresh

Read [Lists, Forms, and Workflows](common-patterns/lists-forms-workflows.md#pull-to-refresh).

## Typed GoRouter Route SSOT

Read [Routing and App Shell](common-patterns/routing-app-shell.md#typed-gorouter-route-ssot).

## Long-Running Sync/Auth Cancellation

Read [Routing and App Shell](common-patterns/routing-app-shell.md#long-running-syncauth-cancellation).

## App Shell + Bootstrap Boundary

Read [Routing and App Shell](common-patterns/routing-app-shell.md#app-shell-bootstrap-boundary).

## Delta Sync (Incremental Remote Pull)

Read [Delta Sync](common-patterns/delta-sync.md#delta-sync-incremental-remote-pull).

## Modal Snapshot Pattern

Read [Modals and Navigation](common-patterns/modals-navigation.md#modal-snapshot-pattern).

## Dismiss Modal → Push Route (Bottom Sheet Navigation)

Read [Modals and Navigation](common-patterns/modals-navigation.md#dismiss-modal-push-route-bottom-sheet-navigation).

## Pop Fallback Helpers Check Navigator Stacks

Read [Modals and Navigation](common-patterns/modals-navigation.md#pop-fallback-helpers-check-navigator-stacks).

## Debounce, Gate, and Batch

Read [Debounce, Gate, and Batch](common-patterns/debounce-gate-batch.md#debounce-gate-and-batch).

## Remote Functions + destructive reconciliation

Read [Debounce, Gate, and Batch](common-patterns/debounce-gate-batch.md#remote-functions-destructive-reconciliation).
