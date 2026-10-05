# Testing


## Read first

1. Mock interfaces, never concrete implementations.
2. Unit tests use `ProviderContainer.test()`; widget tests use `UncontrolledProviderScope`.
3. Override repo/datasource providers, not notifiers directly.
4. Prefer explicit `pump()`; `pumpAndSettle` only for finite anim/async.
5. Selectors use central deterministic `AppWidgetKeys`; no inline keys, `tapAt`, first icon, case-sensitive labels.
6. Add contract drift tests for copied constants/schema/field IDs across runtimes.
7. Treat clean-install and preserved-restart tests as separate cases, with the
   state recorded in the test receipt.

## Trigger

Signals: ProviderContainer.test, UncontrolledProviderScope, mocktail, widget tests, event contract


## Rules

1. Mock interfaces (`IProductRepository`), not concrete classes (`ProductRepository`) → doubles honour the provider's contract; implementation changes do not break tests.
2. Containers = `ProviderContainer.test()`, not manual `createContainer` → disposed automatically when the test ends.
3. Widget tests pass that container through `UncontrolledProviderScope`, not a raw `ProviderScope` with overrides → unit and widget tests share one container/override setup, and the test holds the container before the first pump.
4. Prefer explicit `pump()`. `pumpAndSettle` = finite animation/async only, bounded with the positional timeout (`pumpAndSettle(const Duration(milliseconds: 100), .sendSemanticsUpdate, const Duration(seconds: 5))`) → an unbounded settle hangs on infinite/ticking animation.
5. Override repository/datasource providers, not notifiers → the notifier's real state logic stays under test.
6. Repeated icons, draggable sheets and close/open actions = deterministic `ValueKey` selectors from the central key registry; no inline string keys, `tapAt(...)`, first-match icon finders or case-sensitive label text → those break on layout, order or copy changes and drift from E2E.
7. Streams/realtime/push/sync/shared remote state = reaction test per event family the feature consumes → assert resulting notifier state or visible UI (update, stale-source refresh, removal/delete fallback). Datasource/service test asserts the registered subscription/channel/filter set → injected-event reaction tests cannot catch missing or wrong wiring; names shared with another runtime also get a drift test (rule 9). See [Event Contract and Sync Tests](#event-contract-and-sync-tests).
8. Shared fakes, mocks, provider-container factories, platform stubs and async wait helpers = one test helper SSOT → one fix reaches every test.
9. Constants/schema/field IDs copied across Flutter/backend/functions/native runtimes = contract drift test → a one-sided rename fails a test, not production.
10. Pause-sensitive provider startup/projections, transient mode-error clearing and native-link contracts, when present = regression tests from the [lifecycle regression matrix](#lifecycle-regression-matrix) → these fail silently (lost first update, stale error, drifted link).
11. Before reusing a modal key for a new modal, wait for the old key to be absent → otherwise the closing route satisfies the next finder.
12. File picker, permission prompt, keyboard, share sheet or platform-channel behaviour = test through the real platform wrapper → a widget mock proves only the Flutter side.

## Setup

```yaml
# pubspec.yaml
dev_dependencies:
  flutter_test:
    sdk: flutter
  mocktail: ^1.0.5
  build_runner: <version>
```

Resolve `<version>` from [core-stack.md](core-stack.md); do not duplicate its pin here.

## Mock Declaration

No codegen. Declare mocks file top:

```dart
import 'package:mocktail/mocktail.dart';

class MockIProductRepository extends Mock implements IProductRepository {}
class MockIAuthRepository extends Mock implements IAuthRepository {}
```

Non-nullable arg matchers → register fallback once `setUpAll`:

```dart
setUpAll(
  () => registerFallbackValue(
    Product(id: ProductId('fallback'), name: DisplayName('Fallback'), price: .usd(0)),
  ),
);
```

**Fake vs Mock** — Mocks (Mocktail) for interaction verify (`verify`, `when`). Fakes (manual subclass) for working impls w/ controlled behavior:

```dart
// Fake: real behavior, controlled output
class FakeProductRepository extends Fake implements IProductRepository {
  List<Product> items = [];

  @override
  Future<List<Product>> fetchAll() async => items;
}

// Mock: stub + verify with closure syntax
final mock = MockIProductRepository();
when(() => mock.fetchAll()).thenAnswer((_) async => [product]);
verify(() => mock.fetchAll()).called(1);
```

## ProviderContainer.test

Auto-dispose each test. Sync `Notifier` with deferred `_load` has no `.future` → read the provider, then `await pumpEventQueue()` to drain the load and its awaited repository call; one microtask is not enough.

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('fetches products on init', () async {
    final mockRepo = MockIProductRepository();
    when(() => mockRepo.fetchAll()).thenAnswer((_) async => [
      Product(id: ProductId('1'), name: DisplayName('Widget'), price: .usd(9.99)),
    ]);

    final container = ProviderContainer.test(
      overrides: [
        productRepositoryProvider.overrideWithValue(mockRepo),
      ],
    );

    container.read(productProvider);
    await pumpEventQueue();

    final state = container.read(productProvider);
    expect(state.items, hasLength(1));
    expect(state.items.first.name.value, 'Widget');
    verify(() => mockRepo.fetchAll()).called(1);
  });
}
```

## Test Helper SSOT

Prefer one shared helper module:

```text
test/helpers/test_fakes.dart
```

It owns:

- `createTestContainer(...)`
- fake services and repositories
- mock classes for interfaces
- mocktail fallback registration
- platform stubs
- async provider wait helpers
- local database setup/teardown helpers

Do not redefine common fakes in every test file. Feature-specific fakes may live next to that feature only when they are not useful elsewhere.

## Cross-Runtime Contract Drift Tests

If Flutter shares constants with another runtime, test the contract:

- table/collection/bucket/function IDs
- field names and relationship names
- enum/string wire values
- manifest/schema/index requirements
- copied shared source files
- platform channel method names
- deep-link path contracts

Generic pattern:

```dart
test('app and backend table ids stay in sync', () {
  expect(AppTableIds.workouts, BackendTableIds.workouts);
  expect(AppFields.userId, BackendFields.userId);
});
```

Keep backend-vendor details in that backend skill. The Flutter rule is: copied runtime contracts need drift tests.

## overrideWithBuild

Mock `build()` only, keep notifier methods intact:

```dart
test('increment works with custom initial state', () {
  final container = ProviderContainer.test(
    overrides: [
      counterProvider.overrideWithBuild((_, _) => 42),
    ],
  );

  expect(container.read(counterProvider), 42);

  // Original increment method still works
  container.read(counterProvider.notifier).increment();
  expect(container.read(counterProvider), 43);
});
```

## overrideWithValue for Async Providers

```dart
test('handles pre-loaded async data', () {
  final container = ProviderContainer.test(
    overrides: [
      userProvider.overrideWithValue(
        .data(User(id: UserId('1'), name: DisplayName('Test'))),
      ),
    ],
  );

  final user = container.read(userProvider);
  expect(user.value?.name.value, 'Test');
});
```

## Widget Tests

`UncontrolledProviderScope` inject container. Explicit frames = trigger + advance through the animation; route transitions avoid hardcoded durations when possible.

```dart
testWidgets('shows product list', (tester) async {
  final mockRepo = MockIProductRepository();
  when(() => mockRepo.fetchAll()).thenAnswer((_) async => [
    Product(id: ProductId('1'), name: DisplayName('Widget'), price: .usd(9.99)),
    Product(id: ProductId('2'), name: DisplayName('Gadget'), price: .usd(19.99)),
  ]);

  final container = ProviderContainer.test(
    overrides: [
      productRepositoryProvider.overrideWithValue(mockRepo),
    ],
  );

  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: ProductListScreen()),
    ),
  );

  await tester.pump();
  await tester.pump(const Duration(milliseconds: 300));

  expect(find.text('Widget'), findsOneWidget);
  expect(find.text('Gadget'), findsOneWidget);
});
```

## Widget Key Registry

Default file: `lib/core/testing/app_widget_keys.dart`. Use existing project equivalent if present.

```dart
abstract final class AppWidgetKeys {
  static const productCloseButton = 'product.close.button';
  static const productSaveButton = 'product.save.button';
}
```

Widgets:

```dart
final l10n = context.l10n;

IconButton(
  key: const ValueKey(AppWidgetKeys.productCloseButton),
  tooltip: l10n.closeProductTooltip,
  onPressed: onClose,
  icon: const Icon(Icons.close),
)
```

Tests/E2E:

```dart
await tester.tap(find.byKey(const ValueKey(AppWidgetKeys.productCloseButton)));
```

Rules:

- One registry file per app unless the project already has a namespaced equivalent.
- Prefer feature-prefixed names: `profile.avatar.edit`, `checkout.payment.submit`.
- No inline `ValueKey('...')` in widgets or tests.
- Add keys only to real interaction/inspection targets, not every widget.
- Storage keys and API paths use the sibling registries `StorageKeys` / `ApiPaths` in `lib/core/constants/` ([architecture.md](architecture.md#key-registries)).

## WidgetTester.container

Access `ProviderContainer` from widget tests:

```dart
testWidgets('can access container', (tester) async {
  final container = ProviderContainer.test();
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: MyWidget()),
    ),
  );

  expect(tester.container(), same(container));
  expect(container.read(myProvider), someValue);
});
```

## Testing Notifier Methods

```dart
test('deleteItem removes from state', () async {
  final mockRepo = MockIProductRepository();
  when(() => mockRepo.fetchAll()).thenAnswer((_) async => [
    Product(id: ProductId('1'), name: DisplayName('A'), price: .usd(10)),
    Product(id: ProductId('2'), name: DisplayName('B'), price: .usd(20)),
  ]);
  when(() => mockRepo.delete(any())).thenAnswer((_) async {});

  final container = ProviderContainer.test(
    overrides: [
      productRepositoryProvider.overrideWithValue(mockRepo),
    ],
  );

  // Wait for initial load (sync Notifier with deferred load)
  container.read(productProvider);
  await pumpEventQueue();

  // Delete and verify
  await container.read(productProvider.notifier).deleteItem('1');

  final state = container.read(productProvider);
  expect(state.items, hasLength(1));
  expect(state.items.first.id.value, '2');
});
```

## Event Contract and Sync Tests

Stream, realtime, push, subscription, callback, poller, cache-invalidation or source-of-truth refresh path = notifier/widget reaction test: emit a representative event → assert the resulting state or visible UI (update, refetch, clear/fallback).

Cover each event family the feature consumes; skip families it does not:

- create/add/join
- update/rename/status/order
- delete/remove/leave/revoke
- generated/regenerated values
- permission/ownership changes
- stale, partial, duplicate, out-of-order or unrelated events the feature must reconcile or ignore

Datasource/service wiring test = assert the registered channel/topic/filter/listener set → the reaction test injects events, so it passes even when the real subscription is missing or wrong. Names shared with another runtime also get a contract drift test (rule 9):

```dart
test('subscribes to every product event family', () async {
  final source = FakeRemoteEventSource();
  final datasource = ProductRemoteDatasource(source);

  await datasource.watchProducts(ownerId: 'owner-1').first;

  expect(source.subscriptions, contains('products.owner-1.create'));
  expect(source.subscriptions, contains('products.owner-1.update'));
  expect(source.subscriptions, contains('products.owner-1.delete'));
});
```

Notifier reaction:

```dart
test('refetches source of truth after remote update event', () async {
  final repo = FakeProductRepository()
    ..items = [Product(id: ProductId('p1'), name: DisplayName('Old'), price: .usd(1))];
  final events = FakeProductEventSource();

  final container = ProviderContainer.test(
    overrides: [
      productRepositoryProvider.overrideWithValue(repo),
      productEventSourceProvider.overrideWithValue(events),
    ],
  );

  container.read(productProvider);
  await pumpEventQueue();

  repo.items = [Product(id: ProductId('p1'), name: DisplayName('New'), price: .usd(1))];
  events.emit(const .updated(id: 'p1'));
  await pumpEventQueue();

  expect(container.read(productProvider).items.single.name.value, 'New');
});
```

Generated values and read-your-writes:

- If create/update/delete can return stale, partial, or derived values, assert the notifier refreshes from the source of truth before success UI/navigation.
- If a code/token/link/slug/order/index is generated remotely, mutate it in the fake source first, then assert UI/notifier state eventually shows that exact generated value.
- If a selected item is deleted or the actor loses access, assert selected state clears and the list/detail route falls back without throwing.

## Lifecycle regression matrix

| Risk | Required red-capable proof |
|---|---|
| Async startup before listener ownership | Register durable owner/listener, start once, and assert the first result appears once |
| Route covered or provider listener paused | Emit the first update while covered, resume, and assert current state/pending event is not lost |
| Computed-provider chain | Compare direct base-provider projection and fail if pause/resume misses the first update |
| Login/signup/reset mode change | Seed a server/validation error, switch mode, and assert error + pending state clear |
| Native/custom link drift | Build URI from producer contract and parse through the Flutter typed-route ingress for Android + iOS fixtures |
| E2E harness false positive | Unknown scenario fails; critical log fails; screenshot is taken only after asserted target state |
| Modal key reuse | Close the old modal, wait for its key to be absent, open the new modal, and assert the new route state |
| Native prompt boundary | Complete the platform prompt and assert the returned app state, not only a widget-tree change |

## Testing Repository Layer

```dart
test('fetchAll returns entities from remote', () async {
  final mockRemote = MockIProductRemoteDatasource();
  final mockLocal = MockIProductLocalDatasource();

  when(() => mockRemote.fetchAll()).thenAnswer((_) async => [
    const ProductModel(id: '1', name: 'Test', price: 9.99),
  ]);

  final repo = ProductRepository(mockRemote, mockLocal);
  final result = await repo.fetchAll();

  expect(result, hasLength(1));
  expect(result.first.name.value, 'Test');
  expect(result.first, isA<Product>()); // Entity, not Model
  verify(() => mockRemote.fetchAll()).called(1);
});

test('falls back to cache when offline', () async {
  final mockRemote = MockIProductRemoteDatasource();
  final mockLocal = MockIProductLocalDatasource();

  when(() => mockRemote.fetchAll()).thenThrow(const SocketException('offline'));
  when(() => mockLocal.getAll()).thenAnswer((_) async => [
    const ProductModel(id: '1', name: 'Cached', price: 5.00),
  ]);

  final repo = ProductRepository(mockRemote, mockLocal);
  final result = await repo.fetchAll();

  expect(result.first.name.value, 'Cached');
  verify(() => mockLocal.getAll()).called(1);
});
```

## Testing Union States

```dart
test('auth state transitions', () async {
  final mockAuth = MockIAuthRepository();
  when(() => mockAuth.getSession()).thenAnswer(
    (_) async => User(id: UserId('1'), name: DisplayName('Test')),
  );

  final container = ProviderContainer.test(
    overrides: [
      authRepositoryProvider.overrideWithValue(mockAuth),
    ],
  );

  // Initial state is loading
  final initial = container.read(authProvider);
  expect(initial, isA<AuthLoading>());

  // Wait for session check
  await pumpEventQueue();

  final state = container.read(authProvider);
  expect(state, isA<Authenticated>());

  // Pattern match to verify user
  if (state case Authenticated(:final user)) {
    expect(user.name.value, 'Test');
  }
});
```

## Common Pitfalls

| Issue | Fix |
|-------|-----|
| `pumpAndSettle` hangs | Explicit `pump()` + bounded `pump(Duration(...))`; `pumpAndSettle` with positional timeout (rule 4) finite anim only |
| State not updated after async | `await provider.future` (AsyncValue) or `await pumpEventQueue()` sealed-state |
| Provider not found | Wrap `UncontrolledProviderScope` |
| Mock not applied | Verify override matches provider type |
| Container disposed early | `ProviderContainer.test()` — auto-manages |
| Inline `ValueKey('close')` strings drift from E2E | Put key strings in `AppWidgetKeys`, use constants in widgets/tests |
| Realtime join/create not observed | Emit the join/create event the feature consumes; assert the resulting state or visible UI |
| Delete/remove leaves stale detail UI | Emit delete/remove event and assert selected state clears or route fallback appears |
| Generated code/token stale after mutation | Fake source generates new value; notifier must refetch and expose source-of-truth value |
| Event test passes but real app does not sync | Add writer/observer Dart MCP E2E from [dart-mcp-e2e-testing.md](dart-mcp-e2e-testing.md) |
