# Value Objects

Wrap domain primitives in sealed Freezed classes. Kills primitive obsession. Sidesteps `arch_domain_import`.

## Trigger

Signals: `Distance`, `Money`, `Email`, `Username`, `Slug`, `PhoneNumber`, `HeartRate`, `Weight`, `Pace`, unit conversion in domain, currency math in domain, bare `double distanceMeters` / `int amountCents` / `String email` at entity boundary, `arch_domain_import` fighting `core/extensions/` import.

Before code: output verbatim `Reading: value-objects.md`

## Why

Domain inner, `core/extensions/` outer. Dependency Rule: inner never depend on outer. Lint `arch_domain_import` (ERROR) blocks. Three options:

| Scope | Use |
|---|---|
| 1 entity, 1 derivation | Entity getter |
| 2+ entities share primitive concept | **Value Object** in `/domain/value_objects/` |
| Only widgets/notifiers/repos use it | `core/extensions/` |

VO wins: lives in `/domain/` (lint pass), encodes invariants, type-safe API, unit conversions as getters.

## Where

- Feature: `lib/features/<x>/domain/value_objects/<name>.dart`
- Shared: `lib/core/domain/value_objects/<name>.dart`

Both match `/domain/` → both allowed.

## Distance

```dart
// lib/core/domain/value_objects/distance.dart
import 'package:freezed_annotation/freezed_annotation.dart';
part 'distance.freezed.dart';

@freezed
sealed class Distance with _$Distance {
  const Distance._();
  const factory Distance.meters(double value) = _Meters;
  const factory Distance.kilometers(double value) = _Kilometers;
  const factory Distance.miles(double value) = _Miles;

  factory Distance.fromMeters(double m) {
    assert(m >= 0, 'Distance cannot be negative');
    return Distance.meters(m);
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

@freezed
class Money with _$Money {
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
@freezed
class Email with _$Email {
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
```

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
