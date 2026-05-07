# Hive CE Persistence

Binary persistence Flutter. Hive CE + TypeAdapter codegen.

## Core Stack

`hive_ce`, `hive_ce_flutter`, `hive_ce_generator`. Constraints: see [README.md → Core Stack](../README.md#whats-included).

## Setup

```yaml
# pubspec.yaml — see README.md Core Stack for canonical versions
dependencies:
  hive_ce: <version>
  hive_ce_flutter: <version>

dev_dependencies:
  build_runner: <version>
  hive_ce_generator: <version>
```

## TypeAdapter Storage vs JSON

TypeAdapters big perf win.

| Mode | Reads | Writes | Size |
|------|-------|--------|------|
| Binary (TypeAdapter) | ~10x faster | ~5x faster | ~60% smaller |
| JSON (no adapter) | Baseline | Baseline | Baseline |

Use TypeAdapters for hot-path entities.

## @GenerateAdapters Pattern

Gen TypeAdapters for Freezed classes sans @HiveType.

### Step 1: Create Adapter Specification

```dart
// lib/core/hive/hive_adapters.dart
import 'package:hive_ce/hive_ce.dart';
import 'package:my_app/features/user/domain/entities/user.dart';
import 'package:my_app/features/order/domain/entities/order.dart';

part 'hive_adapters.g.dart';

/// TypeId allocation:
/// 0 - CacheEntry (reserved for @HiveType)
/// 1 - User
/// 2 - Order
/// 3 - OrderItem
@GenerateAdapters([
  AdapterSpec<User>(),
  AdapterSpec<Order>(),
  AdapterSpec<OrderItem>(),
  AdapterSpec<OrderStatus>(), // enums work too
], firstTypeId: 1, reservedTypeIds: {0})
void _hiveAdapters() {}
```

### Step 2: Generate Adapters

```bash
dart run build_runner build --delete-conflicting-outputs
```

Generates:
- `hive_adapters.g.dart` — TypeAdapter implementations
- `hive_registrar.g.dart` — Extension method for registration

### Step 3: Register Adapters

```dart
import 'package:hive_ce_flutter/hive_flutter.dart';
import 'package:my_app/core/hive/hive_registrar.g.dart';

Future<void> initializeStorage() async {
  final path = (await getApplicationSupportDirectory()).path;
  Hive.init(path);
  Hive.registerAdapters(); // One call registers all adapters
}
```

## TypeId Management

TypeIds unique + stable. Change TypeId = break existing data.

```
// Allocation strategy: Reserve ranges per feature
// 0-9: Core (AppState, Settings, Cache)
// 10-19: User feature
// 20-29: Orders feature
```

## Mixing @HiveType and @GenerateAdapters

@HiveType for non-Freezed. @GenerateAdapters for Freezed.

```dart
// Non-Freezed class with @HiveType
@HiveType(typeId: 0)
class CacheEntry {
  @HiveField(0)
  final String key;
  
  @HiveField(1)
  final String value;
  
  CacheEntry({required this.key, required this.value});
}

// Freezed classes use @GenerateAdapters
@GenerateAdapters([
  AdapterSpec<User>(),     // typeId: 1
], firstTypeId: 1, reservedTypeIds: {0})
```

## IsolatedHive (background-isolate persistence)

Hive CE 2.19+ ships `IsolatedHive` — a parallel API that runs the box on a
background isolate so large reads/writes don't block the UI. Use it only when
profiling shows main-isolate jank from Hive I/O on a hot path; for typical
key/value usage the standard `Hive` API is fine.

```dart
final box = await IsolatedHive.openBox<OrderModel>('orders');
await box.put(order.id, OrderModel.fromDomain(order));
final all = await box.values; // async — crosses the isolate boundary
```

Caveats the package surfaces:
- TypeAdapter registration has to happen on the isolate (registrar generated
  the same way; call from the spawn callback the package documents).
- Every read/write is async — no sync `get`. Update repository signatures
  accordingly.
- Streaming via `box.watch()` works but events arrive on a port; debounce
  before driving rebuilds.

## Repository Pattern

Hive is a persistence detail. Follow the canonical chain:
`HiveOrderDatasource` → `HiveOrderRepository implements IOrderRepository` → `OrderNotifier`.
Domain `Order` stays Hive-free; persistence-only `OrderModel` carries `@HiveField` indices.
Provider returns the interface so tests can override with a fake.

```dart
// features/orders/domain/entities/order.dart — pure domain, no Hive imports
@freezed
sealed class Order with _$Order {
  const factory Order({
    required String id,
    required List<OrderItem> items,
    required OrderStatus status,
  }) = _Order;
}
```

```dart
// features/orders/data/models/order_model.dart — Hive persistence model
@GenerateAdapters([
  AdapterSpec<OrderModel>(),
  AdapterSpec<OrderItemModel>(),
  AdapterSpec<OrderStatus>(),
], firstTypeId: 20)
@freezed
sealed class OrderModel with _$OrderModel {
  const OrderModel._();
  const factory OrderModel({
    required String id,
    required List<OrderItemModel> items,
    required OrderStatus status,
  }) = _OrderModel;

  factory OrderModel.fromDomain(Order o) => OrderModel(
        id: o.id,
        items: o.items.map(OrderItemModel.fromDomain).toList(),
        status: o.status,
      );

  Order toDomain() => Order(id: id, items: items.map((m) => m.toDomain()).toList(), status: status);
}
```

```dart
// features/orders/data/datasources/hive_order_datasource.dart
abstract interface class IOrderLocalDatasource {
  Future<void> save(OrderModel model);
  OrderModel? get(String id);
  List<OrderModel> getAll();
  Future<void> delete(String id);
}

class HiveOrderDatasource implements IOrderLocalDatasource {
  HiveOrderDatasource(this._box);
  final Box<OrderModel> _box;

  @override
  Future<void> save(OrderModel model) => _box.put(model.id, model);
  @override
  OrderModel? get(String id) => _box.get(id);
  @override
  List<OrderModel> getAll() => _box.values.toList();
  @override
  Future<void> delete(String id) => _box.delete(id);
}

@Riverpod(keepAlive: true)
Future<IOrderLocalDatasource> orderLocalDatasource(Ref ref) async {
  final box = await Hive.openBox<OrderModel>('orders');
  ref.onDispose(box.close);
  return HiveOrderDatasource(box);
}
```

```dart
// features/orders/domain/repositories/i_order_repository.dart
abstract interface class IOrderRepository {
  Future<void> save(Order order);
  Order? get(String id);
  List<Order> getAll();
  Future<void> delete(String id);
}
```

```dart
// features/orders/data/repositories/hive_order_repository.dart
class HiveOrderRepository implements IOrderRepository {
  HiveOrderRepository(this._datasource);
  final IOrderLocalDatasource _datasource;

  @override
  Future<void> save(Order order) =>
      _datasource.save(OrderModel.fromDomain(order));

  @override
  Order? get(String id) => _datasource.get(id)?.toDomain();

  @override
  List<Order> getAll() =>
      _datasource.getAll().map((m) => m.toDomain()).toList();

  @override
  Future<void> delete(String id) => _datasource.delete(id);
}

@Riverpod(keepAlive: true)
Future<IOrderRepository> orderRepository(Ref ref) async {
  final datasource = await ref.watch(orderLocalDatasourceProvider.future);
  return HiveOrderRepository(datasource);
}
```

Notifier consumes `IOrderRepository` only — never reaches into Hive itself.
Tests override `orderRepositoryProvider` with `MockIOrderRepository`; no Hive
init needed in unit tests. See `architecture.md` for the full layer chain and
`testing.md` for the override pattern.

## Testing with TypeAdapters

```dart
// test/shared/hive_test_helper.dart
class HiveTestHelper {
  static Future<Directory> initialize(String testName) async {
    final tempDir = Directory('${Directory.current.path}/test_hive_$testName');
    if (tempDir.existsSync()) tempDir.deleteSync(recursive: true);
    tempDir.createSync();
    Hive.init(tempDir.path);
    _registerAdapters();
    return tempDir;
  }

  static Future<void> cleanup(Directory tempDir) async {
    await Hive.close();
    if (tempDir.existsSync()) tempDir.deleteSync(recursive: true);
  }
}

/// Idempotent adapter registration.
void _registerAdapters() {
  if (!Hive.isAdapterRegistered(0)) {
    Hive.registerAdapter(CacheEntryAdapter());
  }
  if (!Hive.isAdapterRegistered(1)) {
    Hive.registerAdapter(UserAdapter());
  }
}
```

## Storage Location

```dart
// Use Application Support (not Documents)
final path = (await getApplicationSupportDirectory()).path;
Hive.init(path);
```

## Critical Rules

1. **TypeIds permanent** — Never change, rename, reuse TypeId post-release
2. **HiveField indices permanent** — Never reuse removed field index. Append new at `nextIndex`
3. **Field types permanent** — Never flip type (`String`↔`List`, enum↔int) at same index
4. **Box names permanent** — Rename loses data
5. **Reserve TypeId 0** — Use `reservedTypeIds: {0}` if @HiveType classes exist
6. **Gen after changes** — Run build_runner when add/modify entities
7. **Idempotent registration** — Check `isAdapterRegistered` in tests
8. **Store entities, not JSON** — TypeAdapters for direct object storage
9. **Close boxes** — Call `Hive.close()` in tearDown

## Retiring entities

Delete class = retire typeId. Never reuse for successor. Add retired id to `reservedTypeIds`. New class gets fresh id.

```dart
// WRONG — Program deleted, Routine reused typeId 10
// Old user data written as Program at id 10 → new RoutineAdapter reads it
// → cryptic type-cast crash on boot

// RIGHT
@GenerateAdapters([
  AdapterSpec<Routine>(),     // new id 12 (next free)
  AdapterSpec<RoutineDay>(),  // new id 13
], firstTypeId: 1, reservedTypeIds: {0, 9, 10, 11}) // 9/10/11 retired
```

Field retirement same rule: remove field from class + keep index in `nextIndex` accounting, never reassign.

## Failure signatures

Typeid / field reuse symptoms:

| Error | Cause |
|-------|-------|
| `type 'String' is not a subtype of type 'List<dynamic>'` in `BinaryReaderImpl.readFrame` | Field index or typeId reused; new adapter reads old bytes |
| `HiveError: Cannot read, unknown typeId: N` | Adapter for retired typeId not registered |
| `RangeError: value not in range` on enum | Enum reordered or cases removed |

Fresh install works, upgrade breaks = binary incompat. Grep commit history for typeId / HiveField index reassignment.

## Evolution cheat sheet

| Change | Safe? | How |
|--------|-------|-----|
| Add new field | ✅ | New `@HiveField(nextIndex)`, nullable or default value |
| Remove field | ✅ | Delete property; leave index retired (never reuse) |
| Rename class | ✅ | Class name change only — Dart symbol, not serialized |
| Rename field | ✅ | Dart symbol only; `@HiveField` index unchanged |
| Change field type | ❌ | Retire old index, add new index with new type |
| Delete class | ✅ | Retire typeId into `reservedTypeIds` |
| Replace class (rename + restructure) | ❌ (if typeId reused) | New typeId, retire old |
| Reorder enum cases | ❌ | Enum encoded by index — retire adapter, new one |

## File Structure

```
lib/core/hive/
├── hive_adapters.dart       # @GenerateAdapters annotation
├── hive_adapters.g.dart     # Generated adapters
└── hive_registrar.g.dart    # Generated registrar
test/shared/
└── hive_test_helper.dart
```

## Adding New Entities

1. Create Freezed entity
2. Add `AdapterSpec<Entity>()` to @GenerateAdapters list
3. Run `dart run build_runner build`
4. Update test helper if needed

## References

- [Hive CE Documentation](https://docs.hivedb.dev/)
- [hive_ce on pub.dev](https://pub.dev/packages/hive_ce)
