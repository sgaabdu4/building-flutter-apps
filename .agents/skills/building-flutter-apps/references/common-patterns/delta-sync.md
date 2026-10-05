# Common Patterns — Delta Sync


## Read first

1. Delta sync = pull changed rows + deleted IDs after the last confirmed server cursor.
2. Repository owns merge/delete reconciliation; notifier triggers sync + guards lifecycle.
3. Advance the cursor only after every table applies successfully.

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

Repository → map entities to models + delegate. Local datasource → keyed
upsert of the changed rows only; never read + rewrite the whole collection
([performance.md](../performance.md) rule 16,
[hive-persistence.md](../hive-persistence.md#repository-pattern)).

```dart
// features/exercises/data/repositories/exercise_repository.dart
@override
Future<void> mergeAll(List<Exercise> items) =>
    _local.mergeAll(items.map(ExerciseModel.fromEntity).toList());
```

```dart
// features/exercises/data/datasources/hive_exercise_datasource.dart
@override
Future<void> mergeAll(List<ExerciseModel> models) =>
    _box.putAll({for (final model in models) model.id: model});
```

### deleteByIds Implementation

Local datasource → delete the given keys only.

```dart
// features/exercises/data/repositories/exercise_repository.dart
@override
Future<void> deleteByIds(Set<String> ids) => _local.deleteByIds(ids);
```

```dart
// features/exercises/data/datasources/hive_exercise_datasource.dart
@override
Future<void> deleteByIds(Set<String> ids) => _box.deleteAll(ids);
```

### Sync Service Flow

Per table: no stored sync date → full pull; otherwise pull rows updated since it, then delete local IDs missing from the remote ID set. Store the newest remote `updatedAt`; a successful empty first pull stores an epoch watermark so the next run uses delta, not another full pull.

```dart
final lastTableSync = await settingsRepo.getTableSyncDate(tableKey);
final DateTime? watermark;

if (lastTableSync == null) {
  final all = await remote.getAll(userId);
  if (all.isNotEmpty) await repo.mergeAll(all.map((m) => m.toEntity()).toList());
  watermark = newestUpdatedAt(all) ?? .fromMillisecondsSinceEpoch(0, isUtc: true);
} else {
  final changed = await remote.getUpdatedSince(userId, lastTableSync);
  if (changed.isNotEmpty) await repo.mergeAll(changed.map((m) => m.toEntity()).toList());

  final remoteIds = (await remote.getAllIds(userId)).toSet();
  final localIds = {for (final exercise in await repo.getAll()) exercise.id.value};
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

Per-table keys are `StorageKeys` entries such as `StorageKeys.syncDateExercises` ([Key Registries](../architecture.md#key-registries)), never local constants in the repository.

```dart
// In settings repository:
Future<DateTime?> getTableSyncDate(String key) async {
  final ms = await _storage.read<int>(key);
  return ms != null ? .fromMillisecondsSinceEpoch(ms, isUtc: true) : null;
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
