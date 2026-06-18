# Value Objects

## Read first

1. Domain-meaning primitives (unit/currency/identity/format) become sealed Freezed VOs in `/domain/values/`.
2. Public factories validate; raw redirects stay private (`._raw`, `._meters`). No passthrough factories.
3. Domain entities do not expose named primitive factories; convert at data/notifier/import boundaries.
4. Hive/data models keep primitives; mappers bridge model primitives ↔ domain VOs.
5. Use VO when concept spans 2+ entities; one-off derivation can be an entity getter.
6. Required domain strings are non-empty VOs. Optional strings are `String?` and blank input is normalized to `null` before domain construction.

## Trigger

Signals: `Distance`, `Money`, `Email`, `Username`, `Slug`, `PhoneNumber`, `HeartRate`, `Weight`, `Pace`, unit conversion in domain, currency math in domain, bare `double distanceMeters` / `int amountCents` / `String email` at entity boundary, `arch_domain_import` fighting `core/extensions/` import.

Before code: output `Reading: value-objects.md`

## Decision

| Scope | Use |
|---|---|
| 1 entity, 1 derivation | Entity getter |
| 2+ entities share primitive concept | Value Object in `/domain/values/` |
| Widget/notifier/repo-only helper | `core/extensions/` |

Domain never imports `core/extensions/`; `arch_domain_import` = ERROR.

## Where

- Feature: `lib/features/<x>/domain/values/<name>.dart`
- Shared: `lib/core/domain/values/<name>.dart`

Both match `/domain/` → both allowed.

## Nullability + Empty Text

`null` means absence. `''` means a present empty string. Do not use `''` as a
missing-value sentinel in domain code.

| Situation | Use |
|---|---|
| Required ID / slug / email / display name | VO factory that trims and rejects blank |
| Optional note / bio / description | `String?`, with blank normalized to `null` at data/notifier/import boundary |
| Search query / form draft | non-domain state field named `query`, `searchQuery`, `draftName`, or `inputText` |
| No items | non-null collection default `[]` / `{}` |

Boundary normalization:

```dart
String? optionalTextFromInput(String input) {
  final trimmed = input.trim();
  return trimmed.isEmpty ? null : trimmed;
}
```

## Distance

```dart
// lib/core/domain/values/distance.dart
import 'package:freezed_annotation/freezed_annotation.dart';
part 'distance.freezed.dart';

@Freezed(map: FreezedMapOptions.none, when: FreezedWhenOptions.none)
sealed class Distance with _$Distance {
  const Distance._();
  const factory Distance._meters(double value) = _Meters;
  const factory Distance._kilometers(double value) = _Kilometers;
  const factory Distance._miles(double value) = _Miles;

  factory Distance.fromMeters(double m) {
    if (m.isNaN || !m.isFinite || m < 0) {
      throw ArgumentError.value(m, 'm', 'Distance must be finite and non-negative');
    }
    return Distance._meters(m);
  }

  double get inMeters => switch (this) {
        _Meters(:final value) => value,
        _Kilometers(:final value) => value * 1000,
        _Miles(:final value) => value * 1609.344,
      };
  double get inKilometers => inMeters / 1000;
  double get inMiles => inMeters / 1609.344;
}
```

Entity:
```dart
@freezed
class WorkoutSet with _$WorkoutSet {
  const factory WorkoutSet({required Distance distance, required Duration duration}) = _WorkoutSet;
  const WorkoutSet._();
  double? get paceSecondsPerKm => duration.inSeconds / distance.inKilometers;
  double? get speedKmh => distance.inKilometers / (duration.inSeconds / 3600);
}
```

## Money

```dart
enum Currency { usd, eur, gbp, sar }

@Freezed(map: FreezedMapOptions.none, when: FreezedWhenOptions.none)
sealed class Money with _$Money {
  const Money._();
  const factory Money({required int cents, required Currency currency}) = _Money;
  factory Money.usd(double dollars) => Money(cents: (dollars * 100).round(), currency: Currency.usd);

  double get asDouble => cents / 100;
  bool get isPositive => cents > 0;

  Money operator +(Money other) {
    assert(currency == other.currency);
    return Money(cents: cents + other.cents, currency: currency);
  }
}
```

Display = widget calls extension on the unwrapped value:
```dart
Text(order.total.asDouble.asCurrency(symbol: '\$'))
```

## Email (identity)

```dart
@Freezed(map: FreezedMapOptions.none, when: FreezedWhenOptions.none)
sealed class Email with _$Email {
  const Email._();
  const factory Email._raw(String value) = _Email;

  factory Email(String input) {
    final t = input.trim().toLowerCase();
    if (!_pattern.hasMatch(t)) throw const FormatException('Invalid email');
    return Email._raw(t);
  }
  static final _pattern = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');
}
```

`User({required Email email})` — invalid string impossible.

## Non-empty text

```dart
@Freezed(map: FreezedMapOptions.none, when: FreezedWhenOptions.none)
sealed class DisplayName with _$DisplayName {
  const DisplayName._();
  const factory DisplayName._raw(String value) = _DisplayName;

  factory DisplayName(String input) {
    final trimmed = input.trim();
    if (trimmed.isEmpty) {
      throw ArgumentError.value(input, 'input', 'DisplayName cannot be blank');
    }
    return DisplayName._raw(trimmed);
  }

  String get value => switch (this) {
        _DisplayName(:final value) => value,
      };
}
```

No `@Default('') String name` in domain entities. Required text uses a VO;
optional text uses `String?`.

## Decision matrix

| Situation | Use |
|---|---|
| `m / 1000` once in 1 entity | Entity getter |
| `m → km` in 3 entities | `Distance` VO |
| `cents / 100` in widget | `cents.asCurrency()` extension |
| `cents + cents` math in domain | `Money` VO with `operator +` |
| Email validated at form | `Validators.email` |
| Email enforced via type | `Email` VO |
| Date format in widget | `date.formatted()` extension |
| Date diff in domain | built-in `Duration` (it IS a VO) |

## Forbidden

```dart
// ❌ extension import in domain
import 'package:myapp/core/extensions/num_extensions.dart'; // arch_domain_import ERROR

// ❌ primitive obsession
class Order {
  final int totalCents;
  final String customerEmail;
  final double weightKg;
}

// ✅ VO boundary
class Order {
  final Money total;
  final Email customerEmail;
  final Weight weight;
}

// ❌ public raw VO constructor — caller skips invariants (vo_public_raw_constructor)
@Freezed(map: FreezedMapOptions.none, when: FreezedWhenOptions.none)
sealed class Distance with _$Distance {
  const Distance._();
  const factory Distance.meters(double value) = _Meters;
}

// ❌ passthrough factory — looks compliant, still skips validation (vo_public_raw_constructor)
@Freezed(map: FreezedMapOptions.none, when: FreezedWhenOptions.none)
sealed class Distance with _$Distance {
  const Distance._();
  const factory Distance._meters(double value) = _Meters;
  factory Distance.meters(double value) => Distance._meters(value);  // zero-touch forward
}

// ✅ private raw redirect + public factory with EXPLICIT guards in body
@Freezed(map: FreezedMapOptions.none, when: FreezedWhenOptions.none)
sealed class Distance with _$Distance {
  const Distance._();
  const factory Distance._meters(double value) = _Meters;
  factory Distance.fromMeters(double m) {
    if (m.isNaN) throw ArgumentError.value(m, 'm', 'Distance cannot be NaN');
    if (!m.isFinite) throw ArgumentError.value(m, 'm', 'Distance must be finite');
    if (m < 0) throw ArgumentError.value(m, 'm', 'Distance cannot be negative');
    return Distance._meters(m);
  }
}

// ✅ extracted guard helper — still validates, lint passes (body is function call, not bare arg)
@Freezed(map: FreezedMapOptions.none, when: FreezedWhenOptions.none)
sealed class Distance with _$Distance {
  const Distance._();
  const factory Distance._meters(double value) = _Meters;
  factory Distance.meters(double v) => Distance._meters(_guard(v, 'meters'));
  static double _guard(double v, String unit) {
    if (v.isNaN || !v.isFinite || v < 0) {
      throw ArgumentError.value(v, 'v', 'Distance.$unit must be finite and non-negative');
    }
    return v;
  }
}

// ❌ named primitive factory on domain entity — boundary in wrong layer (domain_entity_primitive_factory)
// (entity, not VO — bare `@freezed` is fine here; opt-out only required in /domain/values/)
@freezed
sealed class User with _$User {
  const factory User({required Email email}) = _User;
  factory User.fromPrimitives(String emailString) => User(email: Email(emailString));
}

// ✅ convert primitives at data/notifier/import boundary; entity accepts VOs only
@freezed
sealed class User with _$User {
  const factory User({required Email email}) = _User;
}
// inside UserModel.toEntity() or UserImportService — outside /domain/:
//   User(email: Email(json['email'] as String))

// ❌ hand-rolled copyWith in /domain/ (domain_custom_copy_with)
@freezed
sealed class User with _$User {
  const User._();
  const factory User({required String id, required Email email}) = _User;
  User copyWith({String? id, Email? email}) => User(id: id ?? this.id, email: email ?? this.email);
}

// ✅ let Freezed generate copyWith from the redirect — change the constructor if the API is wrong
@freezed
sealed class User with _$User {
  const User._();
  const factory User({required String id, required Email email}) = _User;
}
```

### Hive collision

Disk sacred. `hive_ce_generator` writes `HiveField(N)` indices to `hive_adapters.g.yaml` (committed) from Freezed ctor param order on first run. Wrapping a primitive in a VO on a `@GenerateAdapters`-registered class regenerates that yaml against the new shape — different binary layout from the one on user disks. `dart analyze` blind. Per the [hive_ce docs](https://github.com/IO-Design-Team/hive_ce_docs/blob/master/custom-objects/generate_adapters.md): *"Changing the type of a field is not supported. You should create a new one instead."*

**Option A — entity stays primitive, VO via getter.** Use when entity shipped w/ user data.

```dart
@freezed
sealed class WorkoutSet with _$WorkoutSet {
  const WorkoutSet._();
  const factory WorkoutSet({
    required String id,
    /// HiveField(1)
    required double distanceMeters,  // locked
    /// HiveField(2)
    required int durationSeconds,    // locked
  }) = _WorkoutSet;
  Distance get distance => Distance.fromMeters(distanceMeters);
  Duration get duration => Duration(seconds: durationSeconds);
}
```

**Option B — separate Model (Hive) + Entity (VOs) + mapper.** Use for new entities.

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
@GenerateAdapters([AdapterSpec<WorkoutSetModel>()], firstTypeId: 1) void _h() {}

// /domain/entities/workout_set.dart
@freezed
sealed class WorkoutSet with _$WorkoutSet {
  const factory WorkoutSet({required String id, required Distance distance, required Duration duration}) = _WorkoutSet;
}

// /data/mappers/workout_set_mapper.dart
extension WorkoutSetMapper on WorkoutSetModel {
  WorkoutSet toEntity() => WorkoutSet(id: id, distance: Distance.fromMeters(distanceMeters), duration: Duration(seconds: durationSeconds));
}
```

Forbidden either option: reorder ctor params on `@GenerateAdapters` class, renumber/reuse `HiveField(N)`, reuse retired `typeId`. See [hive-persistence.md](hive-persistence.md).

Lints: `hive_field_no_vo_type` (no VO types on Model ctor params).

## Test

```dart
group('Distance', () {
  test('rejects negative', () => expect(() => Distance.fromMeters(-1), throwsA(isA<AssertionError>())));
  test('m → km', () => expect(Distance.meters(1500).inKilometers, 1.5));
  test('miles roundtrip', () => expect(Distance.miles(1).inKilometers, closeTo(1.609344, 1e-9)));
});
```

## Related

- Rule 11: extensions outer only. Domain blocked.
- Rule 12: this. VO in `/domain/`.
- Rule 7: multi-unit VO = sealed Freezed. Match via native `switch`.
- Lint `arch_domain_import`: VOs in `/domain/` import freely.

## When NOT to VO

- No domain meaning (counters, UI flags)
- Form-boundary only (use `Validators`)
- Already a VO: `Duration`, `DateTime`, `Uri`

Over-VO = own anti-pattern. Apply when invariants exist OR primitive shared 2+ entities.
