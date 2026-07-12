# Hive CE Persistence

## Read first

1. TypeIds + HiveField indexes are permanent after release. Never reuse/reorder; append/retire only.
2. `hive_adapters.g.yaml` is disk-format SSOT. Commit it; edit manually on rename.
3. Changing field type is unsupported. Retire old field, add new field.
4. Domain is Hive-free. Hive models stay in data layer with primitives; mapper bridges VOs/entities.
5. Never change ctor param order/types for shipped `@GenerateAdapters` models.

## Trigger

Signals: hive_ce, hive_ce_flutter, TypeAdapter, @GenerateAdapters, IsolatedHive, HiveField
Before code: output `Reading: hive-persistence.md`


## Core Stack

`hive_ce`, `hive_ce_flutter`, `hive_ce_generator`. Constraints: see [core-stack.md](core-stack.md).

Flutter app source imports Hive through `hive_ce_flutter`, not `hive_ce`
directly. `hive_ce_flutter` re-exports the core Hive API and adds Flutter
integration helpers; using it keeps the Flutter package surface visible even
when code uses core types such as `Box`, `Hive`, `AdapterSpec`, or
`GenerateAdapters`.

## Setup

```yaml
# pubspec.yaml — see core-stack.md for canonical versions
dependencies:
  hive_ce: <version>
  hive_ce_flutter: <version>

dev_dependencies:
  build_runner: <version>
  hive_ce_generator: <version>
```

## TypeAdapter Storage vs JSON

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
import 'package:hive_ce_flutter/hive_ce_flutter.dart';
import 'package:my_app/features/user/data/models/user_model.dart';
import 'package:my_app/features/order/data/models/order_model.dart';

part 'hive_adapters.g.dart';

/// TypeId allocation:
/// 0 - CacheEntry (reserved for @HiveType)
/// 1 - UserModel
/// 2 - OrderModel
/// 3 - OrderItemModel
@GenerateAdapters([
  AdapterSpec<UserModel>(),
  AdapterSpec<OrderModel>(),
  AdapterSpec<OrderItemModel>(),
  AdapterSpec<OrderStatus>(), // enums work too
], firstTypeId: 1, reservedTypeIds: {0})
void _hiveAdapters() {}
```

`AdapterSpec<T>()` always names a persistence-layer `Model` from `/data/models/`, never a `/domain/entities/` class. Domain entities stay Hive-free. The mapper bridges (see [Repository Pattern](#repository-pattern) and [VO Interop](#vo-interop)).

### Step 2: Generate Adapters

```bash
dart run build_runner build --delete-conflicting-outputs
```

Generates:
- `hive_adapters.g.dart` — TypeAdapter implementations
- `hive_registrar.g.dart` — Extension method for registration

### Step 3: Register Adapters

```dart
import 'package:hive_ce_flutter/hive_ce_flutter.dart';
import 'package:my_app/core/hive/hive_registrar.g.dart';

Future<void> initializeStorage() async {
  await Hive.initFlutter('my_app');
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

## IsolatedHive (background-isolate)

Hive CE 2.19+ ships `IsolatedHive` — box on background isolate, no UI block
on big I/O. Use only when profiling shows main-isolate jank from Hive on a
hot path. Standard `Hive` fine for typical key/value.

```dart
final box = await IsolatedHive.openBox<OrderModel>('orders');
await box.put(order.id, OrderModel.fromDomain(order));
final all = await box.values; // async — crosses isolate boundary
```

Caveats:
- TypeAdapter register on isolate. Registrar same; call from spawn callback per package docs.
- All reads/writes async — no sync `get`. Update repo signatures.
- `box.watch()` works, events on port — debounce before rebuild.

## Repository Pattern

Hive = persistence detail. Canonical chain:
`HiveOrderDatasource` → `HiveOrderRepository implements IOrderRepository` → `OrderNotifier`.
Domain `Order` Hive-free. Persistence-only `OrderModel` carries `@HiveField`.
Provider returns iface — tests override w/ fake.

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

Notifier consumes `IOrderRepository` only — never touches Hive. Tests
override `orderRepositoryProvider` w/ `MockIOrderRepository`, no Hive init.
See [architecture.md](architecture.md) for layer chain, [testing.md](testing.md) for override pattern.

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
import 'package:hive_ce_flutter/hive_ce_flutter.dart';

// Standard Flutter setup: Documents directory + optional subdirectory.
await Hive.initFlutter('my_app');

// Custom path setup: keep this explicit when preserving an existing data path,
// e.g. Application Support. Still import through hive_ce_flutter.
final path = (await getApplicationSupportDirectory()).path;
Hive.init(path);
```

## Critical Rules

1. **TypeIds permanent** — Never change, rename, reuse TypeId post-release
2. **HiveField indices permanent** — Never reuse retired index. Append at `nextIndex`
3. **Field types permanent** — Never flip type (`String`↔`List`, enum↔int) at same index
4. **Box names permanent** — Rename loses data
5. **Reserve TypeId 0** — Use `reservedTypeIds: {0}` if @HiveType classes exist
6. **Gen after changes** — Run build_runner when add/modify entities
7. **Idempotent registration** — Check `isAdapterRegistered` in tests
8. **Store entities, not JSON** — TypeAdapters for direct object storage
9. **Close boxes** — Call `Hive.close()` in tearDown
10. **Hive lives in `Local<X>Datasource` ONLY** — Notifiers and widgets NEVER import `package:hive_ce` / `package:hive_ce_flutter` and NEVER call `Hive.openBox` / `Hive.box` / `box.get` / `box.put` / `box.delete`. Production Flutter `lib/` files that do use Hive import `package:hive_ce_flutter/hive_ce_flutter.dart`, not `package:hive_ce/hive_ce.dart`. Datasource implements interface; repository exposes domain entities; notifier depends on repository provider. The hook blocks Hive imports outside `data/datasources/` and `*_datasource.dart` files.

## VO Interop

`hive_adapters.g.yaml` = disk-format SSOT. **Commit it**. After release, never delete it. Ctor param order/type is append-only. Field rename requires manual `hive_adapters.g.yaml` edit. New non-nullable fields need defaults. Field type change is unsupported; add a new field.

**Rule:** `/data/models/` = primitives. `/domain/entities/` = VOs. Mapper bridges.

```dart
// /data/models/workout_set_model.dart
@freezed
sealed class WorkoutSetModel with _$WorkoutSetModel {
  const factory WorkoutSetModel({
    /// HiveField(0)
    required String id,
    /// HiveField(1)
    required double distanceMeters,
    /// HiveField(2)
    required int durationSeconds,
  }) = _WorkoutSetModel;
}
// /core/hive/hive_adapters.dart → AdapterSpec<WorkoutSetModel>()

// /domain/entities/workout_set.dart
@freezed
sealed class WorkoutSet with _$WorkoutSet {
  const factory WorkoutSet({required String id, required Distance distance, required Duration duration}) = _WorkoutSet;
}

// /data/mappers/workout_set_mapper.dart
extension WorkoutSetMapper on WorkoutSetModel {
  WorkoutSet toEntity() => WorkoutSet(id: id, distance: Distance.fromMeters(distanceMeters), duration: Duration(seconds: durationSeconds));
}
extension WorkoutSetToModel on WorkoutSet {
  WorkoutSetModel toModel() => WorkoutSetModel(id: id, distanceMeters: distance.inMeters, durationSeconds: duration.inSeconds);
}
```

**Shipped domain class:** keep primitive ctor slots; expose VOs via getters. Do not change disk shape.

**Forbidden:**
- Reorder ctor params on `@GenerateAdapters` class (silent slot shift).
- Change param type at existing position.
- Renumber/reuse `HiveField(N)`.
- Reuse retired `typeId`.

Constructor signature = append-only schema.

**Lint (ERROR):**
- `use_hive_ce_flutter_import` — production Flutter `lib/` files import Hive through `package:hive_ce_flutter/hive_ce_flutter.dart`, not `package:hive_ce/hive_ce.dart`. Test helpers may use manual temp-dir setup.
- `hive_field_no_vo_type` — `/data/models/` `@freezed` ctor: no VO types. Hard-coded set: `Distance`/`Money`/`Email`/`Slug`/`PhoneNumber`/`HeartRate`/`Weight`/`Pace`/`Username`. Auto-extends w/ types imported from `*/domain/values/<name>.dart` (PascalCase filename heuristic) + `show` clause names.

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

| Error | Fix |
|-------|-----|
| `type 'String' is not a subtype of type 'List<dynamic>'` | Check field index/typeId reuse |
| `HiveError: Cannot read, unknown typeId: N` | Register/retire adapter id correctly |
| `RangeError: value not in range` on enum | Do not reorder/remove encoded enum cases |

Upgrade-only failure = binary incompat. Check typeId / HiveField changes.

## Evolution cheat sheet

| Change | Safe? | How |
|--------|-------|-----|
| Add new field | ✅ | New ctor param at end; nullable OR default value (required for non-nullable) |
| Remove field | ✅ | Delete ctor param; retired index recorded in `hive_adapters.g.yaml` |
| Rename class | ⚠️ | Manually edit `hive_adapters.g.yaml` |
| Rename field | ⚠️ | Manually edit field key in `hive_adapters.g.yaml` (per official docs) |
| Change field type | ❌ | Per official docs: not supported. Retire old field, add new with new type |
| Reorder ctor params | ❌ | Append only |
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
- [hive_ce_flutter on pub.dev](https://pub.dev/packages/hive_ce_flutter)
