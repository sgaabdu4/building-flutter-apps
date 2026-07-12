# Extensions & Utilities

## Read first

1. Primitive ops live in `core/extensions/`; never inline repeated format/parse/math/string/date code.
2. Domain never imports `core/extensions/`; use entity getter or VO.
3. Widgets use context extensions (`context.colors`, `context.textTheme`, `context.isCurrentModalRoute`, etc.).
4. Notifiers/services own snackbars; widgets call notifier methods, not `ScaffoldMessenger`.
5. Search/API inputs use `Debouncer` (500ms min).

## Trigger

Signals: SnackBarUtils, context extensions, Debouncer, Validators, extension types, Result type, **any** `DateTime` / `String` / `int` / `double` / `num` / `Duration` formatting / parsing / arithmetic / capitalize / titleCase / truncate / initials / timeAgo / diff / startOfDay / endOfDay / isToday / clamped / pluralized / asCurrency / percent / toFixed / inWords / `NumberFormat` / `DateFormat` / locale-format.
Before code: output `Reading: extensions-utilities.md`

## SSOT rule

Primitive manipulation lives in `core/extensions/`. NEVER inline at call site. Authoritative in [SKILL.md → Critical Rule 11](../SKILL.md#critical-rules).

> **Domain NEVER imports `core/extensions/`.** Outer dep — `arch_domain_import` ERROR. Domain math: entity getter (one-off) OR VO (cross-entity). See [value-objects.md](value-objects.md) + [SKILL.md → Rule 12](../SKILL.md#critical-rules).

### Forbidden inline → use extension

| Forbidden inline                                        | Use                          |
|---------------------------------------------------------|------------------------------|
| `'${s[0].toUpperCase()}${s.substring(1)}'`              | `s.capitalized`              |
| `s.split(' ').map(...).join(' ')` for title case        | `s.titleCase`                |
| `s.length > n ? '${s.substring(0,n)}...' : s`           | `s.truncate(n)`              |
| `DateTime.now().difference(date)` for relative time     | `date.timeAgo`               |
| `DateTime.now().toUtc()` / `DateTime.timestamp()`       | `DateTimeX.nowUtc()`         |
| `DateTimeX.nowLocal().startOfDay`                       | `DateTimeX.nowLocalStartOfDay()` |
| `DateTimeX.nowLocal().calendarDaysBefore(60)`           | semantic `DateTimeX` helper  |
| `DateTime(d.year, d.month, d.day)` for day boundary     | `d.startOfDay` / `d.endOfDay`|
| Manual `year == now.year && month == ...` for today     | `d.isToday` / `d.isYesterday`|
| `NumberFormat.currency(...).format(amount)` ad-hoc      | `amount.asCurrency()`        |
| `DateFormat('MM/dd').format(date)` or `date.formatted(pattern: 'MM/dd')` | semantic `DateTime` getter owned by `date_time_extensions.dart` |
| `(value * 100).toStringAsFixed(n) + '%'`                | `value.asPercent(n)`         |
| `value.clamp(lo, hi)` repeated at call site             | `value.clamped(lo, hi)`      |
| `count == 1 ? 'item' : 'items'`                         | `count.pluralized('item')`   |
| `items.indexBy((item) => item.id)[id]` for one-off lookup | `items.lookupByKey(id, (item) => item.id)` |
| `items.indexPositionsBy((item) => item.id)[id] ?? -1`    | `items.indexOfByKey(id, (item) => item.id)` |
| `Theme.of(context).colorScheme` / `MediaQuery.sizeOf(context)` | `context.colors` / `context.screenSize` |
| `ModalRoute.of(context)?.isCurrent` / `ModalRoute.isCurrentOf(context)` | `context.isCurrentModalRoute` |
| Raw key/id/limit/threshold literals                     | named constants, VOs, or semantic helpers |

Missing case? Add to extension file in `core/extensions/`, export in barrel, then call. Don't inline "just this once".


## Context Extensions

```dart
// core/extensions/context_extensions.dart
extension ContextExtensions on BuildContext {
  ThemeData get theme => Theme.of(this);
  TextTheme get textTheme => Theme.of(this).textTheme;
  ColorScheme get colors => Theme.of(this).colorScheme;

  Size get screenSize => MediaQuery.sizeOf(this);
  EdgeInsets get padding => MediaQuery.paddingOf(this);
  EdgeInsets get viewInsets => MediaQuery.viewInsetsOf(this);
  double get screenWidth => MediaQuery.sizeOf(this).width;
  double get screenHeight => MediaQuery.sizeOf(this).height;
  bool get isCurrentModalRoute {
    final isCurrent = ModalRoute.isCurrentOf(this);
    if (isCurrent == null) return true;
    return isCurrent;
  }

  bool get isCompact => screenWidth < 600;
  bool get isMedium => screenWidth >= 600 && screenWidth < 840;
  bool get isExpanded => screenWidth >= 840;
}
```

### Dialogs

Dialogs and sheets are local presentation helpers. Use named helpers for
semantic presentation, and return results through `Navigator.pop` from inside
the modal widget.

```dart
final l10n = context.l10n;
final confirmed = await showConfirmDialog(
  context: context,
  title: l10n.deleteTitle,
  message: l10n.deleteMessage,
);

if (confirmed) {
  await ref.read(itemsNotifierProvider.notifier).delete(id);
}
```

## String Extensions

```dart
// core/extensions/string_extensions.dart
extension StringExtensions on String {
  String get capitalized =>
      isEmpty ? this : '${this[0].toUpperCase()}${substring(1)}';

  String get titleCase =>
      split(' ').map((w) => w.capitalized).join(' ');

  String truncate(int maxLength, {String ellipsis = '...'}) =>
      length <= maxLength ? this : '${substring(0, maxLength)}$ellipsis';

  String get initials {
    final words = trim().split(RegExp(r'\s+'));
    if (words.isEmpty) return '';
    if (words.length == 1) return words[0][0].toUpperCase();
    return '${words[0][0]}${words[1][0]}'.toUpperCase();
  }
}
```

## DateTime Extensions

Current-time access belongs here too. Use `DateTimeX.nowUtc()` for
persisted/server timestamps and `DateTimeX.nowLocal()` for local UI calendar
logic. Current-day boundaries and repeated windows should be named helpers here
rather than inline `DateTimeX.nowLocal().startOfDay` or
`DateTimeX.nowLocal().calendarDaysBefore(60)` call sites.

```dart
// core/extensions/date_time_extensions.dart
abstract final class DateTimeX {
  static DateTime nowUtc() => DateTime.timestamp();
  static DateTime nowLocal() => nowUtc().toLocal();
  static DateTime nowLocalStartOfDay() => nowLocal().startOfDay;

  // Name repeated windows for the app/domain instead of inlining the number.
  static DateTime localHistoryWindowStart() =>
      nowLocalStartOfDay().calendarDaysBefore(60);
}

extension DateTimeExtensions on DateTime {
  bool get isToday {
    final now = DateTimeX.nowLocal();
    return year == now.year && month == now.month && day == now.day;
  }

  bool get isYesterday {
    final y = DateTimeX.nowLocal().calendarDaysBefore(1);
    return year == y.year && month == y.month && day == y.day;
  }

  DateTime get startOfDay => DateTime(year, month, day);
  DateTime get endOfDay => DateTime(year, month, day, 23, 59, 59);

  // Calendar days preserve local wall-clock time across DST transitions.
  // Use add/subtract(Duration) only for elapsed-time arithmetic.
  DateTime calendarDaysBefore(int days) => _copyWithCalendarDay(day - days);
  DateTime calendarDaysAfter(int days) => _copyWithCalendarDay(day + days);

  DateTime _copyWithCalendarDay(int calendarDay) {
    if (isUtc) {
      return DateTime.utc(
        year,
        month,
        calendarDay,
        hour,
        minute,
        second,
        millisecond,
        microsecond,
      );
    }
    return DateTime(
      year,
      month,
      calendarDay,
      hour,
      minute,
      second,
      millisecond,
      microsecond,
    );
  }

  String get timeAgo {
    final diff = DateTimeX.nowLocal().difference(toLocal());
    if (diff.inSeconds < 60) return 'just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    if (diff.inDays < 7) return '${diff.inDays}d ago';
    if (diff.inDays < 30) return '${diff.inDays ~/ 7}w ago';
    if (diff.inDays < 365) return '${diff.inDays ~/ 30}mo ago';
    return '${diff.inDays ~/ 365}y ago';
  }

  /// Locale format via `intl`. Keep raw pattern literals inside this file or
  /// pass a named constant from a dedicated owner.
  String formatted({String pattern = 'yMMMd', String? locale}) =>
      DateFormat(pattern, locale).format(this);

  String get asDate => formatted(pattern: 'yMMMd');
  String get asTime => formatted(pattern: 'jm');
  String get asDateTime => formatted(pattern: 'yMMMd jm');
}
```

Pattern reference: `intl` `DateFormat`. Skill convention — date display call sites use semantic getters (`.asDate`, `.asTime`, product-specific compact date getters, etc.). Never inline `DateFormat(...)` or `.formatted(pattern: ...)` at widget/notifier sites.

## Int Extensions

```dart
// core/extensions/int_extensions.dart
extension IntExtensions on int {
  /// Pluralize: `1.pluralized('item') == '1 item'`, `3.pluralized('item') == '3 items'`.
  /// Pass explicit plural for irregular nouns: `2.pluralized('child', plural: 'children')`.
  String pluralized(String singular, {String? plural}) =>
      this == 1 ? '$this $singular' : '$this ${plural ?? '${singular}s'}';

  int clamped(int lo, int hi) => clamp(lo, hi) as int;

  Duration get days => Duration(days: this);
  Duration get hours => Duration(hours: this);
  Duration get minutes => Duration(minutes: this);
  Duration get seconds => Duration(seconds: this);
  Duration get milliseconds => Duration(milliseconds: this);

  /// `1234567.compact == '1.2M'`. Wrap `NumberFormat.compact()`.
  String get compact => NumberFormat.compact().format(this);
}
```

Usage:

```dart
Text(items.length.pluralized('result'))                 // "3 results"
Future.delayed(300.milliseconds, ...)
final retries = attempts.clamped(0, 5);
```

## Double / Num Extensions

```dart
// core/extensions/double_extensions.dart
extension DoubleExtensions on double {
  /// Locale currency. Default project locale via `Intl.defaultLocale`.
  String asCurrency({String? locale, String? symbol, int decimals = 2}) =>
      NumberFormat.currency(locale: locale, symbol: symbol, decimalDigits: decimals)
          .format(this);

  /// `0.875.asPercent() == '88%'`, `0.875.asPercent(1) == '87.5%'`.
  String asPercent([int decimals = 0]) =>
      '${(this * 100).toStringAsFixed(decimals)}%';

  double clamped(double lo, double hi) => clamp(lo, hi) as double;

  /// Fixed-decimal string without trailing zeros: `3.10.toFixed(2) == '3.10'`.
  String toFixed(int decimals) => toStringAsFixed(decimals);
}

extension NumExtensions on num {
  /// Locale decimal: `1234567.89.formatted() == '1,234,567.89'`.
  String formatted({String? locale, int? decimals}) {
    final fmt = NumberFormat.decimalPattern(locale);
    if (decimals != null) {
      fmt
        ..minimumFractionDigits = decimals
        ..maximumFractionDigits = decimals;
    }
    return fmt.format(this);
  }
}
```

Usage:

```dart
Text(total.asCurrency(symbol: '\$'))     // "$1,299.00"
Text(progress.asPercent(1))              // "87.5%"
Text(score.clamped(0.0, 100.0).toFixed(1))
```

## Duration Extensions

```dart
// core/extensions/duration_extensions.dart
extension DurationExtensions on Duration {
  /// Human-readable: `2h 15m`, `45s`. Drops zero leading units.
  String get inWords {
    if (inDays > 0) return '${inDays}d ${inHours.remainder(24)}h';
    if (inHours > 0) return '${inHours}h ${inMinutes.remainder(60)}m';
    if (inMinutes > 0) return '${inMinutes}m ${inSeconds.remainder(60)}s';
    return '${inSeconds}s';
  }

  /// Stopwatch-style `mm:ss` or `hh:mm:ss`.
  String get clock {
    final h = inHours;
    final m = inMinutes.remainder(60).toString().padLeft(2, '0');
    final s = inSeconds.remainder(60).toString().padLeft(2, '0');
    return h > 0 ? '$h:$m:$s' : '$m:$s';
  }
}
```

## Iterable Extensions

Overlap `package:collection`. Extensions skip dep + import conflicts.

```dart
// core/extensions/iterable_extensions.dart
extension IterableExtensions<T> on Iterable<T> {
  T? firstWhereOrNull(bool Function(T) test) {
    for (final element in this) {
      if (test(element)) return element;
    }
    return null;
  }

  Map<K, List<T>> groupBy<K>(K Function(T) key) {
    final map = <K, List<T>>{};
    for (final element in this) {
      (map[key(element)] ??= []).add(element);
    }
    return map;
  }
}
```

## Widget List Extensions

```dart
// core/extensions/widget_extensions.dart
extension WidgetListExtensions on List<Widget> {
  List<Widget> separatedBy(Widget separator) {
    if (length <= 1) return this;
    return [
      for (int i = 0; i < length; i++) ...[
        if (i > 0) separator,
        this[i],
      ],
    ];
  }
}
```

Usage:

```dart
Column(
  children: [
    const FieldA(),
    const FieldB(),
    const FieldC(),
  ].separatedBy(const SizedBox(height: Spacing.s16)),
)
```

## SnackBar Utility

Boundary rule (notifier/service owns snackbar; widgets dispatch only) =
authoritative in [SKILL.md → Snackbar boundary](../SKILL.md). This section
ships the impl; rule repeated only in passing.

Central context-free snackbar.

### Class

```dart
// core/utils/snack_bar_utils.dart
abstract final class SnackBarUtils {

  static GlobalKey<ScaffoldMessengerState>? _key;

  static void initialize(GlobalKey<ScaffoldMessengerState> key) {
    _key = key;
  }

  static void showSuccess(String message) =>
      _show(message, type: SnackBarType.success);

  static void showError(String message) =>
      _show(message, type: SnackBarType.error);

  static void showInfo(String message) =>
      _show(message, type: SnackBarType.info);

  static void showWarning(String message) =>
      _show(message, type: SnackBarType.warning);

  static void hide() => _key?.currentState?.hideCurrentSnackBar();

  static void _show(String message, {required SnackBarType type}) {
    final state = _key?.currentState;
    if (state == null) return;

    state
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: SnackBarContent(message: message, type: type),
        backgroundColor: Colors.transparent,
        elevation: 0,
        behavior: SnackBarBehavior.floating,
        padding: EdgeInsets.zero,
        margin: const EdgeInsets.symmetric(
          horizontal: Spacing.s16,
          vertical: Spacing.s16,
        ),
        dismissDirection: DismissDirection.horizontal,
      ));
  }
}

enum SnackBarType { success, error, info, warning }
```

### Styled Content

Tweak `SnackBarContent` to match design system. `SemanticColors` for type border/icon, `Radii.rounded12` for radius, `context.textTheme.bodyMedium` for text. `@visibleForTesting` — public only so widget tests can pump `SnackBarContent` direct without going through `ScaffoldMessenger`:

```dart
@visibleForTesting
class SnackBarContent extends StatelessWidget {
  const SnackBarContent({super.key, required this.message, required this.type});

  final String message;
  final SnackBarType type;

  @override
  Widget build(BuildContext context) {
    final (icon, borderColor) = switch (type) {
      SnackBarType.success => (Icons.check_circle_rounded, SemanticColors.success),
      SnackBarType.error   => (Icons.error_rounded, SemanticColors.error),
      SnackBarType.info    => (Icons.info_rounded, SemanticColors.info),
      SnackBarType.warning => (Icons.warning_rounded, SemanticColors.warning),
    };

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: Spacing.s16, vertical: Spacing.s12),
      decoration: BoxDecoration(
        color: context.colors.surface,
        borderRadius: Radii.rounded12,
        border: Border.all(color: borderColor),
      ),
      child: Row(
        children: [
          Container(
            width: 32, height: 32,
            decoration: BoxDecoration(color: borderColor, shape: BoxShape.circle),
            child: Icon(icon, color: Colors.white, size: 18),
          ),
          const SizedBox(width: Spacing.s12),
          Expanded(
            child: Text(message, style: context.textTheme.bodyMedium, maxLines: 3, overflow: TextOverflow.ellipsis),
          ),
          GestureDetector(onTap: SnackBarUtils.hide, child: const Icon(Icons.close, size: IconSizes.s20)),
        ],
      ),
    );
  }
}
```

### Wiring

```dart
final _scaffoldKey = GlobalKey<ScaffoldMessengerState>();

void main() {
  SnackBarUtils.initialize(_scaffoldKey);
  runApp(
    ProviderScope(
      child: MaterialApp.router(
        scaffoldMessengerKey: _scaffoldKey,
        routerConfig: router,
      ),
    ),
  );
}
```

### Usage

Notifier/service code owns success/error side effects. Widgets/screens do not call snackbar utilities directly.

```dart
// WRONG — widget bypasses notifier boundary.
onPressed: () => SnackBarUtils.showInfo('Syncing...');
```

Widget callbacks should only dispatch:

```dart
onPressed: () => ref.read(productProvider.notifier).deleteProduct(id);
```

## Debouncer

Timer debouncer. Search, validation, auto-save. See [common-patterns.md](common-patterns.md) for `SearchNotifier` usage.

```dart
// core/utils/debouncer.dart
class Debouncer {
  Debouncer({this.duration = const Duration(milliseconds: 500)});

  final Duration duration;
  Timer? _timer;

  void call(VoidCallback action) {
    _timer?.cancel();
    _timer = Timer(duration, action);
  }

  void cancel() => _timer?.cancel();

  void dispose() {
    _timer?.cancel();
    _timer = null;
  }
}
```

## Validators

Composable form field validation:

```dart
// core/utils/validators.dart
abstract final class Validators {
  static final _emailRegex = RegExp(r'^[\w-\.]+@([\w-]+\.)+[\w-]{2,4}$');

  static String? required(String? value) =>
      (value == null || value.trim().isEmpty) ? 'Required' : null;

  static String? email(String? value) {
    if (value == null || value.isEmpty) return 'Required';
    if (!_emailRegex.hasMatch(value)) return 'Invalid email';
    return null;
  }

  static String? Function(String?) minLength(int min) => (String? value) {
        if (value == null || value.length < min) return 'Min $min characters';
        return null;
      };

  /// Chain validators: `Validators.compose([Validators.required, Validators.email])`
  static String? Function(String?) compose(List<String? Function(String?)> validators) =>
      (String? value) {
        for (final v in validators) {
          final error = v(value);
          if (error != null) return error;
        }
        return null;
      };
}
```

## Result Type

Typed success/failure wrapper. Freezed sealed class:

```dart
// core/domain/result.dart
@freezed
sealed class Result<T> with _$Result<T> {
  const factory Result.success(T data) = Success<T>;
  const factory Result.failure(String message, [Object? error]) = Failure<T>;
}
```

```dart
switch (result) {
  case Success(:final data):
    state = state.copyWith(user: data);
  case Failure(:final message):
    state = state.copyWith(error: message);
}
```

## Extension Types

Zero-cost compile-time wrappers (Dart 3.3). See [dart-patterns-records.md](dart-patterns-records.md#extension-types-dart-3.3) for full ref.

```dart
extension type UserId(String value) {}
extension type ProductId(String value) {}

void deleteProduct(ProductId id) { /* ... */ }
deleteProduct(UserId('u1'));    // compile-time ERROR
deleteProduct(ProductId('p1')); // OK
```

Use for entity IDs, units, currencies. NEVER raw `String`/`int` when multiple ID types coexist.

## Barrel Export

```dart
// core/extensions/extensions.dart
export 'context_extensions.dart';
export 'string_extensions.dart';
export 'date_time_extensions.dart';
export 'int_extensions.dart';
export 'double_extensions.dart';
export 'duration_extensions.dart';
export 'iterable_extensions.dart';
export 'widget_extensions.dart';
```
