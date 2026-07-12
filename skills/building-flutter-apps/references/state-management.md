# State Management

## Read first

1. No prop-drilling state. Child widgets watch providers by ID.
2. Provider-derived caches have one SSOT: generated computed provider, notifier/repo state, or memoized service/repo/datasource cache.
3. Widgets are UI + dispatch only: no `try/catch`, no awaited notifier result branching, no top-level/global helper functions, no `*Data` helper namespaces that filter/map/sort/index collections, no private collection helpers.
4. Notifiers/widgets never touch storage SDKs; use Local Datasource → Repository.
5. After every notifier/repo await: `if (!ref.mounted) return;`. In `finally`: `if (ref.mounted) { ... }`.
6. After every widget/State await: `if (!context.mounted) return;`. No bare `mounted`.
7. No `ref.watch()` inside notifier methods; `ref.watch` in `build()` only.
8. Mutation methods lazily init deps; sync `Notifier.build()` never reads `state` before first return.
9. Collections in state are non-null with empty defaults. Model `not loaded` / `not applicable` as AsyncValue or a sealed state, not `List<T>?`.
10. Empty string is allowed only for explicit transient draft/search/input text. Domain-required strings use VOs; optional strings normalize blank to `null`.

## Trigger

Signals: ref.mounted, Notifier, AsyncNotifier, state.copyWith, ref.onDispose, sync notifier trap
Before code: output `Reading: state-management.md`


## Rules — NEVER Violate

0. **NEVER prop-drill state.** Child widgets watch the provider directly via `ref.watch` / `ref.read` / `ref.listen`. Do **not** pass entity / state / notifier instances through constructor parameters. Allowed constructor params: `Key`, callbacks (`VoidCallback`, `ValueChanged`, etc.), primitive props on atoms, and immutable IDs for lookup. `class OrderCard extends StatelessWidget { final OrderEntity order; ... }` — forbidden. `class OrderCard extends ConsumerWidget { final String orderId; ... build → ref.watch(orderProvider(orderId)) }` — correct.

0b. **NEVER call storage SDK from a notifier or widget.** `Hive.openBox`, `Hive.box`, `box.get`/`put`/`delete`, `SharedPreferences.getInstance`, `FlutterSecureStorage()`, `getApplicationDocumentsDirectory()`, `dart:io` file ops — all live behind a `Local<X>Datasource` interface, called by `<X>Repository`. Notifier depends on the repository provider, not on storage. Imports of `package:hive_ce`, `package:hive_ce_flutter`, `package:shared_preferences`, `package:flutter_secure_storage`, `package:path_provider`, or `dart:io` in `*_notifier.dart` or any `presentation/` file are violations.

0c. **MUST extract shared behavior to a mixin.** When the same logic appears in 2+ notifiers, widgets, or services, write `mixin XxxMixin on Y` and apply via `with`. Suffix the name with `Mixin`. Copy-paste sharing across notifiers / widgets / services is forbidden. See [mixins.md](mixins.md).

0d. **NEVER duplicate provider-derived caches or mutation events.** One generated computed provider/notifier/repo/service owns the cached/indexed/snapshot value and one-shot event serials/payloads. `ConsumerState` may own UI lifecycle handles only (controller/focus/animation/timer). Fields like `*Cache`, `*Source`, `*Snapshot`, `*Memo`, `*ById`, provider-family arg wrappers (`config`/`args`/`params`), and `ProviderSubscription` in widget state are forbidden. Standalone `*Signal` / `*Event` / `*Pulse` / `*Serial` providers are forbidden; fold the serial/payload into the owning notifier state and listen to a concrete field with `select`. Durable status providers must be named by the state they own, e.g. `*StatusNotifier` / `*Lifecycle`, not `*Signal`. `ref.listenManual` is forbidden. Use `ref.listen` in `build` for UI side effects; move durable sync to the provider/notifier SSOT. Lints: `riverpod_consumer_state_derived_cache`, `riverpod_widget_provider_arg_wrapper`, `riverpod_consumer_state_provider_subscription`, `riverpod_listen_manual_forbidden`, `riverpod_event_counter_signal_forbidden`.

1. **MUST** check `if (!ref.mounted) return;` after EVERY `await` in notifier.
2. **MUST** check `if (!context.mounted) return;` after EVERY `await` in widget.
3. **MUST** catch error in notifier by default. Datasource, repo propagate. `try/catch` at data layer allowed **only** for: (a) domain error translation, (b) idempotency recovery (404/409), (c) transaction rollback, (d) local-first fire-and-forget sync. Plain log-and-rethrow forbidden — delete. Widget `try/catch` is forbidden; lint: `widget_try_catch_boundary`.
4. **NEVER** make widgets branch on awaited notifier results or own local busy flags for provider mutations. `final ok = await ref.read(xProvider.notifier).save(); if (ok) ...` and `bool _isSaving = false;` beside `ref.read(xProvider.notifier).save()` both turn the widget into a controller. Notifier owns the decision, exposes `isSaving` / `isSubmitting` and success serials, and widgets observe/listen. Lints: `widget_awaits_notifier_result`, `widget_local_mutation_flag`.
5. **NEVER** declare top-level/global helper functions in widget/screen files. Put behavior on a widget class, `abstract final class` namespace, notifier, or computed provider. Lint: `widget_top_level_function_boundary`.
6. **MUST** `ref.read()` one-time access in callback. MUST `ref.watch()` rebuild on dep change.
7. **MUST** dispose timer, controller, subscription via `ref.onDispose()`.
8. **NEVER** `ref.watch()` inside notifier method — use `ref.read()` or `ref.listen()`.
9. **NEVER** set state after mounted check fail — return now.
10. **NEVER** read `state` (incl `state.copyWith`) inside sync `Notifier.build()` or any path sync before `build()` returns. First `state` assign in sync notifier must be direct value (e.g. `state = const FooState(isLoading: true)`), or deferred via `Future.microtask`. Read state before first `state=` throw *"Tried to read the state of an uninitialized provider"*. `AsyncNotifier` exempt (pre-init `AsyncLoading`). See [Sync Notifier Initialization Trap](#sync-notifier-initialization-trap).
11. **MUST** init repo/dep inside mutation method before write (`create*`, `update*`, `delete*`, `set*`, `reorder*`). Never rely on background `_init*()` timing.
11b. **MUST** guard async `_init*` / `_restore*` / `_load*` notifier writes with a generation/request token. A background load/restore that started before a user mutation must not assign `state` after the mutation. Lint: `notifier_async_init_stale_state_write`.
12. **MUST** avoid broad parent-provider invalidation in nav-critical flow (wizard/deep-link route param). Use targeted sync (`upsert`/replace/remove).
13. **NEVER** swap `context.mounted` to `mounted` to suppress lint. Style = `context.mounted`. In `State` methods, use `final context = this.context;` before `await`, then `if (!context.mounted) return;`.
14. **NEVER** use nullable collection state (`List<T>?`, `Map<K, V>?`, `Set<T>?`). Use `@Default([])` / `@Default({})`, or model tri-state with a sealed union / `AsyncValue`.
15. **NEVER** use `''` or boolean `"1"` / `"0"` strings as state sentinels. Name transient text fields explicitly (`query`, `searchQuery`, `draftName`, `inputText`). Keep booleans typed; if a wire protocol truly needs `"1"` / `"0"`, convert at the datasource boundary with a named encoder. Required domain text becomes a VO before it reaches domain. Optional text is `String?`, with blank normalized to `null` at the notifier/repo boundary. Lints: `nullable_collection_type`, `state_empty_string_sentinel`, `state_bool_string_sentinel`.

## Nullability + Empty Values

Dart null safety makes non-nullable the default, but `null` is still correct
for real absence. Do not fight the type system with sentinels.

| Situation | Use |
|---|---|
| Loaded, no items | `@Default([]) List<T> items` |
| Not loaded vs loaded empty | `AsyncValue<List<T>>` or sealed state |
| Optional note / bio / description | `String?`, blank input normalized to `null` |
| Required email / ID / slug / name | Value Object with non-empty validation |
| Search box / form draft before submit | `@Default('') String query` / `draftName` |

```dart
String? optionalTextFromInput(String value) {
  final trimmed = value.trim();
  return trimmed.isEmpty ? null : trimmed;
}
```

## Widget Context After Await

Widgets guard the `BuildContext`, not just `State.mounted`.

```dart
class ProductPageState extends ConsumerState<ProductPage> {
  Future<void> save() async {
    final context = this.context;

    await ref.read(productProvider.notifier).save();
    if (!context.mounted) return;

    const ProductListRoute().go(context);
  }
}
```

Do not pass `BuildContext` into async helpers just for navigation/snackbars.
Navigation uses generated typed route helpers; see
[common-patterns.md](common-patterns.md#typed-gorouter-route-ssot).

## Notifier Structure

Every feature notifier follow same pattern:

```dart
part 'product_notifier.g.dart';

@freezed
sealed class ProductState with _$ProductState {
  const factory ProductState({
    @Default([]) List<Product> items,
    @Default(false) bool isLoading,
    AppError? error,
  }) = _ProductState;
}

@Riverpod(keepAlive: true)
class ProductNotifier extends _$ProductNotifier {
  int _loadGeneration = 0;

  @override
  ProductState build() {
    // Defer work — avoids reading uninitialized state during build.
    // See "Sync Notifier Initialization Trap".
    final generation = ++_loadGeneration;
    Future.microtask(() => _load(generation));
    return const ProductState(isLoading: true);
  }

  Future<void> _load(int generation) async {
    if (!ref.mounted) return;
    try {
      final items = await ref.read(productRepositoryProvider).fetchAll();
      if (!ref.mounted) return;
      if (generation != _loadGeneration) return;
      state = state.copyWith(items: items, isLoading: false);
    } on Exception catch (e, s) {
      if (!ref.mounted) return;
      state = state.copyWith(isLoading: false, error: AppError.from(e));
      Crash.error(e, s, reason: 'ProductNotifier._load');
    }
  }

  Future<void> refresh() async {
    final generation = ++_loadGeneration;
    state = state.copyWith(isLoading: true, error: null);
    await _load(generation);
  }
}
```

## Sync Notifier Initialization Trap

Sync `Notifier<T>` has **no initial state** until `build()` returns. Read `state` before first `state=` throw:

> `Bad state: Tried to read the state of an uninitialized provider.`

(See `riverpod/src/core/provider/notifier_provider.dart` — `state` getter documents this.)

Dart `async` body runs **sync up to first `await`**. So calling `_load()` from `build()` executes code before first `await` *before* `build()` returns. If that code reads `state` (incl `state.copyWith(...)`), throw.

`AsyncNotifier` exempt — Riverpod pre-init state to `AsyncLoading` before `build()` runs.

### ❌ Wrong — read before init

```dart
@Riverpod(keepAlive: true)
class ProductNotifier extends _$ProductNotifier {
  @override
  ProductState build() {
    _load();                       // body runs sync until first await
    return const ProductState();
  }

  Future<void> _load() async {
    state = state.copyWith(        // ❌ state not yet initialized — throws
      isLoading: true,
    );
    final items = await ref.read(productRepositoryProvider).fetchAll();
    // ...
  }
}
```

### ❌ Wrong — `fireImmediately: true` w/ sync state read

```dart
@override
FooState build() {
  ref.listen(authProvider, (prev, next) {
    state = state.copyWith(...);   // ❌ fires sync during build — throws
  }, fireImmediately: true);
  return const FooState();
}
```

### ✅ Right — direct-value seed + deferred load

```dart
@override
ProductState build() {
  Future.microtask(_load);                         // runs after build returns
  return const ProductState(isLoading: true);      // seed via constructor
}
```

### ✅ Right — set state before register `fireImmediately` listener

```dart
@override
FooState build() {
  // A direct-value write primes state so later reads inside listeners are safe.
  state = const FooState();
  ref.listen(authProvider, (prev, next) {
    state = state.copyWith(...);                   // safe
  }, fireImmediately: true);
  return state;
}
```

### ✅ Right — drop `fireImmediately`, defer init handling

```dart
@override
FooState build() {
  ref.listen(authProvider, _handleAuthChange);     // no fireImmediately
  Future.microtask(() {
    if (!ref.mounted) return;
    _handleAuthChange(null, ref.read(authProvider));
  });
  return const FooState();
}
```

Rule of thumb: **first `state =` in sync notifier must be direct value, not `copyWith`.**

## ref.mounted Guard

Riverpod 3.0 throw if touch disposed Ref. MUST guard after EVERY `await`:

```dart
Future<void> save(Product product) async {
  state = state.copyWith(isLoading: true);

  await ref.read(productRepositoryProvider).save(product);
  if (!ref.mounted) return;  // REQUIRED

  state = state.copyWith(isLoading: false);

  await ref.read(productRepositoryProvider).refreshCache();
  if (!ref.mounted) return;  // REQUIRED after each await

  final items = await _fetchAll();
  if (!ref.mounted) return;  // REQUIRED — `await` inside copyWith still needs guard
  state = state.copyWith(items: items);
}
```

MUST guard after EVERY `await`, not just first.

### Inside `finally` — Guard, Never Early-Return

Use the guard form, not the early-return form. `return;` in `finally` swallows in-flight exceptions (Dart `control_flow_in_finally` + custom `avoid_mounted_check_in_finally` with auto-fix).

```dart
// ❌ Wrong — `return;` in finally eats exceptions
try {
  await doWork();
} finally {
  if (!ref.mounted) return;
  state = state.copyWith(isResetting: false);
}

// ✅ Correct — guard the assignment, no control flow in finally
try {
  await doWork();
} finally {
  if (ref.mounted) {
    state = state.copyWith(isResetting: false);
  }
}
```

Same rule for `context.mounted` in `State` cleanup, and bare `mounted` inside `State`.

## Dependency Readiness For Mutations

Mutation methods must resolve deps before writes. Do not add notifier-local
repository cache fields; Riverpod provider caching is the SSOT.

### ❌ Wrong — null repo short-circuit in user action

```dart
Future<void> saveThing(Thing thing) async {
  final repo = _repository;
  if (repo == null) return; // drops user action
  await repo.save(thing);
}
```

### ❌ Wrong — notifier-local repository cache

```dart
class ThingNotifier extends _$ThingNotifier {
  IThingRepository? _repository;

  Future<IThingRepository?> _ensureRepository() async {
    _repository ??= await ref.read(thingRepositoryProvider.future);
    if (!ref.mounted) return null;
    return _repository;
  }
}
```

### ✅ Right — resolve before write from provider SSOT

```dart
Future<IThingRepository?> thingRepositoryOrNull(Ref ref) async {
  final repo = await ref.read(thingRepositoryProvider.future);
  if (!ref.mounted) return null;
  return repo;
}

Future<void> saveThing(Thing thing) async {
  final repo = await thingRepositoryOrNull(ref);
  if (repo == null) return;
  await repo.save(thing);
  if (!ref.mounted) return;
}
```

Rule of thumb: method mutates data → resolve dependencies first via a
stateless helper/mixin, then write. No `_repository` / `_repo` / `_service`
cache fields in generated notifiers unless the field owns a real lifecycle
resource that must be disposed. Lint: `notifier_local_dependency_cache`.

## Optimistic Updates

Update UI now. Revert on fail:

```dart
Future<void> deleteItem(String id) async {
  final previousItems = state.items;

  // Update UI immediately
  state = state.copyWith(
    items: state.items.where((i) => i.id != id).toList(),
  );

  try {
    await ref.read(productRepositoryProvider).delete(id);
  } catch (e) {
    if (!ref.mounted) return;
    // Revert on failure
    state = state.copyWith(
      items: previousItems,
      error: 'Delete failed',
    );
  }
}
```

## Preventing Duplicate Fetches

Guard vs multiple simultaneous fetch:

```dart
@Riverpod(keepAlive: true)
class ProductNotifier extends _$ProductNotifier {
  bool _isFetching = false;

  @override
  ProductState build() {
    Future.microtask(_load);
    return const ProductState(isLoading: true);
  }

  Future<void> _load() async {
    if (_isFetching) return;
    _isFetching = true;

    // Safe: runs after build returns, so state is initialized.
    if (ref.mounted) state = state.copyWith(isLoading: true);
    try {
      final items = await ref.read(productRepositoryProvider).fetchAll();
      if (!ref.mounted) return;
      state = state.copyWith(items: items, isLoading: false);
    } on Exception catch (e, s) {
      if (!ref.mounted) return;
      state = state.copyWith(isLoading: false, error: AppError.from(e));
      Crash.error(e, s, reason: 'PaginatedProductNotifier._load');
    } finally {
      _isFetching = false;
    }
  }
}
```

## Async Initialization

Use build method for init. Riverpod call `build()` when provider first read. For sync `Notifier`, **dispatch async init via `Future.microtask`** so nothing reads `state` before `build()` returns (see [Sync Notifier Initialization Trap](#sync-notifier-initialization-trap)):

```dart
@Riverpod(keepAlive: true)
class AuthNotifier extends _$AuthNotifier {
  @override
  AuthState build() {
    Future.microtask(_checkSession);
    return const AuthState.loading();
  }

  Future<void> _checkSession() async {
    try {
      final user = await ref.read(authRepositoryProvider).getSession();
      if (!ref.mounted) return;
      state = AuthState.authenticated(user);
    } catch (_) {
      if (!ref.mounted) return;
      state = const AuthState.unauthenticated();
    }
  }
}
```

## AsyncNotifier Pattern

Provider expose `AsyncValue` direct:

```dart
@Riverpod(keepAlive: true)
class UserNotifier extends _$UserNotifier {
  @override
  Future<User> build() async {
    final repo = ref.read(userRepositoryProvider);
    return repo.getCurrentUser();
  }

  /// Refresh data
  Future<void> refresh() async {
    state = const AsyncLoading<User>();
    final nextState = await AsyncValue.guard(() async {
      final repo = ref.read(userRepositoryProvider);
      return repo.getCurrentUser();
    });
    if (!ref.mounted) return;
    state = nextState;
  }

  Future<void> updateName(String name) async {
    state = const AsyncLoading();
    final nextState = await AsyncValue.guard(() async {
      final repo = ref.read(userRepositoryProvider);
      return repo.updateName(name);
    });
    if (!ref.mounted) return;
    state = nextState;
  }
}

// Widget usage
class UserProfile extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final userAsync = ref.watch(userProvider);
    return switch (userAsync) {
      AsyncData(:final value) => Text(value.name),
      AsyncError(:final error) => ErrorRetry(
        message: error.toString(),
        onRetry: () => ref.invalidate(userProvider),
      ),
      AsyncLoading() => const ShimmerPlaceholder(), // Prefer shimmer over bare spinner
    };
  }
}
```

**Key:** `AsyncValue.guard` wraps try-catch and returns `AsyncData` or `AsyncError`. Still guard `ref.mounted` after the awaited guard before assigning `state`. Avoid `copyWithPrevious`; internal in Riverpod 3 dev builds.

## AsyncValue.requireValue

Combine multi async provider sync when know loaded:

```dart
@Riverpod(keepAlive: true)
class DashboardNotifier extends _$DashboardNotifier {
  @override
  Future<DashboardData> build() async {
    // Both providers load in parallel
    final user = ref.watch(userProvider).requireValue;
    final products = ref.watch(productProvider).requireValue;

    return DashboardData(user: user, products: products);
  }
}
```

Use `requireValue` only when certain provider has data. Throw if loading/error.

## Loading Progress

Report progress w/ `AsyncLoading.progress`:

```dart
@override
Future<List<Product>> build() async {
  state = const AsyncLoading(progress: 0.0);
  final page1 = await fetchPage(1);

  state = const AsyncLoading(progress: 0.5);
  final page2 = await fetchPage(2);

  return [...page1, ...page2];
}
```

## Cleanup

Dispose timer, controller, subscription:

```dart
@Riverpod(keepAlive: true)
class SearchNotifier extends _$SearchNotifier {
  Timer? _debounceTimer;

  @override
  SearchState build() {
    ref.onDispose(() => _debounceTimer?.cancel());
    return const SearchState();
  }
}
```

Lifecycle listener now return unsubscribe fn:

```dart
final removeDispose = ref.onDispose(() => cleanup());
// Later, remove the listener if needed:
removeDispose();
```

## State Teardown, Errors, and Cross-Provider Communication

Read [state-management-lifecycle.md](state-management-lifecycle.md) for notifier-owned teardown, error handling strategy, domain error types, and cross-provider communication.
