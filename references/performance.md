# Performance

## Trigger

Signals: ref.watch, leaf widget, .select(), ListView.builder, computed provider, ref.onDispose
Before generating code in this area, output verbatim: `Reading: performance.md`


Flutter rendering/animations/slivers/isolates/app-size → see [flutter-optimizations.md](flutter-optimizations.md).

## Rules — NEVER Violate

1. **MUST** watch providers in leaf widgets — NEVER parents passing data down.
2. **MUST** use `.select()` for specific fields in leaf widgets.
3. **MUST** extract widget classes — NEVER helper methods (`_buildXxx()`).
4. **MUST** use `const` constructors where possible.
5. **MUST** use `ListView.builder` — NEVER `ListView(children: [...])` for dynamic lists.
6. **NEVER** expensive ops (sort/filter/map) in `build()` — use computed providers.
7. **MUST** dispose timers/controllers/subscriptions via `ref.onDispose()`.
8. **NEVER** hold raw API responses in state — extract needed fields only.
9. **NEVER** clamp text scaling at app root. Fix local responsive layout/overflow instead.

## Widget Rebuild Rules

### Text Scaling

Do not disable user accessibility globally:

```dart
// WRONG — app-wide clamp hides layout bugs and blocks accessibility.
MaterialApp(
  builder: (context, child) => MediaQuery.withClampedTextScaling(
    maxScaleFactor: 1,
    child: child!,
  ),
);
```

Fix the widget:

- allow wrapping
- use `Flexible`/`Expanded`
- avoid fixed heights around text
- use shorter labels
- make compact controls icon-first
- test large text sizes on small screens

### Watch in Leaf Widgets

Watch in smallest widget. NEVER watch in parent + pass down:

```dart
// WRONG — parent rebuilds all children (prop drilling)
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

`select` skip rebuild when unrelated fields change:

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
// WRONG — helper methods hide rebuild boundaries.
Widget _buildHeader() => Container(...);
```

```dart
class HeaderWidget extends StatelessWidget {
  const HeaderWidget({super.key});

  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}
```

### Use const Constructors

```dart
// WRONG — allocates new object on every parent rebuild
return Padding(padding: const EdgeInsets.all(16), child: child);

// RIGHT — reuses existing object. `const` requires every argument be const,
// so the child must be a concrete const widget (here: SizedBox.shrink()).
// You CANNOT pass a runtime `child` variable into a const constructor.
return const Padding(padding: EdgeInsets.all(16), child: SizedBox.shrink());
```

## Provider Lifecycle

### keepAlive vs Auto-Dispose

| `@Riverpod(keepAlive: true)` | `@riverpod` |
|------------------------------|-------------|
| Repositories, datasources, services | Computed values, derived data |
| Feature notifiers | One-time fetches |
| Computed providers whose **all** deps are keepAlive | Computed providers with mixed dep lifecycles |
| Lives until app terminates | Disposes when no widget watches |

Auto-dispose in all-keepAlive chain can break pause/resume subscription counting. Match lifecycle.

Practical guardrails:
- If all upstream deps are `keepAlive`, keep downstream computed providers `keepAlive`.
- Do not stack computed hops in pause-sensitive paths (`computedA -> computedB -> familyC`).
- Flatten: watch base state once, derive with pure helpers.

### Equality Filtering

Riverpod 3.0 use `==` for notification filter. Freezed gen `==` auto.

Override `updateShouldNotify` only when want reference-equality (`identical`) for perf-sensitive large state:

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
// WRONG — NEVER build all items at once
ListView(children: items.map((i) => ItemWidget(i)).toList())

// RIGHT — MUST use builder for lazy loading
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
- Use `.select()` for specific props
- Extract widget classes, not helper methods
- Use `const` constructors where possible
- Never override `operator ==` on Widget — O(N²) rebuild check; use `const` + caching

### State Management
- `@Riverpod(keepAlive: true)` for repos, datasources, services, notifiers
- `@riverpod` for computed values, one-time fetches
- `if (!ref.mounted) return;` after every `await`

### Data Loading
- Cache remote data locally (remote → local fallback)
- Paginate large lists
- Debounce search inputs (500ms)
- Prevent duplicate fetches with boolean flags
- Use `Future.wait()` for parallel ops

### Memory
- Dispose timers/controllers/subscriptions in `ref.onDispose()`
- No raw API responses in state
- Auto-dispose for temporary state

## Recap

1. MUST watch providers in leaf widgets — NEVER in parent widgets that pass data down as props. Watching high in the tree causes every descendant to rebuild on each state change.
2. MUST use `.select()` for specific fields so rebuilds fire only when the watched field changes — watching the whole provider object rebuilds on any field change, even unrelated ones.
3. MUST use `ListView.builder` — NEVER `ListView(children: [...])` for dynamic lists. The `children` form eagerly constructs all items; `builder` lazy-constructs only visible items.

