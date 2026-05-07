# V11 Clean Fixture — runZonedGuarded with legacy context nearby

<!-- NOTE: runZonedGuarded is a legacy pattern. Prefer PlatformDispatcher.instance.onError. -->

```dart
runZonedGuarded(() async {
  await Firebase.initializeApp();
  runApp(const MyApp());
}, (error, stack) {
  FirebaseCrashlytics.instance.recordError(error, stack, fatal: true);
});
```
