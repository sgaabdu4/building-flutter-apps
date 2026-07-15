# State Management — Async Mutations


## Read first

1. Guard every notifier/repository `await` with `if (!ref.mounted) return;` before touching state or ref again.
2. Inside `finally`, use `if (ref.mounted) { ... }`; do not early-return from `finally`.
3. Stable infrastructure dependencies use `ref.read`; reactive rendering uses `ref.watch` in `build()`.

## Trigger

Signals: mutation method, `ref.read`, `ref.watch`, `ref.listen`, `_ensureRepository`, async cancellation, optimistic update, duplicate fetch.
Before code: output `Reading: async-mutations.md`.

## Mounted guards

```dart
Future<void> save() async {
  state = state.copyWith(isSaving: true);
  try {
    await ref.read(orderRepositoryProvider).save(state.order);
    if (!ref.mounted) return;
    state = state.copyWith(isSaving: false, successSerial: state.successSerial + 1);
  } catch (error, stackTrace) {
    if (!ref.mounted) return;
    state = state.copyWith(isSaving: false, error: AppError.from(error, stackTrace));
  }
}
```

```dart
Future<void> refresh() async {
  state = state.copyWith(isRefreshing: true);
  try {
    await _load();
  } finally {
    if (ref.mounted) {
      state = state.copyWith(isRefreshing: false);
    }
  }
}
```

## Dependency readiness

Do not cache repositories/services in notifier fields just to avoid reading providers.

```dart
Future<void> placeOrder() async {
  final auth = ref.read(authNotifierProvider);
  final cart = ref.read(cartNotifierProvider);
  final repo = ref.read(orderRepositoryProvider);

  if (auth case Authenticated(:final user)) {
    await repo.place(user.id, cart.items);
    if (!ref.mounted) return;
    state = state.copyWith(successSerial: state.successSerial + 1);
  }
}
```

Use `ref.watch` only in `build()` when the notifier intentionally rebuilds from another provider. Use `ref.listen` in `build()` for side effects tied to provider changes.

## Optimistic updates

Optimistic updates need deterministic rollback or source-of-truth reconciliation:

```dart
Future<void> markRead(NotificationId id) async {
  final previous = state;
  state = state.markRead(id);
  try {
    await ref.read(notificationsRepositoryProvider).markRead(id);
    if (!ref.mounted) return;
    await _reloadFromSourceOfTruth();
  } catch (error, stackTrace) {
    if (!ref.mounted) return;
    state = previous.copyWith(error: AppError.from(error, stackTrace));
  }
}
```

## Duplicate fetches

Guard long-running work:

```dart
Future<void> loadMore() async {
  if (state.isLoadingMore || !state.hasMore) return;
  state = state.copyWith(isLoadingMore: true);
  final page = await ref.read(productRepositoryProvider).fetch(cursor: state.cursor);
  if (!ref.mounted) return;
  state = state.append(page);
}
```

## UI effects

Do not create standalone `*Signal` / `*Event` / `*Pulse` providers for one-shot UI effects. Put serial/payload fields on the owning state and listen from the widget:

```dart
ref.listen(
  checkoutNotifierProvider.select((state) => state.successSerial),
  (previous, next) {
    if (previous != next) const OrdersRoute().go(context);
  },
);
```
