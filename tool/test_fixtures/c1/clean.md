# C1 Clean Fixture

```dart
Future<void> submit() async {
  final data = await ref.read(apiProvider).post(payload);
  if (!ref.mounted) return;
  state = AsyncData(data);
}
```
