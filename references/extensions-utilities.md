# Extensions & Utilities

Context/type extensions + utilities. Kill boilerplate. Snackbars use `SnackBarUtils`, not `ScaffoldMessenger.of(context)`.

**Contents:** [Context Extensions](#context-extensions) | [String Extensions](#string-extensions) | [DateTime Extensions](#datetime-extensions) | [Iterable Extensions](#iterable-extensions) | [Widget List Extensions](#widget-list-extensions) | [SnackBar Utility](#snackbar-utility) | [Debouncer](#debouncer) | [Validators](#validators) | [Result Type](#result-type) | [Extension Types](#extension-types) | [Barrel Export](#barrel-export)

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

  bool get isCompact => screenWidth < 600;
  bool get isMedium => screenWidth >= 600 && screenWidth < 840;
  bool get isExpanded => screenWidth >= 840;
}
```

### Dialogs

```dart
extension ContextDialogs on BuildContext {
  Future<bool> showConfirmDialog({
    required String title,
    required String message,
    String confirmLabel = 'Confirm',
    String cancelLabel = 'Cancel',
  }) async {
    final result = await showDialog<bool>(
      context: this,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(cancelLabel),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(confirmLabel),
          ),
        ],
      ),
    );
    return result ?? false;
  }
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

```dart
// core/extensions/date_time_extensions.dart
extension DateTimeExtensions on DateTime {
  bool get isToday {
    final now = DateTime.now();
    return year == now.year && month == now.month && day == now.day;
  }

  bool get isYesterday {
    final y = DateTime.now().subtract(const Duration(days: 1));
    return year == y.year && month == y.month && day == y.day;
  }

  DateTime get startOfDay => DateTime(year, month, day);
  DateTime get endOfDay => DateTime(year, month, day, 23, 59, 59);

  String get timeAgo {
    final diff = DateTime.now().difference(this);
    if (diff.inSeconds < 60) return 'just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    if (diff.inDays < 7) return '${diff.inDays}d ago';
    if (diff.inDays < 30) return '${diff.inDays ~/ 7}w ago';
    if (diff.inDays < 365) return '${diff.inDays ~/ 30}mo ago';
    return '${diff.inDays ~/ 365}y ago';
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

Central context-free snackbar. Notifiers/services dispatch snackbar side effects. Widgets/screens call notifier methods and render state; they do not call `SnackBarUtils.show*` or `ScaffoldMessenger.of(context)` directly.

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

Zero-cost compile-time wrappers (Dart 3.3). See [dart-patterns-records.md](dart-patterns-records.md#extension-types-dart-33) for full ref.

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
export 'iterable_extensions.dart';
export 'widget_extensions.dart';
```
