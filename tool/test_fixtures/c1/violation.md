# C1 Violation Fixture

```dart
Future<void> submit() async {
  final data = await ref.read(apiProvider).post(payload);
  state = AsyncData(data);
}
```
