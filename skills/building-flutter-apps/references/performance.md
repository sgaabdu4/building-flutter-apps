# Performance


## Read first

1. Bind providers in the smallest screen/subscreen boundary; `.select()` only the field needed. Never use `.select((value) => value)` (`riverpod_select_identity_forbidden`); use a field/record select, or watch a generated computed projection provider directly when the entire provider value is already the render projection.
2. High-frequency values (`seconds`, `progress`, `isRunning`) stay in the smallest screen-owned Consumer boundary; reusable widgets receive immutable values.
3. Extract widget classes; no `_buildXxx()` helpers. Use `const` where possible.
4. Dynamic lists use builders/slivers; no eager `ListView(children: [...])`.
5. No expensive sort/filter/map in `build()`; use computed providers/cached indexes.
6. Cache/index/snapshot values need one SSOT: computed provider, notifier/repo state, non-const instance `late final` derived field, or memoized service/repo/datasource cache; never repeat in widget state and never use top-level/global `Expando` side tables. Const Freezed state/entities cannot own `late final` caches.
7. No top-level/global widget helper functions, no `*Data` helper namespaces that filter/map/sort/index collections, and no private widget helpers that derive collections (`where`/`map`/`sort`/lookups); use computed providers/notifiers or non-widget service/model classes.
8. Persist changed rows only after subset mutation; no full-collection rewrite hot paths.
9. Reorderable lists use `onReorderItem` semantics directly: insert at `newIndex`; no deprecated framework `onReorder`, no inverse adapter math, no downstream legacy `newIndex -= 1`. Lint: `use_on_reorder_item_index_semantics`.
10. Foreground waits stay tiny: search/realtime debounce <=150ms, visual animation <=120ms, persistence/hard waits <=50ms. Retry/backoff, rest timers, reminders, and sync/backfill settle timers are background/domain concerns, not tap latency. Lint: `user_visible_duration_too_long`.

## Trigger

Signals: ref.watch, Consumer boundary, .select(), ListView.builder, computed provider, ref.onDispose
Before code: output `Reading: performance.md`


Flutter rendering/animations/slivers/isolates/app-size → see [flutter-optimizations.md](flutter-optimizations.md).

## Rules — NEVER Violate

1. **MUST** bind providers in the smallest screen/subscreen Consumer boundary and pass minimal immutable view data to reusable widgets.
2. **MUST** use `.select()` for specific fields at provider-binding boundaries.
3. **MUST** extract widget classes — NEVER helper methods (`_buildXxx()`).
4. **MUST** use `const` constructors where possible.
5. **MUST** use `ListView.builder` — NEVER `ListView(children: [...])` for dynamic lists.
6. **NEVER** expensive ops (sort/filter/map) in `build()` — use computed providers.
7. **NEVER** declare top-level/global helper functions in widget/screen files. Put behavior on widget classes, `abstract final class` namespaces, computed providers, or notifiers. Lint: `widget_top_level_function_boundary`.
8. **NEVER** put derived collection logic in widget-file `*Data` namespaces or private widget helpers (`List<T> _filtered...`, `Map<K, V> _itemsBy...`). Use computed providers/notifiers. Lint: `widget_derived_collection_logic`.
9. **NEVER** duplicate provider-derived caches/indexes/snapshots in `ConsumerState`; one provider/notifier/repo/service is the SSOT. No provider-family arg wrappers (`config`/`args`/`params`) or `ProviderSubscription` fields in widget state. No `ref.listenManual`. Lints: `riverpod_consumer_state_derived_cache`, `riverpod_widget_provider_arg_wrapper`, `riverpod_consumer_state_provider_subscription`, `riverpod_listen_manual_forbidden`.
10. **MUST** dispose timers/controllers/subscriptions via `ref.onDispose()`.
11. **NEVER** hold raw API responses in state — extract needed fields only.
12. **NEVER** clamp text scaling at app root. Fix local responsive layout/overflow instead.
13. **NEVER** watch timer/ticker/progress fields in a broad modal/sheet parent. Extract the smallest screen-owned Consumer boundary for the ticking controls.
14. **NEVER** allocate Map/List/Set in getters used from `build()` / `.select()` / hot notifier paths. Use computed providers/service caches, or non-const instance-owned `late final` immutable indexes; do not use top-level/global `Expando` side tables.
15. **NEVER** do repeated id lookups with `firstWhere` / `indexWhere` / `for` loops in hot paths. Pre-index by id with `Map`.
16. **NEVER** persist full collections after changing a subset. Write changed rows via `mergeAll` / `saveMany`; debounce draft persistence with a real `Timer` / `Debouncer` at <=50ms.
17. **NEVER** block splash/cover routes on background sync, table backfill, or local merge work. Route to the shell when auth/setup is known, then hydrate data behind local state. Lint: `router_splash_waits_for_initial_sync`.
18. **NEVER** add foreground hard sleeps or slow debounces. Search/realtime debounce <=150ms, visual animation <=120ms, persistence/hard waits <=50ms. Lint: `user_visible_duration_too_long`.
19. **MUST** use `onReorderItem` semantics directly for `ReorderableListView`, `SliverReorderableList`, and `ReorderableList`: `newIndex` is already post-removal. Insert at `newIndex`; do not use deprecated framework `onReorder`, `newIndex > oldIndex ? newIndex + 1 : newIndex`, or `if (oldIndex < newIndex) newIndex -= 1`. Lint: `use_on_reorder_item_index_semantics`.

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

### Bind Providers at Screen Boundaries

Bind in the smallest screen/subscreen Consumer boundary. Reusable widgets receive minimal immutable view inputs:

```dart
// WRONG — broad state watch rebuilds the whole screen subtree.
class UserScreen extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final userState = ref.watch(userProvider);
    return UserSummary(user: userState.user);
  }
}

// RIGHT — screen selects the render projection; widget stays provider-free.
class UserSummaryScreen extends ConsumerWidget {
  const UserSummaryScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final (:name, :email) = ref.watch(
      userProvider.select((s) => (name: s.name, email: s.email)),
    );
    return UserSummary(name: name, email: email);
  }
}

class UserSummary extends StatelessWidget {
  const UserSummary({required this.name, required this.email, super.key});

  final String name;
  final String email;

  @override
  Widget build(BuildContext context) => Column(
        children: [Text(name), Text(email)],
      );
}
```

### Use .select() to Watch Specific Fields

`select` skips rebuilds when unrelated fields change. `.select()` is necessary but not sufficient: if the selected field changes every second, the binding boundary still rebuilds every second. Put timer/ticker/progress watches in the smallest screen-owned Consumer boundary.

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

Build must be pure. Do not hide field/controller mutations in helper calls from `build()`.

```dart
// WRONG — build calls helper that mutates fields/controllers.
@override
Widget build(BuildContext context) {
  final item = ref.watch(itemProvider);
  _syncInitialValues(item); // assigns _controller.text / _cached fields
  return const SizedBox.shrink();
}
```

```dart
// RIGHT — sync from lifecycle/event/provider, not build.
@override
void didUpdateWidget(covariant Editor oldWidget) {
  super.didUpdateWidget(oldWidget);
  _syncInitialValues(widget.initialItem);
}
```

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

## Indexed Lookup and Persistence Hot Paths

### Cache immutable collection indexes

```dart
// WRONG — fresh Map every getter access. Records/selects see new identity.
Map<String, List<Item>> get itemsByGroup {
  final map = <String, List<Item>>{};
  for (final item in items) {
    (map[item.groupId] ??= <Item>[]).add(item);
  }
  return map;
}
```

```dart
// RIGHT — compute once on a non-const immutable instance.
late final Map<String, List<Item>> itemsByGroup = _indexItemsByGroup(items);
```

### Pre-index repeated id lookups

```dart
// WRONG — O(n*m)
for (final change in changes) {
  final index = items.indexWhere((item) => item.id == change.itemId);
  if (index >= 0) apply(change);
}
```

```dart
// RIGHT — O(n+m)
final itemsById = {for (final item in items) item.id: item};
for (final change in changes) {
  final item = itemsById[change.itemId];
  if (item != null) apply(change);
}
```

### Debounce full-state persistence

A queue or generation token prevents races; it does **not** coalesce writes. Draft persistence called after taps/reorders/expands needs cancel-and-restart `Timer` / `Debouncer` at <=50ms, plus an explicit `persistNow()` for lifecycle flush.

Relevant lints: `modal_high_frequency_watch_not_leaf`, `build_calls_mutating_instance_method`, `collection_getter_allocates_each_access`, `expando_derived_cache_forbidden`, `linear_id_lookup_in_hot_path`, `nested_linear_lookup_by_id`, `save_all_full_collection_after_subset_mutation`, `notifier_persistence_no_debounce`, `user_visible_duration_too_long`, `appwrite_blocking_function_execution_in_client`, `destructive_failure_logged_before_reconcile`, `storage_clear_preserves_migration_state`.

## Checklist

### Widget Rebuilds
- Bind providers in the smallest screen/subscreen Consumer boundary
- Pass minimal immutable view data + typed callbacks to reusable widgets
- Use `.select()` for specific fields
- Extract widget classes, not helper methods
- Use `const` constructors where possible
- Never override `operator ==` on Widget — O(N²) rebuild check; use `const` + caching
- Timer/ticker/progress provider watches live in the smallest screen-owned Consumer boundary, not broad sheet/dialog parents
- `build()` does not call private helpers that assign fields/controllers or call `setState`
- Collection getters used from UI/notifiers are cached or provider-derived, not rebuilt per access
- Id lookups in hot paths use `Map` indexes, not `firstWhere` / `indexWhere` / manual loops

### State Management
- `@Riverpod(keepAlive: true)` for repos, datasources, services, notifiers
- `@riverpod` for computed values, one-time fetches
- `if (!ref.mounted) return;` after every `await`

### Data Loading
- Cache remote data locally (remote → local fallback)
- Paginate large lists
- Debounce search inputs at <=150ms
- Debounce draft/full-state persistence at <=50ms with a real Timer/Debouncer; queues/generation tokens are not debounce
- Persist changed subsets with `mergeAll` / `saveMany`; avoid full `saveAll` rewrites after subset mutation
- Async-start long-running remote functions and reconcile source-of-truth state instead of blocking the client request
- Reconcile destructive failures before Crash/Sentry/Firebase reporting
- Do not preserve migration/version/install markers around reset/clear flows
- Prevent duplicate fetches with boolean flags
- Use `Future.wait()` for parallel ops

### Memory
- Dispose timers/controllers/subscriptions in `ref.onDispose()`
- No raw API responses in state
- Auto-dispose for temporary state
