# State Management — Notifier Structure

## Read first

1. Use `@riverpod` / `@Riverpod` codegen for every provider and notifier.
2. Sync `Notifier.build()` must not read `state` before the first assignment; seed with a direct value or defer work with `Future.microtask`.
3. Keep generated notifier shape conventional: `class FooNotifier extends _$FooNotifier`.

## Trigger

Signals: `Notifier`, `AsyncNotifier`, `build()`, loading state, `AsyncValue`, cleanup, progress state.
Before code: output `Reading: notifier-structure.md`.

## Notifier shape

```dart
part 'cart_notifier.g.dart';

@Riverpod(keepAlive: true)
class CartNotifier extends _$CartNotifier {
  @override
  CartState build() {
    Future.microtask(_load);
    return const CartState(items: [], isLoading: true);
  }
}
```

Rules:

- Use generated refs from the base class; do not store a `Ref` field.
- Do not use `StateNotifier`, `StateNotifierProvider`, `StateProvider`, manual `Provider`, or manual `AsyncNotifierProvider`.
- State is a sealed Freezed class when it carries meaningful state.
- Use `copyWith` for state updates after the first sync seed.

## Sync notifier init trap

Never read `state`, `state.copyWith`, or a provider callback that reads `state` before sync `build()` returns.

```dart
// WRONG: state is uninitialized before build returns.
@override
CounterState build() {
  state = state.copyWith(isLoading: true);
  return state;
}
```

```dart
// RIGHT: direct seed, async work deferred.
@override
CounterState build() {
  Future.microtask(_load);
  return const CounterState(isLoading: true);
}
```

## AsyncNotifier

Use `AsyncNotifier` when the provider's primary value is loaded asynchronously and the UI naturally renders `AsyncValue<T>`.

```dart
@riverpod
class ProfileNotifier extends _$ProfileNotifier {
  @override
  Future<Profile> build(String userId) async {
    final repo = ref.read(profileRepositoryProvider);
    return repo.fetch(userId);
  }
}
```

For durable app state with explicit flags, prefer a Freezed state object behind a sync notifier plus deferred load.

## Loading and progress

Keep initial loading, background refresh, and load-more state distinct:

- `isLoading`: first load only.
- `isRefreshing`: already-rendered data is being refreshed.
- `isLoadingMore`: paginated append.
- `progress`: long-running visible operation with bounded UI updates.

## Cleanup

Register lifecycle cleanup in `build()`:

```dart
@override
SearchState build() {
  final timer = _debouncer;
  ref.onDispose(timer.dispose);
  return const SearchState();
}
```

Do not keep provider-derived caches, repository instances, or subscriptions in widget state. Use generated providers, notifier state, repository/service memo fields, or computed providers as the single source of truth.

## Full reference

For rare edge cases not covered here, read [state-management.md](../state-management.md).
