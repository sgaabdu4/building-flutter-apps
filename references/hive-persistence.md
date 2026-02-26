# Hive CE Persistence

Binary persistence for Flutter using Hive CE with TypeAdapter code generation.

## Core Stack

| Package | Version | Purpose |
|---------|---------|---------|
| hive_ce | 2.19.3+ | Core binary storage |
| hive_ce_flutter | 2.3.4+ | Flutter integration |
| hive_ce_generator | 1.9.0+ | TypeAdapter code generation |

## TypeAdapter Storage vs JSON

TypeAdapters provide significant performance gains.

| Mode | Reads | Writes | Size |
|------|-------|--------|------|
| Binary (TypeAdapter) | ~10x faster | ~5x faster | ~60% smaller |
| JSON (no adapter) | Baseline | Baseline | Baseline |

Use TypeAdapters for entities read/written frequently.

## @GenerateAdapters Pattern

Generate TypeAdapters for Freezed classes without @HiveType annotations.

### Step 1: Create Adapter Specification

```dart
// lib/core/hive/hive_adapters.dart
import 'package:hive_ce/hive.dart';
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

TypeIds must be unique and stable. Changing a TypeId breaks existing data.

```
// Allocation strategy: Reserve ranges per feature
// 0-9: Core (AppState, Settings, Cache)
// 10-19: User feature
// 20-29: Orders feature
```

## Mixing @HiveType and @GenerateAdapters

Use @HiveType for non-Freezed classes. Use @GenerateAdapters for Freezed classes.

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

## Repository Pattern

```dart
@Riverpod(keepAlive: true)
class OrderRepository extends _$OrderRepository {
  late Box<Order> _box;
  
  @override
  FutureOr<void> build() async {
    _box = await Hive.openBox<Order>('orders');
  }
  
  Future<void> save(Order order) async => await _box.put(order.id, order);
  Order? get(String id) => _box.get(id);
  List<Order> getAll() => _box.values.toList();
  Future<void> delete(String id) async => await _box.delete(id);
}
```

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

1. **TypeIds are permanent** — Never change a TypeId after release
2. **Reserve TypeId 0** — Use `reservedTypeIds: {0}` if you have @HiveType classes
3. **Generate after changes** — Run build_runner when adding/modifying entities
4. **Idempotent registration** — Check `isAdapterRegistered` in tests
5. **Store entities, not JSON** — Use TypeAdapters for direct object storage
6. **Close boxes** — Call `Hive.close()` in tearDown

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
