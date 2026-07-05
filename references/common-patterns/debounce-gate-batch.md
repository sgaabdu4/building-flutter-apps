# Common Patterns — Debounce, Gate, and Batch

## Read first

1. Use this for high-frequency UI/network/storage boundaries and destructive remote reconciliation.
2. For reusable `Debouncer` helper ownership or repeated ID lookup utilities, read [collections-helpers.md](../extensions/collections-helpers.md) instead.
3. For search, pagination, and form state shape, read [lists-forms-workflows.md](lists-forms-workflows.md) first, then this file only for the boundary mechanics.

## Trigger

Signals: TextField per-keystroke side effects, Slider/scroll throttling, full-collection rewrite, persistence debounce, long-running remote function, destructive reconcile-before-log, reset/clear markers, WebView/VideoPlayer gate, storage-read memoization.
Before code: output `Reading: debounce-gate-batch.md`.

## Debounce, Gate, and Batch

High-frequency boundaries (keystrokes, drag gestures, scroll ticks, sync cycles, long-running remote work, destructive reset/delete flows) must coalesce or reconcile before they reach a notifier, network, or disk. Foreground waits must stay tiny: search/realtime debounce <=150ms, visual animation <=120ms, persistence/hard waits <=50ms. Retry/backoff, rest timers, reminders, and sync/backfill settle timers belong in background owners. Each lint below catches one specific shape of the same anti-pattern: treating asynchronous boundaries as if they complete atomically and cheaply.

### Input callbacks — debounce or move to terminal event

```dart
// NEVER — fires per keystroke
TextField(onChanged: (v) {
  ref.read(searchProvider.notifier).search(v); // N requests for "hello"
});

// DO — Timer cancel-and-restart
Timer? _debounce;
TextField(onChanged: (v) {
  _debounce?.cancel();
  _debounce = Timer(const Duration(milliseconds: 150), () {
    ref.read(searchProvider.notifier).search(v);
  });
});

// Slider/RangeSlider — defer terminal effects
Slider(
  onChanged: (v) => setState(() => _local = v),       // local UI only
  onChangeEnd: (v) => ref.read(p.notifier).set(v),    // one notifier call
);
```

Lints: `text_field_on_changed_no_debounce`, `slider_on_changed_no_debounce`, `scroll_listener_no_throttle`, `user_visible_duration_too_long`.

### Notifier persistence helpers — real debounce, not just generation tokens

Use a cancel-and-restart `Timer` / `Future.delayed` / `Debouncer` to coalesce bursts. Keep foreground persistence debounce <=50ms. A queue or generation token only prevents stale/overlapping writes; it does **not** debounce.

```dart
class DraftNotifier extends Notifier {
  Timer? _debounce;
  void _persistDraft() {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 50), _save);
  }
}
```

Lints: `notifier_persistence_no_debounce`, `user_visible_duration_too_long`.

### Sync push — guard with a dirty list

```dart
void pushItems(String userId, List<Entity> items) {
  if (items.isEmpty) return;                                // early return
  remote.saveAll(userId, items.map(Model.fromEntity).toList());
}

// or outer dirty check
if (isDirty) {
  remote.saveAll(userId, items.map(Model.fromEntity).toList());
}
```

Lint: `sync_save_all_no_dirty_guard`.

### Remote Functions + destructive reconciliation

```dart
// NEVER — blocks the client on a potentially long-running backend function.
final execution = await functions.createExecution(
  functionId: deleteAccountFunctionId,
  body: payload,
  xasync: false,
);
final result = DeleteResult.fromExecution(execution);

// DO — async-start, then reconcile source of truth with bounded polling/realtime.
final start = await functions.createExecution(
  functionId: deleteAccountFunctionId,
  body: payload,
  xasync: true,
);
if (!DeleteResult.fromAsyncStart(start).ok) return false;
return waitForDeleted(userId, maxAttempts: 60, interval: const Duration(seconds: 2));
```

```dart
// NEVER — false telemetry if the backend completed after the client timed out.
} catch (e, s) {
  Crash.error(e, s);
  await _reconcileDeletedState();
}

// DO — reconcile first; log only when the source of truth still disagrees.
} catch (e, s) {
  final deleted = await _reconcileDeletedState();
  if (!deleted) Crash.error(e, s);
}
```

Lints: `appwrite_blocking_function_execution_in_client`, `destructive_failure_logged_before_reconcile`.

### Subset changes — write changed rows, not the whole collection

```dart
// NEVER — one changed row, full rewrite.
final index = items.indexWhere((item) => item.id == changed.id);
if (index >= 0) items[index] = changed;
await local.saveAll(items.map(Model.fromEntity).toList());

// DO — persist the changed subset.
await local.mergeAll([changed].map(Model.fromEntity).toList());
```

Lint: `save_all_full_collection_after_subset_mutation`.

### Collection getters and id lookup — cache indexes

```dart
// NEVER — allocates and scans on every access/call.
Map<String, List<Item>> get itemsByGroup {
  final map = <String, List<Item>>{};
  for (final item in items) {
    (map[item.groupId] ??= <Item>[]).add(item);
  }
  return map;
}
final item = items.firstWhere((item) => item.id == itemId);

// DO — cache immutable indexes and use O(1) lookup.
final itemsById = {for (final item in items) item.id: item};
final item = itemsById[itemId];
```

Lints: `collection_getter_allocates_each_access`, `linear_id_lookup_in_hot_path`, `nested_linear_lookup_by_id`.

### Heavy widgets — gate behind a user action

```dart
class VideoCard extends ConsumerWidget {
  bool _userTappedPlay = false;
  Widget build(BuildContext context, WidgetRef ref) {
    if (_userTappedPlay) return VideoPlayer(controller);
    return GestureDetector(
      onTap: () => setState(() => _userTappedPlay = true),
      child: Placeholder(),
    );
  }
}
```

Lint: `webview_init_in_build_no_gate`.

### Service storage reads — memoize

```dart
class FlagsService {
  final Map<String, bool> _cache = {};
  Future<bool> flag(String key) async => _cache[key] ??= await _storage.read<bool>(key);
}
```

Lint: `service_storage_read_no_memo`.

### Reset/clear flows — hard clear app-owned state

```dart
// DO — reset means all app-owned local keys are cleared.
Future<void> resetAll() async {
  await _storage.clear();
}

// NEVER — keeps old migration/version/install markers alive.
Future<void> resetAll() async {
  final schemaVersion = await _storage.read<String>(schemaVersionKey);
  await _storage.clear();
  if (schemaVersion != null) {
    await _storage.save(schemaVersionKey, schemaVersion);
  }
}
```

Lint: `storage_clear_preserves_migration_state`.

### Manual subscriptions — forbidden

```dart
class _State extends ConsumerState {
  void initState() {
    super.initState();
    // NEVER: manual subscription lifecycle in widget state.
    ref.listenManual(provider, (_, __) {});
  }

  Widget build(BuildContext context) {
    ref.listen(provider, (_, __) {});
    return const SizedBox.shrink();
  }
}
```

Lint: `riverpod_listen_manual_forbidden`.

### `@Riverpod(keepAlive: true)` — derive from a bounded projection

```dart
// NEVER — retains every log for the session
@Riverpod(keepAlive: true)
List<Log> session(Ref ref) => ref.watch(provider.select((s) => s.logs));

// DO — bounded projection
@Riverpod(keepAlive: true)
int sessionCount(Ref ref) => ref.watch(provider.select((s) => s.count));
```

Lint: `keepalive_watches_unbounded_collection`.

### Datasource interfaces — expose a batch loader

```dart
abstract class SettingsLocalDatasource {
  Future<SettingsSnapshot> loadAll();          // one read, all values
  Future<bool> getOptIn();                     // optional single-value getters
  Future<int> getThemeIndex();
}
```

Lint: `datasource_missing_batch_loader`.

### Save callbacks — guard zero / empty input

```dart
void submit(int amount, int count) {
  if (amount <= 0 && count <= 0) return;       // no empty rows
  ref.read(provider.notifier).saveEntry(amount: amount, count: count);
}
```

Lint: `notifier_zero_value_save_no_guard`.

### Widget→notifier boundary — wrap unit primitives in Value Objects

```dart
// NEVER — raw unit-bearing primitive crosses the boundary
double distanceMeters = parsed;
ref.read(provider.notifier).save(distance: distanceMeters);

// DO — wrap at the boundary
final distance = Distance.fromMeters(parsed);  // domain VO with invariants
ref.read(provider.notifier).save(distance: distance);
```

Lint: `notifier_param_requires_value_object`. See [value-objects.md](../value-objects.md).

### Modal helpers — always pass `routeSettings`

```dart
Future<T?> openConfirm<T>(BuildContext context) => showDialog<T>(
  context: context,
  routeSettings: const RouteSettings(name: 'confirm-dialog'),
  builder: (_) => const ConfirmDialog(),
);
```

Lint: `modal_helper_requires_route_settings`.

Cross-link: [Modal Snapshot Pattern](modals-navigation.md#modal-snapshot-pattern) covers the dialog mutation half. [State Teardown Belongs in the Notifier](../state-management-lifecycle.md#state-teardown-belongs-in-the-notifier) covers the success-path teardown half.
