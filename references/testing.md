# Testing

## Trigger

Signals: ProviderContainer.test, UncontrolledProviderScope, mocktail, widget tests, event contract
Before generating code in this area, output verbatim: `Reading: testing.md`


## Contents

- [Rules — NEVER Violate](#rules--never-violate)
- [Setup](#setup)
- [Mock Declaration](#mock-declaration)
- [ProviderContainer.test](#providercontainertest)
- [Test Helper SSOT](#test-helper-ssot)
- [Cross-Runtime Contract Drift Tests](#cross-runtime-contract-drift-tests)
- [overrideWithBuild](#overridewithbuild)
- [overrideWithValue for Async Providers](#overridewithvalue-for-async-providers)
- [Widget Tests](#widget-tests)
- [Widget Key Registry](#widget-key-registry)
- [WidgetTester.container](#widgettestercontainer)
- [Testing Notifier Methods](#testing-notifier-methods)
- [Event Contract and Sync Tests](#event-contract-and-sync-tests)
- [Testing Repository Layer](#testing-repository-layer)
- [Testing Union States](#testing-union-states)
- [Common Pitfalls](#common-pitfalls)

## Rules — NEVER Violate

1. **MUST** mock interfaces (`IProductRepository`), NEVER concrete (`ProductRepository`).
2. **MUST** use `ProviderContainer.test()` — NEVER manual `createContainer`.
3. **MUST** use `UncontrolledProviderScope` widget tests — NEVER raw `ProviderScope` w/ overrides.
4. **MUST** prefer explicit `pump()`. `pumpAndSettle(timeout: ...)` only finite anim/async; avoid infinite/ticking.
5. **MUST** override repo/datasource level — NEVER mock notifiers direct.
6. **MUST** use deterministic `ValueKey` selectors from a central key registry for repeated icons, draggable sheets, close/open actions. NEVER use inline string keys, `tapAt(...)`, first-match icon finders, or case-sensitive label text.
7. **MUST** add event-contract tests for streams/realtime/push/sync/shared remote state: exact subscriptions/listeners, every event family, notifier reaction, stale-source refresh, and removal/delete behavior.
8. **MUST** keep shared fakes, mocks, provider-container factories, platform stubs, and async wait helpers in a test helper SSOT.
9. **MUST** add contract drift tests when constants/schema/field IDs are copied across Flutter/backend/functions/native runtimes.

```mermaid
graph LR
  subgraph "Test Targets by Layer"
    U[Unit Tests] -->|mock interfaces| R[Repositories]
    U -->|mock repos| N[Notifiers]
    W[Widget Tests] -->|override repos| S[Screens]
    W -->|UncontrolledProviderScope| C[ProviderContainer.test]
  end
```

## Setup

```yaml
# pubspec.yaml
dev_dependencies:
  flutter_test:
    sdk: flutter
  mocktail: ^1.0.5
  build_runner: ^2.15.0
```

## Mock Declaration

No codegen. Declare mocks file top:

```dart
import 'package:mocktail/mocktail.dart';

class MockIProductRepository extends Mock implements IProductRepository {}
class MockIAuthRepository extends Mock implements IAuthRepository {}
```

Non-nullable arg matchers → register fallback once `setUpAll`:

```dart
setUpAll(() => registerFallbackValue(const Product(id: '', name: '', price: 0)));
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

Auto-dispose each test:

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('fetches products on init', () async {
    final mockRepo = MockIProductRepository();
    when(() => mockRepo.fetchAll()).thenAnswer((_) async => [
      const Product(id: '1', name: 'Widget', price: 9.99),
    ]);

    final container = ProviderContainer.test(
      overrides: [
        productRepositoryProvider.overrideWithValue(mockRepo),
      ],
    );

    // Trigger build() and flush the deferred Future.microtask(_load) call.
    // `.future` only exists on AsyncNotifier — for sync Notifier with
    // microtask-deferred load, pump the microtask queue instead.
    container.read(productProvider);
    await Future<void>.microtask(() {});

    final state = container.read(productProvider);
    expect(state.items, hasLength(1));
    expect(state.items.first.name, 'Widget');
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
      counterProvider.overrideWithBuild((ref) => 42),
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
        AsyncValue.data(const User(id: '1', name: 'Test')),
      ),
    ],
  );

  final user = container.read(userProvider);
  expect(user.value?.name, 'Test');
});
```

## Widget Tests

`UncontrolledProviderScope` inject container:

```dart
testWidgets('shows product list', (tester) async {
  final mockRepo = MockIProductRepository();
  when(() => mockRepo.fetchAll()).thenAnswer((_) async => [
    const Product(id: '1', name: 'Widget', price: 9.99),
    const Product(id: '2', name: 'Gadget', price: 19.99),
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

  // Prefer explicit frames: trigger + advance through animation.
  // For route transitions, avoid hardcoded durations when possible.
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
IconButton(
  key: const ValueKey(AppWidgetKeys.productCloseButton),
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

## WidgetTester.container

Access `ProviderContainer` from widget tests:

```dart
testWidgets('can access container', (tester) async {
  await tester.pumpWidget(
    const ProviderScope(child: MaterialApp(home: MyWidget())),
  );

  final container = tester.container();
  expect(container.read(myProvider), someValue);
});
```

## Testing Notifier Methods

```dart
test('deleteItem removes from state', () async {
  final mockRepo = MockIProductRepository();
  when(() => mockRepo.fetchAll()).thenAnswer((_) async => [
    const Product(id: '1', name: 'A', price: 10),
    const Product(id: '2', name: 'B', price: 20),
  ]);
  when(() => mockRepo.delete(any())).thenAnswer((_) async {});

  final container = ProviderContainer.test(
    overrides: [
      productRepositoryProvider.overrideWithValue(mockRepo),
    ],
  );

  // Wait for initial load (sync Notifier with deferred microtask load)
  container.read(productProvider);
  await Future<void>.microtask(() {});

  // Delete and verify
  await container.read(productProvider.notifier).deleteItem('1');

  final state = container.read(productProvider);
  expect(state.items, hasLength(1));
  expect(state.items.first.id, '2');
});
```

## Event Contract and Sync Tests

Any stream, realtime, push, subscription, callback, poller, cache invalidation, or source-of-truth refresh path needs tests at two levels:

1. Datasource/service contract test: proves the exact channel/topic/query/filter/listener set is registered.
2. Notifier/widget reaction test: emits representative events and proves state updates, refetches, or clears correctly.

Do not test only the happy create event. Cover the event families the product depends on:

- create/add/join
- update/rename/status/order
- delete/remove/leave/revoke
- generated/regenerated values
- permission/ownership changes
- stale, partial, duplicate, out-of-order, and unrelated events

Minimum contract:

```dart
test('subscribes to every event family needed for item sync', () async {
  final source = FakeRemoteEventSource();
  final datasource = ProductRemoteDatasource(source);

  await datasource.watchProducts(ownerId: 'owner-1').first;

  expect(source.subscriptions, contains('products.owner-1.create'));
  expect(source.subscriptions, contains('products.owner-1.update'));
  expect(source.subscriptions, contains('products.owner-1.delete'));
});
```

Minimum notifier reaction:

```dart
test('refetches source of truth after remote update event', () async {
  final repo = FakeProductRepository()
    ..items = [const Product(id: 'p1', name: 'Old')];
  final events = FakeProductEvents();

  final container = ProviderContainer.test(
    overrides: [
      productRepositoryProvider.overrideWithValue(repo),
      productEventsProvider.overrideWithValue(events),
    ],
  );

  container.read(productProvider);
  await Future<void>.microtask(() {});

  repo.items = [const Product(id: 'p1', name: 'New')];
  events.emit(const ProductEvent.updated(id: 'p1'));
  await Future<void>.microtask(() {});

  expect(container.read(productProvider).items.single.name, 'New');
});
```

Generated values and read-your-writes:

- If create/update/delete can return stale, partial, or derived values, assert the notifier refreshes from the source of truth before success UI/navigation.
- If a code/token/link/slug/order/index is generated remotely, mutate it in the fake source first, then assert UI/notifier state eventually shows that exact generated value.
- If a selected item is deleted or the actor loses access, assert selected state clears and the list/detail route falls back without throwing.

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
  expect(result.first.name, 'Test');
  expect(result.first, isA<Product>()); // Entity, not Model
  verify(() => mockRemote.fetchAll()).called(1);
});

test('falls back to cache on error', () async {
  final mockRemote = MockIProductRemoteDatasource();
  final mockLocal = MockIProductLocalDatasource();

  when(() => mockRemote.fetchAll()).thenThrow(Exception('Network error'));
  when(() => mockLocal.getAll()).thenAnswer((_) async => [
    const ProductModel(id: '1', name: 'Cached', price: 5.00),
  ]);

  final repo = ProductRepository(mockRemote, mockLocal);
  final result = await repo.fetchAll();

  expect(result.first.name, 'Cached');
  verify(() => mockLocal.getAll()).called(1);
});
```

## Testing Union States

```dart
test('auth state transitions', () async {
  final mockAuth = MockIAuthRepository();
  when(() => mockAuth.getSession()).thenAnswer(
    (_) async => const User(id: '1', name: 'Test'),
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
  await Future<void>.microtask(() {});

  final state = container.read(authProvider);
  expect(state, isA<Authenticated>());

  // Pattern match to verify user
  if (state case Authenticated(:final user)) {
    expect(user.name, 'Test');
  }
});
```

## Common Pitfalls

| Problem | Solution |
|---------|----------|
| `pumpAndSettle` hangs | Explicit `pump()` + bounded `pump(Duration(...))`; `pumpAndSettle(timeout: ...)` finite anim only |
| State not updated after async | `await provider.future` (AsyncValue) or `await Future.microtask(() {})` sealed-state |
| Provider not found | Wrap `UncontrolledProviderScope` |
| Mock not applied | Verify override matches provider type |
| Container disposed early | `ProviderContainer.test()` — auto-manages |
| Inline `ValueKey('close')` strings drift from E2E | Put key strings in `AppWidgetKeys`, use constants in widgets/tests |
| Realtime join/create not observed | Contract-test exact event families plus notifier reaction test for emitted event |
| Delete/remove leaves stale detail UI | Emit delete/remove event and assert selected state clears or route fallback appears |
| Generated code/token stale after mutation | Fake source generates new value; notifier must refetch and expose source-of-truth value |
| Event test passes but real app does not sync | Add writer/observer Dart MCP E2E from [dart-mcp-e2e-testing.md](dart-mcp-e2e-testing.md) |

## Recap

1. MUST mock interfaces (`IProductRepository`), NEVER concrete implementations.
2. MUST use `ProviderContainer.test()` — NEVER manual `createContainer`. Manual containers leak between tests and corrupt subsequent test state.
3. MUST use `UncontrolledProviderScope` in widget tests — NEVER raw `ProviderScope` with overrides. Raw `ProviderScope` creates its own container and ignores the test container's overrides.

