# A4-freezed Violation Fixture

```dart
@freezed
class CartState with _$CartState {
  const factory CartState({
    required List<Item> items,
    String? error,
  }) = _CartState;
}
```
