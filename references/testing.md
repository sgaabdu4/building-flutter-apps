# Testing

Test utilities for Riverpod 3.x with `ProviderContainer.test()`.

## Setup

```yaml
# pubspec.yaml
dev_dependencies:
  flutter_test:
    sdk: flutter
  mockito: ^5.4.0
  build_runner: ^2.4.0
```

## Mock Generation

Use `@GenerateMocks` to generate mocks. Run `dart run build_runner build -d` after adding annotations:

```dart
import 'package:mockito/annotations.dart';
import 'package:mockito/mockito.dart';

@GenerateMocks([ProductRepository, AuthRepository])
import 'product_notifier_test.mocks.dart';
```

**Fake vs Mock** — Use mocks (Mockito) when you need to verify interactions (`verify`, `when`). Use fakes (manual subclass) when you need working implementations with controlled behavior:

```dart
// Fake: real behavior, controlled output
class FakeProductRepository extends Fake implements ProductRepository {
  List<Product> items = [];

  @override
  Future<List<Product>> fetchAll() async => items;
}

// Mock: verify calls + stub returns
final mock = MockProductRepository();
when(mock.fetchAll()).thenAnswer((_) async => [product]);
verify(mock.fetchAll()).called(1);
```

## ProviderContainer.test

Replaces the manual `createContainer` pattern. Auto-disposes after each test:

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('fetches products on init', () async {
    final mockRepo = MockProductRepository();
    when(mockRepo.fetchAll()).thenAnswer((_) async => [
      const Product(id: '1', name: 'Widget', price: 9.99),
    ]);

    final container = ProviderContainer.test(
      overrides: [
        productRepositoryProvider.overrideWithValue(mockRepo),
      ],
    );

    // Read the notifier to trigger build()
    container.read(productProvider);

    // Wait for async operations
    await Future.delayed(const Duration(milliseconds: 100));

    final state = container.read(productProvider);
    expect(state.items, hasLength(1));
    expect(state.items.first.name, 'Widget');
    verify(mockRepo.fetchAll()).called(1);
  });
}
```

## overrideWithBuild

Mock only the `build()` method while keeping the notifier's methods intact:

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

Use `UncontrolledProviderScope` to inject a container:

```dart
testWidgets('shows product list', (tester) async {
  final mockRepo = MockProductRepository();
  when(mockRepo.fetchAll()).thenAnswer((_) async => [
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

  // Use pump(), not pumpAndSettle() — avoids hangs with looping animations
  await tester.pump(const Duration(milliseconds: 300));

  expect(find.text('Widget'), findsOneWidget);
  expect(find.text('Gadget'), findsOneWidget);
});
```

## WidgetTester.container

Access the `ProviderContainer` from widget tests:

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
  final mockRepo = MockProductRepository();
  when(mockRepo.fetchAll()).thenAnswer((_) async => [
    const Product(id: '1', name: 'A', price: 10),
    const Product(id: '2', name: 'B', price: 20),
  ]);
  when(mockRepo.delete('1')).thenAnswer((_) async {});

  final container = ProviderContainer.test(
    overrides: [
      productRepositoryProvider.overrideWithValue(mockRepo),
    ],
  );

  // Wait for initial load
  container.read(productProvider);
  await Future.delayed(const Duration(milliseconds: 100));

  // Delete and verify
  await container.read(productProvider.notifier).deleteItem('1');
  await Future.delayed(const Duration(milliseconds: 100));

  final state = container.read(productProvider);
  expect(state.items, hasLength(1));
  expect(state.items.first.id, '2');
});
```

## Testing Repository Layer

```dart
test('fetchAll returns entities from remote', () async {
  final mockRemote = MockProductRemoteDatasource();
  final mockLocal = MockProductLocalDatasource();

  when(mockRemote.fetchAll()).thenAnswer((_) async => [
    const ProductModel(id: '1', name: 'Test', price: 9.99),
  ]);

  final repo = ProductRepository(mockRemote, mockLocal);
  final result = await repo.fetchAll();

  expect(result, hasLength(1));
  expect(result.first.name, 'Test');
  expect(result.first, isA<Product>()); // Entity, not Model
  verify(mockRemote.fetchAll()).called(1);
});

test('falls back to cache on error', () async {
  final mockRemote = MockProductRemoteDatasource();
  final mockLocal = MockProductLocalDatasource();

  when(mockRemote.fetchAll()).thenThrow(Exception('Network error'));
  when(mockLocal.getAll()).thenAnswer((_) async => [
    const ProductModel(id: '1', name: 'Cached', price: 5.00),
  ]);

  final repo = ProductRepository(mockRemote, mockLocal);
  final result = await repo.fetchAll();

  expect(result.first.name, 'Cached');
  verify(mockLocal.getAll()).called(1);
});
```

## Testing Union States

```dart
test('auth state transitions', () async {
  final mockAuth = MockAuthRepository();
  when(mockAuth.getSession()).thenAnswer(
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
  await Future.delayed(const Duration(milliseconds: 100));

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
| `pumpAndSettle` hangs | Use `pump(Duration(...))` instead |
| State not updated after async | Add `await Future.delayed(...)` |
| Provider not found | Wrap in `UncontrolledProviderScope` |
| Mock not applied | Verify override matches provider type |
| Container disposed early | Use `ProviderContainer.test()` — auto-manages |
