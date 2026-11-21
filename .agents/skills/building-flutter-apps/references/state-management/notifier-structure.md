# State Management — Notifier Structure

## Read first

1. Use `@riverpod` / `@Riverpod` codegen for every provider and notifier.
2. Sync `Notifier.build()` must not read `state` before the first assignment; seed directly. Use `AsyncNotifier.build()` for primary async state.
3. Keep generated notifier shape conventional: `class FooNotifier extends _$FooNotifier`.

## Trigger

Signals: `Notifier`, `AsyncNotifier`, `build()`, loading state, `AsyncValue`, cleanup, progress state.

## Notifier shape

```dart
part 'cart_notifier.g.dart';

@Riverpod(keepAlive: true)
class CartNotifier extends _$CartNotifier {
  @override
  Future<CartState> build() async {
    final items = await ref.read(cartRepositoryProvider).load();
    return CartState(items: items);
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
// RIGHT: a sync build() only seeds. State that loads belongs in AsyncNotifier.build(), below.
@override
CounterState build() => const CounterState();
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

State that must load as soon as a screen reads it goes in `AsyncNotifier.build()`. The first read or watch starts the load, so no screen code starts it. This is the fix for `avoid_sync_notifier_state_read`, which refuses load calls inside a sync `build()`. Keep a Freezed state object with explicit flags inside the `AsyncValue` when the UI needs them, such as `isLoadingMore`. Later work, such as the next page, a refresh or a retry, starts from the event that causes it: scroll, pull to refresh or a button. Never call `ref.read` in `initState` to start a load. Never delay a load with a frame callback or a zero-delay wait ([the forms](../flutter-optimizations.md#start-work-at-its-trigger)). Exception: pause-sensitive startup starts from its durable owner after the watch/listen path exists, through an idempotent `load()` ([pause boundaries](../state-management-lifecycle.md#pause-projection-and-mode-boundaries)). Do not rely on `Future.microtask` ordering there to beat route pause or listener attachment: it is one of the refused forms.

## Loading and progress

Keep initial loading, background refresh, and load-more state distinct:

- `isLoading`: on a sync state, work that an event starts. A first load that starts in `AsyncNotifier.build()` uses the `AsyncValue` loading state instead.
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
