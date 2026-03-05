# Riverpod 3.x Codegen

Generate all providers with annotations. Never write providers manually. Never import from `package:riverpod/legacy.dart`.

## Setup

```yaml
# pubspec.yaml
dependencies:
  flutter_riverpod: ^3.2.1
  riverpod_annotation: ^3.0.0

dev_dependencies:
  build_runner: ^2.4.0
  riverpod_generator: ^3.0.0
  riverpod_lint: ^3.0.0
```

Every file with providers needs these:

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'my_file.g.dart';
```

## Generated Provider Names

Riverpod 3.x strips the "Notifier" suffix from class-based provider names:

| Class | Generated Provider |
|---|---|
| `CartNotifier` | `cartProvider` |
| `ProductNotifier` | `productProvider` |
| `AuthNotifier` | `authProvider` |

Functional providers keep their full name:
| Function | Generated Provider |
|---|---|
| `productRepository(Ref)` | `productRepositoryProvider` |
| `cartTotal(Ref)` | `cartTotalProvider` |

Never write `xxxNotifierProvider` — it does not exist in codegen output.

## Provider Types

### keepAlive Providers (long-lived)

For repositories, datasources, services, and feature notifiers:

```dart
// Functional provider — returns a value, lives forever
@Riverpod(keepAlive: true)
ProductRepository productRepository(Ref ref) {
  return ProductRepository(
    ref.read(productRemoteDatasourceProvider),
    ref.read(productLocalDatasourceProvider),
  );
}

// Class-based notifier — manages mutable state, lives forever
@Riverpod(keepAlive: true)
class CartNotifier extends _$CartNotifier {
  @override
  CartState build() => const CartState();

  void addItem(Product product) {
    state = state.copyWith(
      items: [...state.items, product],
    );
  }
}
```

### Auto-dispose Providers (short-lived)

For computed values, one-time fetches, and derived state:

```dart
// Computed value — disposes when no widget watches it
@riverpod
int cartTotal(Ref ref) {
  final items = ref.watch(cartProvider.select((s) => s.items));
  return items.fold(0, (sum, item) => sum + item.price.toInt());
}

// Async fetch — disposes when unused
@riverpod
Future<ProductDetail> productDetail(Ref ref, String id) async {
  final repo = ref.read(productRepositoryProvider);
  return repo.fetchById(id);
}
```

### Family Providers (parameterized)

Codegen handles family automatically through function parameters:

```dart
// Parameters become family args — no FamilyNotifier needed
@riverpod
Future<List<Product>> productsByCategory(Ref ref, String category) async {
  final repo = ref.read(productRepositoryProvider);
  return repo.fetchByCategory(category);
}

// Class-based with parameters
@riverpod
class ProductEditor extends _$ProductEditor {
  @override
  ProductFormState build(String productId) {
    _loadProduct(productId);
    return const ProductFormState();
  }

  Future<void> _loadProduct(String id) async {
    final product = await ref.read(productRepositoryProvider).fetchById(id);
    if (!ref.mounted) return;
    state = state.copyWith(name: product.name, price: product.price);
  }
}
```

### Generic Providers (type parameters)

New in Riverpod 3.0 — generated providers support generics:

```dart
@riverpod
T multiply<T extends num>(Ref ref, T a, T b) {
  return a * b;
}

// Usage
int integer = ref.watch(multiplyProvider<int>(2, 3));
double decimal = ref.watch(multiplyProvider<double>(2.5, 3.5));
```

## Unified Ref

Riverpod 3.0 uses a single `Ref` type. No more `AutoDisposeRef`, `FutureProviderRef`, or generated `ExampleRef`:

```dart
// Riverpod 3.0 — always use Ref
@riverpod
String greeting(Ref ref) => 'Hello';

// NOT: String greeting(GreetingRef ref) — removed in 3.0
```

`Ref` and `WidgetRef` remain separate. `WidgetRef` is for widgets only.

## Automatic Retry

Providers that fail during initialization retry automatically with exponential backoff (200ms initial, doubling up to 6.4s).

Customize globally:

```dart
void main() {
  runApp(
    ProviderScope(
      retry: (retryCount, error) {
        if (error is ProviderException) return null; // Don't retry dependency failures
        if (retryCount > 5) return null;             // Stop after 5 retries
        return Duration(seconds: retryCount * 2);
      },
      child: const MyApp(),
    ),
  );
}
```

Customize per provider:

```dart
@Riverpod(keepAlive: true, retry: myRetryLogic)
Future<Config> appConfig(Ref ref) async {
  return await fetchConfig();
}
```

## ProviderException

Provider errors wrap in `ProviderException`. This distinguishes "provider failed" from "dependency of provider failed":

```dart
try {
  ref.watch(failingProvider);
} on ProviderException catch (e) {
  switch (e.exception) {
    case NetworkError():
      // Handle network error
    default:
      rethrow;
  }
}
```

## Mutations (experimental)

> **Experimental.** This API may change without a major version bump.

Mutations track side-effect state (idle, pending, success, error) separately from provider state. They prevent providers from being disposed while a side-effect runs.

```dart
// Declare a mutation as a top-level variable
final addTodoMutation = Mutation<void>();

// Watch mutation state in UI
class AddTodoButton extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final addTodo = ref.watch(addTodoMutation);

    return switch (addTodo) {
      MutationIdle() => ElevatedButton(
          onPressed: () {
            addTodoMutation.run(ref, (tsx) async {
              // tsx.get keeps the provider alive until mutation completes
              await tsx.get(todoListProvider.notifier).addTodo('New Todo');
            });
          },
          child: const Text('Submit'),
        ),
      MutationPending() => const CircularProgressIndicator(),
      MutationError() => ElevatedButton(
          onPressed: () { /* retry */ },
          child: const Text('Retry'),
        ),
      MutationSuccess() => const Text('Done'),
    };
  }
}
```

Use `tsx.get` instead of `ref.read` inside mutations — it keeps the provider alive until the mutation completes.

## Offline Persistence (experimental)

> **Experimental.** This API may change without a major version bump.

Providers can persist state to a local database. The official package is `riverpod_sqflite`:

```dart
@Riverpod(keepAlive: true)
class TodosNotifier extends _$TodosNotifier {
  @override
  Future<List<Todo>> build() async {
    persist(
      ref.watch(storageProvider.future),
      key: 'todos',
      encode: jsonEncode,
      decode: (json) {
        final decoded = jsonDecode(json) as List;
        return decoded.map((e) => Todo.fromJson(e as Map<String, Object?>)).toList();
      },
    );

    return await fetchTodos();
  }
}
```

During the `await`, the persisted value is shown. After the network response, server state takes precedence.

## Pause/Resume

Riverpod 3.0 pauses providers when their listeners are not visible:

- Widgets off-screen (based on `TickerMode`) pause their providers
- If a provider is only used by paused providers, it pauses too
- When a provider rebuilds, previous subscriptions stay until rebuild completes

This saves resources. A websocket provider pauses when its screen is not visible.

Override pause behavior:

```dart
TickerMode(
  enabled: false, // pause listeners
  child: Consumer(
    builder: (context, ref, child) {
      final value = ref.watch(myProvider); // paused
      return Text(value.toString());
    },
  ),
)
```

## Weak Listeners

Listen without preventing auto-dispose:

```dart
ref.listen(
  anotherProvider,
  weak: true,
  (previous, next) {
    // Provider can still dispose even though we're listening
  },
);
```

## Lifecycle Listeners Return Unsubscribe Functions

```dart
final removeListener = ref.onDispose(() => print('disposed'));
// Call to remove:
removeListener();
```

## Scoping (codegen only)

Scoped providers declare `dependencies: []` and require an override before use:

```dart
@Riverpod(dependencies: [])
Future<int> scopedValue(Ref ref) => throw UnimplementedError();

// Must override before use
ProviderScope(
  overrides: [
    scopedValueProvider.overrideWithValue(const AsyncValue.data(42)),
  ],
  child: const MyWidget(),
)
```

Use `@Dependencies([scopedValue])` on widgets that consume scoped providers. The lint rule catches missing overrides at compile time.
