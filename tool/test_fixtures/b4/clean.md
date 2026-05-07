# B4 Clean Fixture — keepAlive provider with no family arg is fine

```dart
@Riverpod(keepAlive: true)
Future<Config> appConfig(AppConfigRef ref) async {
  return await loadConfig();
}
```
