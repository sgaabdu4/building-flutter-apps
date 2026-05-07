# A4-freezed Clean Fixture — use sealed union instead

```dart
@freezed
sealed class CartState with _$CartState {
  const factory CartState.data(List<Item> items) = CartData;
  const factory CartState.error(Object error, StackTrace st) = CartError;
  const factory CartState.loading() = CartLoading;
}
```
