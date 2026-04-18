# State Management

Notifier patterns to manage mutable state with Riverpod 3.x codegen.

## Rules — NEVER Violate

1. **MUST** check `if (!ref.mounted) return;` after EVERY `await` in notifiers.
2. **MUST** check `if (!context.mounted) return;` after EVERY `await` in widgets.
3. **MUST** catch errors ONLY in the notifier — NEVER try-catch in datasources or repositories.
4. **MUST** use `ref.read()` for one-time access in callbacks. MUST use `ref.watch()` to rebuild when dependencies change.
5. **MUST** dispose timers, controllers, and subscriptions via `ref.onDispose()`.
6. **NEVER** use `ref.watch()` inside a notifier method — use `ref.read()` or `ref.listen()`.
7. **NEVER** set state after a mounted check fails — return immediately.
8. **NEVER** read `state` (including `state.copyWith`) inside sync `Notifier.build()` or in any code path that runs synchronously before `build()` returns. First `state` assignment in a sync notifier must be a direct value (e.g. `state = const FooState(isLoading: true)`), or deferred via `Future.microtask`. Reading state before first `state=` throws *"Tried to read the state of an uninitialized provider"*. `AsyncNotifier` is exempt (pre-initialized to `AsyncLoading`). See [Sync Notifier Initialization Trap](#sync-notifier-initialization-trap).

```mermaid
graph TD
  A[API call in notifier] --> B{Success?}
  B -->|Yes| C{ref.mounted?}
  B -->|No| D[catch error]
  C -->|Yes| E[Update state with data]
  C -->|No| F[return — do nothing]
  D --> G{ref.mounted?}
  G -->|Yes| H[Set error state]
  G -->|No| F
```

**Contents:** [Notifier Structure](#notifier-structure) | [Sync Notifier Initialization Trap](#sync-notifier-initialization-trap) | [ref.mounted Guard](#refmounted-guard) | [Optimistic Updates](#optimistic-updates) | [Preventing Duplicate Fetches](#preventing-duplicate-fetches) | [Async Initialization](#async-initialization) | [AsyncNotifier Pattern](#asyncnotifier-pattern) | [AsyncValue.requireValue](#asyncvaluerequirevalue) | [Loading Progress](#loading-progress) | [Cleanup](#cleanup) | [Error Handling Strategy](#error-handling-strategy) | [Domain Error Types](#domain-error-types) | [Cross-Provider Communication](#cross-provider-communication)

## Notifier Structure

Every feature notifier follows the same pattern:

```dart
part 'product_notifier.g.dart';

@freezed
sealed class ProductState with _$ProductState {
  const factory ProductState({
    @Default([]) List<Product> items,
    @Default(false) bool isLoading,
    String? error,
  }) = _ProductState;
}

@Riverpod(keepAlive: true)
class ProductNotifier extends _$ProductNotifier {
  @override
  ProductState build() {
    // Defer work — avoids reading uninitialized state during build.
    // See "Sync Notifier Initialization Trap".
    Future.microtask(_load);
    return const ProductState(isLoading: true);
  }

  Future<void> _load() async {
    if (!ref.mounted) return;
    try {
      final items = await ref.read(productRepositoryProvider).fetchAll();
      if (!ref.mounted) return;
      state = state.copyWith(items: items, isLoading: false);
    } catch (e) {
      if (!ref.mounted) return;
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }

  Future<void> refresh() async {
    state = state.copyWith(isLoading: true, error: null);
    await _load();
  }
}
```

Key points:
- Initial loading flag set via the returned constant — never `state.copyWith` before `build()` returns.
- `_load()` is dispatched through `Future.microtask`, so its body runs after `build()` completes and state is initialized.
- `refresh()` is safe to use `state.copyWith` because it runs after mount.

## Sync Notifier Initialization Trap

A sync `Notifier<T>` has **no initial state** until `build()` returns. Reading `state` before the first `state=` throws:

> `Bad state: Tried to read the state of an uninitialized provider.`

(See `riverpod/src/core/provider/notifier_provider.dart` — the `state` getter explicitly documents this.)

A Dart `async` function body runs **synchronously up to its first `await`**. So calling `_load()` from `build()` executes any code before the first `await` *before* `build()` returns. If that code reads `state` (including `state.copyWith(...)`), it throws.

`AsyncNotifier` is exempt because Riverpod pre-initializes its state to `AsyncLoading` before `build()` runs.

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

### ❌ Wrong — `fireImmediately: true` with sync state read

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

### ✅ Right — set state before registering `fireImmediately` listener

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

### ✅ Right — drop `fireImmediately`, defer initial handling

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

Rule of thumb: **first `state =` in a sync notifier must be a direct value, not a `copyWith`.**

## ref.mounted Guard

Riverpod 3.0 throws if you interact with a disposed Ref. MUST guard after EVERY `await`:

```dart
Future<void> save(Product product) async {
  state = state.copyWith(isLoading: true);

  await ref.read(productRepositoryProvider).save(product);
  if (!ref.mounted) return;  // REQUIRED

  state = state.copyWith(isLoading: false);

  await ref.read(productRepositoryProvider).refreshCache();
  if (!ref.mounted) return;  // REQUIRED after each await

  state = state.copyWith(items: await _fetchAll());
}
```

MUST guard after EVERY `await`, not just the first one.

## Optimistic Updates

Update the UI immediately. Revert on failure:

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

Guard against multiple simultaneous fetches:

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
    } catch (e) {
      if (!ref.mounted) return;
      state = state.copyWith(isLoading: false, error: e.toString());
    } finally {
      _isFetching = false;
    }
  }
}
```

## Async Initialization

Use the build method for initialization. Riverpod calls `build()` when the provider is first read. For sync `Notifier`, **dispatch the async init via `Future.microtask`** so nothing reads `state` before `build()` returns (see [Sync Notifier Initialization Trap](#sync-notifier-initialization-trap)):

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

For providers that expose `AsyncValue` directly:

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
    state = await AsyncValue.guard(() async {
      final repo = ref.read(userRepositoryProvider);
      return repo.getCurrentUser();
    });
  }

  Future<void> updateName(String name) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      final repo = ref.read(userRepositoryProvider);
      return repo.updateName(name);
    });
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

**Key:** `AsyncValue.guard` wraps try-catch and assigns `AsyncData` or `AsyncError` atomically. No explicit `ref.mounted` check needed — guard handles state assignment in one step. Avoid `copyWithPrevious`; it is internal in Riverpod 3 dev builds.

## AsyncValue.requireValue

Combine multiple async providers synchronously when you know they're loaded:

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

Use `requireValue` only when you are certain the provider has data. It throws if the provider is in loading or error state.

## Loading Progress

Report loading progress with `AsyncLoading.progress`:

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

Dispose timers, controllers, and subscriptions:

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

Lifecycle listeners now return unsubscribe functions:

```dart
final removeDispose = ref.onDispose(() => cleanup());
// Later, remove the listener if needed:
removeDispose();
```

## Error Handling Strategy

MUST catch errors once — in the notifier. NEVER try-catch in datasources or repositories.

```dart
// Datasource — NEVER try-catch
Future<List<ProductModel>> fetchAll() => _http.get('/products');

// Repository — NEVER try-catch
Future<List<Product>> fetchAll() async {
  final models = await _remote.fetchAll();
  return models.map((m) => m.toEntity()).toList();
}

// Notifier — MUST catch here
Future<void> _load() async {
  try {
    final items = await ref.read(productRepositoryProvider).fetchAll();
    if (!ref.mounted) return;
    state = state.copyWith(items: items);
  } catch (e) {
    if (!ref.mounted) return;
    state = state.copyWith(error: e.toString());
  }
}
```

### Domain Error Types

Define a sealed error hierarchy for typed error handling in notifiers:

```dart
// core/domain/app_error.dart
@freezed
sealed class AppError with _$AppError {
  const factory AppError.network(String message) = NetworkError;
  const factory AppError.validation(String field, String message) = ValidationError;
  const factory AppError.notFound(String resource) = NotFoundError;
  const factory AppError.unauthorized() = UnauthorizedError;
  const factory AppError.unexpected(Object error) = UnexpectedError;
}
```

Use in notifier state and pattern-match in UI:

```dart
// State holds typed error instead of raw string
@freezed
sealed class ProductState with _$ProductState {
  const factory ProductState({
    @Default([]) List<Product> items,
    @Default(false) bool isLoading,
    AppError? error,
  }) = _ProductState;
}

// UI pattern-matches for user-friendly display
if (state.error case NetworkError(:final message))
  ErrorBanner(message: message, onRetry: () => ref.read(productProvider.notifier).refresh())
else if (state.error case NotFoundError(:final resource))
  Text('$resource not found')
```

## Cross-Provider Communication

Read other providers through `ref`:

```dart
@Riverpod(keepAlive: true)
class OrderNotifier extends _$OrderNotifier {
  @override
  OrderState build() => const OrderState();

  Future<void> placeOrder() async {
    final cart = ref.read(cartProvider);
    final user = ref.read(authProvider);

    if (user case Authenticated(:final user)) {
      await ref.read(orderRepositoryProvider).create(
        userId: user.id,
        items: cart.items,
      );
      if (!ref.mounted) return;

      // Reset cart after order
      ref.read(cartProvider.notifier).clear();
    }
  }
}
```

Use `ref.read` for one-time access. Use `ref.watch` to rebuild when dependencies change. Use `ref.listen` for side effects. NEVER use `ref.watch()` inside a notifier method.
