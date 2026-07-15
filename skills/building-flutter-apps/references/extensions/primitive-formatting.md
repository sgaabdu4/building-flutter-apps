# Extensions — Primitive Formatting

## Read first

1. Primitive formatting lives in `core/extensions/`; call sites use semantic extension getters/methods.
2. Persist/server timestamps in UTC; local calendar buckets convert to local before bucketing.
3. Domain entities do not import `core/extensions/`; use entity getters or Value Objects in domain.

## Trigger

Signals: `DateTime`, `String`, `int`, `double`, `num`, `Duration`, `NumberFormat`, `DateFormat`, `intl`, capitalization, currency, percent, clamp.
Before code: output `Reading: primitive-formatting.md`.

## DateTime

Use semantic helpers, not ad-hoc formatting at call sites:

```dart
extension DateTimeX on DateTime {
  static DateTime nowUtc() => DateTime.now().toUtc();
  static DateTime nowLocal() => DateTime.now();

  DateTime get localDayStart {
    final local = toLocal();
    return DateTime(local.year, local.month, local.day);
  }

  String formatShortDate(AppLocalizations l10n) {
    return DateFormat.yMMMd(l10n.localeName).format(toLocal());
  }
}
```

Forbidden at call sites: raw `DateTime.now()` chains, ad-hoc `DateFormat`, inline `.formatted(pattern: ...)`.

Lint: `datetime_now_requires_timezone_intent`.

## String

```dart
extension StringX on String {
  String get capitalized => isEmpty ? this : '${this[0].toUpperCase()}${substring(1)}';
  String truncate(int maxLength) => length <= maxLength ? this : '${substring(0, maxLength)}...';
}
```

Required domain strings are Value Objects, not raw `String` with empty sentinels.

## Number formatting

```dart
extension NumX on num {
  String asCurrency(AppLocalizations l10n, {String? symbol}) {
    return NumberFormat.currency(locale: l10n.localeName, symbol: symbol).format(this);
  }

  num clamped(num min, num max) => clamp(min, max);
}
```

Forbidden at call sites: ad-hoc `NumberFormat`, inline `.clamp(...)`, raw executable magic numbers.

## Duration

```dart
extension DurationX on Duration {
  String get compactLabel {
    final minutes = inMinutes.remainder(60).toString().padLeft(2, '0');
    return '$inHours:$minutes';
  }
}
```
