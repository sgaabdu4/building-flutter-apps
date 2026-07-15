# Extensions — Collections And Helpers

## Read first

1. Repeated lookup/indexing belongs in reusable indexes, computed providers, or shared collection extensions.
2. One-off call-site lookup uses `lookupByKey` / `indexOfByKey`; never local helpers, `firstWhere`, or `indexWhere` in hot paths.
3. Debouncers, validators, `Result`, and extension types are shared helpers, not widget-file globals.

## Trigger

Signals: `Iterable`, lookup by id, indexing, widget list spacing helpers, `Debouncer`, validators, `Result`, extension types, `extensions.dart` export.
Before code: output `Reading: collections-helpers.md`.

## Iterable lookup

```dart
extension IterableLookupX<T> on Iterable<T> {
  T? lookupByKey<K>(K key, K Function(T item) keyOf) {
    for (final item in this) {
      if (keyOf(item) == key) return item;
    }
    return null;
  }

  Map<K, T> indexOfByKey<K>(K Function(T item) keyOf) {
    return {for (final item in this) keyOf(item): item};
  }
}
```

Use a cached index for repeated lookups:

```dart
final productsById = state.products.indexOfByKey((product) => product.id);
```

Lints: `ad_hoc_id_index_lookup`, `linear_id_lookup_in_hot_path`, `nested_linear_lookup_by_id`.

## Widget list helpers

Keep small layout helpers in extension owners, not top-level widget helpers:

```dart
extension WidgetListX on List<Widget> {
  List<Widget> separatedBy(Widget separator) {
    return [
      for (final (index, child) in indexed) ...[
        if (index > 0) separator,
        child,
      ],
    ];
  }
}
```

## Debouncer

```dart
final class Debouncer {
  Debouncer(this.duration);

  final Duration duration;
  Timer? _timer;

  void call(VoidCallback action) {
    _timer?.cancel();
    _timer = Timer(duration, action);
  }

  void dispose() => _timer?.cancel();
}
```

Register disposal with `ref.onDispose(debouncer.dispose)` or widget `dispose()`.

## Validators

Validators normalize blank optional text to `null` at boundaries and return typed validation errors, not user-facing strings. UI maps errors to localized `AppLocalizations`.

## Result

Use `Result<T, E>` only at boundaries where exceptions are intentionally converted to typed outcomes. Do not hide programming errors behind `Result`.

## Extension types

Use extension types for zero-cost typed IDs when Freezed Value Objects are too heavy and no serialization behavior is needed:

```dart
extension type ProductId(String value) {}
```

For domain text with validation, prefer a Freezed Value Object.

## Barrel export

Export extension owners from `core/extensions/extensions.dart`; do not import individual extension files throughout feature code.
