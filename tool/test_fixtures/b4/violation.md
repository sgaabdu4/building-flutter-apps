# B4 Violation Fixture

```dart
@Riverpod(keepAlive: true)
Future<List<Item>> itemList(ItemListRef ref, String userId) async {
  return await fetchItems(userId);
}
```
