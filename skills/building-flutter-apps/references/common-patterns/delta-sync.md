# Common Patterns — Delta Sync

## Delta Sync (Incremental Remote Pull)

Fetch only rows changed since last sync, not all data.

### Repository Interface Additions

```dart
abstract interface class IExerciseRepository {
  // ... existing CRUD ...

  /// Upserts changed items into local storage by ID.
  Future<void> mergeAll(List<Exercise> items);

  /// Removes locally-stored items whose IDs are no longer present remotely.
  Future<void> deleteByIds(Set<String> ids);
}
```

### mergeAll Implementation

```dart
@override
Future<void> mergeAll(List<Exercise> items) async {
  final current = await _local.getAll();
  final updated = [...current];

  final updatedById = {for (final item in updated) item.id: item};

  for (final item in items) {
    updatedById[item.id] = item;
  }

  await _local.saveAll(updatedById.values.toList(growable: false));
}
```

### deleteByIds Implementation

```dart
@override
Future<void> deleteByIds(Set<String> ids) async {
  final current = await _local.getAll();
  final filtered = current.where((e) => !ids.contains(e.id)).toList();
  await _local.saveAll(filtered);
}
```

### Sync Service Flow

```dart
// Per-table delta sync:
// 1. Read per-table lastSyncDate from settings
// 2. If null → first sync full getAll + mergeAll
// 3. If exists → getUpdatedSince(lastSyncDate) + mergeAll
// 4. getAllIds from remote, compare to local IDs, deleteByIds for missing
// 5. Store newest remote updatedAt; for a successful empty first pull, store
//    an epoch/sentinel watermark so the next run uses delta, not another full pull.

final lastTableSync = await settingsRepo.getTableSyncDate(tableKey);
final DateTime? watermark;

if (lastTableSync == null) {
  final all = await remote.getAll(userId);
  if (all.isNotEmpty) await repo.mergeAll(all.map((m) => m.toEntity()).toList());
  watermark = newestUpdatedAt(all) ?? DateTime.fromMillisecondsSinceEpoch(0, isUtc: true);
} else {
  final changed = await remote.getUpdatedSince(userId, lastTableSync);
  if (changed.isNotEmpty) await repo.mergeAll(changed.map((m) => m.toEntity()).toList());

  final remoteIds = (await remote.getAllIds(userId)).toSet();
  final localIds = (await repo.getAll()).map((e) => e.id).toSet();
  final deleted = localIds.difference(remoteIds);
  if (deleted.isNotEmpty) await repo.deleteByIds(deleted);
  watermark = newestUpdatedAt(changed);
}

if (watermark != null) {
  await settingsRepo.setTableSyncDate(tableKey, watermark);
}
```

Reference/catalog data should follow the same contract: full pull only when the
per-table marker is missing, then delta pulls on later launches. Do not force an
`alwaysFullPull` path for normal app open; reserve explicit full refreshes for
manual repair/admin flows.

### Per-Table Sync Date Storage

```dart
// In settings repository:
static const exerciseSyncDateKey = 'sync_date_exercises';

Future<DateTime?> getTableSyncDate(String key) async {
  final ms = await _storage.read<int>(key);
  return ms != null ? DateTime.fromMillisecondsSinceEpoch(ms, isUtc: true) : null;
}

Future<void> setTableSyncDate(String key, DateTime date) async {
  await _storage.save(key, date.millisecondsSinceEpoch);
}
```

### When to Use

| Scenario | Approach |
|----------|----------|
| Data rarely changes | Delta sync — fetches nothing when no changes |
| Frequent small edits | Delta sync — fetches only changed rows |
| Full data refresh needed | Full pull with `saveAll` |
