# State Management — Notifier Structure

## Read first

1. Use `@riverpod` / `@Riverpod` codegen for every provider and notifier.
2. Sync `Notifier.build()` must not read `state` before the first assignment; seed directly. Use `AsyncNotifier.build()` for primary async state.
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
// RIGHT: direct seed. An explicit durable owner starts later work.
@override
CounterState build() {
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

For durable app state with explicit flags, keep a Freezed state object behind a sync notifier. Start loading from an explicit app/bootstrap owner after its watch/listen path exists, or expose an idempotent `load()` that the durable owner calls. Do not rely on `Future.microtask` ordering to beat route pause or listener attachment.

## Pause-sensitive startup

- Route widgets may stop listening while covered or offstage; route-local listeners cannot own durable startup or one-shot delivery.
- Root/bootstrap owner = eagerly watch durable state + register the listener before calling idempotent startup.
- One-shot navigation/snackbar/status = durable state with an identity/sequence + explicit acknowledgement; never an unbuffered callback.
- Provider projection = watch the base state directly; avoid computed-provider → computed-provider chains for pause-sensitive values.
- Regression proof = start covered/paused → emit first update → resume → exact current state or pending event appears once.

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
