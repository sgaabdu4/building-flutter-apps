# Performance

Widget rebuild optimization, provider watching strategy, and memory management. For Flutter-specific rendering, animations, slivers, isolates, and app size techniques, see [flutter-optimizations.md](flutter-optimizations.md).

## Widget Rebuild Rules

### Watch in Leaf Widgets

Watch providers in the smallest widget possible. Never watch in a parent and pass data down:

```dart
// WRONG — parent rebuilds all children
class ParentWidget extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(userProvider);
    return Column(children: [
      UserName(name: user.name),   // prop drilling
      UserEmail(email: user.email),
    ]);
  }
}

// RIGHT — each child watches only what it needs
class UserName extends ConsumerWidget {
  const UserName({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final name = ref.watch(
      userProvider.select((s) => s.name),
    );
    return Text(name);
  }
}
```

### Use .select() to Watch Specific Fields

`select` prevents rebuilds when unrelated fields change:

```dart
// Rebuilds only when items change, not when isLoading or error change
final items = ref.watch(
  productProvider.select((s) => s.items),
);

// Watch multiple fields with a record
final (:isLoading, :error) = ref.watch(
  productProvider.select((s) => (isLoading: s.isLoading, error: s.error)),
);
```

### Extract Widget Classes, Not Helper Methods

```dart
// WRONG — helper method creates new function scope, no optimization
Widget _buildHeader() => Container(...);

// RIGHT — widget class supports const, separate build context
class HeaderWidget extends StatelessWidget {
  const HeaderWidget({super.key});

  @override
  Widget build(BuildContext context) => Container(...);
}
```

### Use const Constructors

```dart
// WRONG — allocates new object on every parent rebuild
return Padding(padding: EdgeInsets.all(16), child: child);

// RIGHT — reuses existing object
return const Padding(padding: EdgeInsets.all(16), child: child);
```

## Provider Lifecycle

### keepAlive vs Auto-Dispose

| `@Riverpod(keepAlive: true)` | `@riverpod` |
|------------------------------|-------------|
| Repositories, datasources, services | Computed values, derived data |
| Feature notifiers | One-time fetches |
| Lives until app terminates | Disposes when no widget watches |

### Equality Filtering

Riverpod 3.0 uses `==` for all notification filtering. Freezed classes generate `==` automatically.

If a provider produces large objects that override `==`, consider the performance cost. Override `updateShouldNotify` to use `identical` for large state:

```dart
@override
bool updateShouldNotify(ProductState previous, ProductState next) {
  return !identical(previous, next);
}
```

## Memory Management

### Clean Up Resources

```dart
@Riverpod(keepAlive: true)
class StreamNotifier extends _$StreamNotifier {
  @override
  StreamState build() {
    final subscription = ref
        .read(streamServiceProvider)
        .stream
        .listen((data) {
          if (!ref.mounted) return;
          state = state.copyWith(data: data);
        });

    ref.onDispose(() => subscription.cancel());

    return const StreamState();
  }
}
```

### Avoid Holding Large Objects

```dart
// WRONG — holds full response in state
state = state.copyWith(rawJson: hugeJsonMap);

// RIGHT — extract only needed fields
state = state.copyWith(
  items: parseItems(hugeJsonMap),
  total: hugeJsonMap['total'] as int,
);
```

## ListView Optimization

### Use ListView.builder

```dart
// WRONG — builds all items at once
ListView(children: items.map((i) => ItemWidget(i)).toList())

// RIGHT — builds only visible items
ListView.builder(
  itemCount: items.length,
  itemBuilder: (context, index) => ItemWidget(items[index]),
)
```

### Use itemExtent When Heights Are Fixed

```dart
ListView.builder(
  itemExtent: 72.0, // fixed height — skips layout calculation
  itemCount: items.length,
  itemBuilder: (context, index) => ItemTile(items[index]),
)
```

## Image Optimization

```dart
// Cache network images
Image.network(
  url,
  cacheWidth: 200,  // decode at display size, not full resolution
  cacheHeight: 200,
)

// Use FadeInImage for smooth loading
FadeInImage.memoryNetwork(
  placeholder: kTransparentImage,
  image: url,
)
```

## Avoid Expensive Operations in build()

```dart
// WRONG — sorts on every rebuild
@override
Widget build(BuildContext context, WidgetRef ref) {
  final items = ref.watch(productProvider.select((s) => s.items));
  final sorted = items.toList()..sort((a, b) => a.name.compareTo(b.name));
  return ListView(...);
}

// RIGHT — compute in notifier or use a computed provider
@riverpod
List<Product> sortedProducts(Ref ref) {
  final items = ref.watch(productProvider.select((s) => s.items));
  return items.toList()..sort((a, b) => a.name.compareTo(b.name));
}
```

## Checklist

### Widget Rebuilds
- Watch providers in leaf widgets, not parents
- Use `.select()` for specific properties
- Extract widget classes, not helper methods
- Use `const` constructors wherever possible
- Never override `operator ==` on Widget — causes O(N²) rebuild checks; rely on `const` and caching instead

### State Management
- `@Riverpod(keepAlive: true)` for repos, datasources, services, notifiers
- `@riverpod` for computed values and one-time fetches
- `if (!ref.mounted) return;` after every `await`

### Data Loading
- Cache remote data locally (remote → local fallback)
- Paginate large lists
- Debounce search inputs (500ms)
- Prevent duplicate fetches with boolean flags
- Use `Future.wait()` for parallel operations

### Memory
- Dispose timers, controllers, subscriptions in `ref.onDispose()`
- Don't hold raw API responses in state
- Use auto-dispose for temporary state
