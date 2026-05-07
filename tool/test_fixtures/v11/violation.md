# V11 Violation Fixture

```dart
runZonedGuarded(() async {
  await Firebase.initializeApp();
  runApp(const MyApp());
}, (error, stack) {
  FirebaseCrashlytics.instance.recordError(error, stack, fatal: true);
});
```
