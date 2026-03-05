# State Management

Notifier patterns to manage mutable state with Riverpod 3.x codegen.

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
    _load();
    return const ProductState();
  }

  Future<void> _load() async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      final items = await ref.read(productRepositoryProvider).fetchAll();
      if (!ref.mounted) return;
      state = state.copyWith(items: items, isLoading: false);
    } catch (e) {
      if (!ref.mounted) return;
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }

  Future<void> refresh() async => _load();
}
```

## ref.mounted Guard

Riverpod 3.0 throws if you interact with a disposed Ref. Always guard after `await`:

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

Guard after every `await`, not just the first one.

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
    _load();
    return const ProductState();
  }

  Future<void> _load() async {
    if (_isFetching) return;
    _isFetching = true;

    state = state.copyWith(isLoading: true);
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

Use the build method for initialization. Riverpod calls `build()` when the provider is first read:

```dart
@Riverpod(keepAlive: true)
class AuthNotifier extends _$AuthNotifier {
  @override
  AuthState build() {
    // Start async load — build itself returns sync
    _checkSession();
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
      AsyncError(:final error) => Text('Error: $error'),
      AsyncLoading() => const CircularProgressIndicator(),
    };
  }
}
```

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

Catch errors once — in the notifier. Let datasources and repositories throw.

```dart
// Datasource — no try-catch
Future<List<ProductModel>> fetchAll() => _http.get('/products');

// Repository — no try-catch
Future<List<Product>> fetchAll() async {
  final models = await _remote.fetchAll();
  return models.map((m) => m.toEntity()).toList();
}

// Notifier — catch here
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

Use `ref.read` for one-time access. Use `ref.watch` to rebuild when dependencies change. Use `ref.listen` for side effects.
