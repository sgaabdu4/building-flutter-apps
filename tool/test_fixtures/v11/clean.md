# V11 Clean Fixture

```dart
Future<void> main() async {
  await Firebase.initializeApp();
  await Crash.init();
  runApp(const MyApp());
}
```
