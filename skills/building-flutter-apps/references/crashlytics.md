# Firebase Crashlytics


## Read first

1. Keep `Crash` boring: direct static wrapper over `FirebaseCrashlytics.instance`.
2. Public API: `Crash.init()`, `Crash.log(...)`, `Crash.error(...)` only.
3. `Crash.init()` runs once in `main()` before `runApp`.
4. Feature code never imports/calls `FirebaseCrashlytics` directly.
5. No PII in `reason`, `message`, or `extras`.

## Trigger

Signals: Crashlytics, FirebaseCrashlytics, Crash.error, Crash.log, crash reporting.
Before code: output `Reading: crashlytics.md`.

## Do not add

- backend interfaces/classes
- debug injection seams
- global error hooks
- isolate listeners
- recoverable-error classifiers
- user/key setters
- remote-error suppression
- feature constants inside `crash_service.dart`

If extras need shared keys, put them in `core/constants/`.

## Minimal shape

```dart
abstract final class Crash {
  static bool _ready = false;

  static Future<void> init() async {
    try {
      if (Firebase.apps.isEmpty) {
        await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
      }
      await FirebaseCrashlytics.instance.setCrashlyticsCollectionEnabled(true);
      _ready = true;
    } on Object catch (error, stackTrace) {
      debugPrint('Crash.init failed: $error\n$stackTrace');
    }
  }

  static void log(String message, {Map<String, Object?> extras = const {}}) {
    final text = extras.isEmpty ? message : '$message $extras';
    debugPrint(text);
    if (!_ready) return;
    _send(FirebaseCrashlytics.instance.log(text));
  }

  static void error(
    Object error,
    StackTrace stackTrace, {
    String? reason,
    bool fatal = false,
    Map<String, Object?> extras = const {},
  }) {
    final information = [for (final entry in extras.entries) '${entry.key}=${entry.value}'];
    debugPrint('${reason ?? 'Crash'}: $error\n$stackTrace');
    if (!_ready) return;
    _send(FirebaseCrashlytics.instance.recordError(
      error,
      stackTrace,
      reason: reason,
      fatal: fatal,
      information: information,
    ));
  }

  static void _send(Future<void> future) {
    unawaited(future.catchError((Object error, StackTrace stackTrace) {
      debugPrint('Crash send failed: $error\n$stackTrace');
    }));
  }
}
```

## `main.dart`

```dart
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Crash.init();
  runApp(const ProviderScope(child: App()));
}
```

## Call patterns

| Situation | Call |
|---|---|
| Notifier `catch` | `Crash.error(e, s, reason: 'Feature.load');` |
| Breadcrumb | `Crash.log('Feature.load.start', extras: {'count': items.length});` |
| Fatal manual report | `Crash.error(e, s, reason: 'Feature.delete', fatal: true);` |

## Testing

Smoke test only:

- `Crash.init()` does not throw on unsupported/test platform.
- `Crash.log(...)` does not throw.
- `Crash.error(...)` does not throw.

## Checklist

- [ ] `crash_service.dart` stays tiny
- [ ] Public API only `init`, `error`, `log`
- [ ] Firebase init in `Crash.init()`
- [ ] Direct `FirebaseCrashlytics.instance.recordError(error, stackTrace, ...)`
- [ ] No SDK imports outside `crash_service.dart`
- [ ] No global hook wiring unless explicitly requested
- [ ] No PII
