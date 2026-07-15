# State Management Lifecycle And Errors


## Read first

Read with [notifier-structure.md](state-management/notifier-structure.md) for initialization/loading and [async-mutations.md](state-management/async-mutations.md) for mutation readiness, async guards, and optimistic updates.

## State Teardown Belongs in the Notifier

For *save and clear* flows, notifier owns save + clear. Failure preserves retry state. Widgets dispatch method, observe state via `ref.watch` / `onMissing*`, and self-navigate. Do not chain widget-side cleanup after awaited notifier mutation.

```dart
// NEVER — widget owns teardown
Future<bool> save(Entity entity) async {
  state = state.copyWith(isSaving: true);
  await ref.read(logProvider.notifier).addLog(...);
  return true; // caller must reset
}

// In widget:
final ok = await ref.read(formProvider.notifier).save(entity);
if (!context.mounted) return;
ref.read(formProvider.notifier).reset(); // widget-side teardown
```

```dart
// DO — notifier owns teardown
Future<bool> save(Entity entity) async {
  if (state.isSaving) return false;
  state = state.copyWith(isSaving: true);
  try {
    await ref.read(logProvider.notifier).addLog(buildLog(entity));
    if (!ref.mounted) return false;
    reset(); // single owner of teardown — success path only
    return true;
  } catch (e, s) {
    if (!ref.mounted) return false;
    Crash.error(e, s);
    state = state.copyWith(
      isSaving: false,
      saveError: SaveError.from(e), // UI observes and shows feedback
    ); // preserve, allow retry
    return false;
  }
}
```

Screen reacts to cleared state and self-navigates via existing `onMissing*` hook. No widget-side `.go(context)` chained off awaited future. See [Modal Snapshot Pattern](common-patterns/modals-navigation.md#modal-snapshot-pattern).

## Exception Ownership

Default: catch error once — in notifier. Datasource, repo propagate.

```dart
// Datasource — default: propagate
Future<List<ProductModel>> fetchAll() => _http.get('/products');

// Repository — default: propagate
Future<List<Product>> fetchAll() async {
  final models = await _remote.fetchAll();
  return models.map((m) => m.toEntity()).toList();
}
```

### Legitimate `try/catch` in data layer

Default rule has four narrow exception. Each MUST have reason beyond "log + rethrow":

1. **Domain error translation** — map raw SDK exception to typed domain error so notifier matches on sealed types.
2. **Idempotency recovery** — swallow "already exists" / "not found" on op whose contract is idempotent (e.g. 404 on delete in batch).
3. **Transaction rollback** — catch, run compensating write, rethrow.
4. **Local-first fire-and-forget sync** — remote mirror of local write where caller not await remote. Swallow + log so dead backend no break local path.

❌ WRONG — bare `try { … } catch (e) { log(...); rethrow; }` add nothing. Delete; let notifier catch.

```dart
// ❌ pointless
Future<void> remove(String id) async {
  try {
    await _remote.remove(id);
  } on Exception catch (e, s) {
    Crash.error(e, s, reason: 'remove');
    rethrow;
  }
}

// ✅ propagate
Future<void> remove(String id) => _remote.remove(id);
```

```dart
// Notifier — MUST catch here. Translate to typed AppError; never store raw String.
Future<void> _load() async {
  try {
    final items = await ref.read(productRepositoryProvider).fetchAll();
    if (!ref.mounted) return;
    state = state.copyWith(items: items);
  } on Exception catch (e, s) {
    if (!ref.mounted) return;
    state = state.copyWith(error: AppError.from(e));
    Crash.error(e, s, reason: 'ProductNotifier._load');
  }
}
```

### Domain Error Types

**Rule.** `AppError` = **sole** error type in notifier state. Never store
`String? error` — pattern-match typed error in UI. Catch in notifier, wrap
`AppError.from(e)`, then `Crash.error(e, s, reason: …)`.

```dart
// core/domain/app_error.dart — `from` ctor for notifier wrap
sealed class AppError {
  static AppError from(Object e) => switch (e) {
        SocketException() || TimeoutException() => AppError.network(e.toString()),
        FormatException() => AppError.unexpected(e),
        _ => AppError.unexpected(e),
      };
}
```

Define sealed error hierarchy for typed error handling in notifier:

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

Use in notifier state, pattern-match in UI:

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

Read other provider via `ref`:

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
