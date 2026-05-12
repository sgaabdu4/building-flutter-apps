# Firebase Crashlytics

Prod wiring. Pattern: backend interface + static facade. Handle platform gating, handler chaining, test seams, non-fatal classify.

## Trigger

Signals: Crashlytics, ICrashBackend, Crash.error, FlutterError.onError, crash reporting
Before generating code in this area, output verbatim: `Reading: crashlytics.md`


> **Swap providers (Sentry, Bugsnag, Datadog, self-hosted).** `ICrashBackend` = seam. New impl (`SentryCrashBackend implements ICrashBackend`), assign in `Crash.init()` instead of `FirebaseCrashBackend`. Facade API (`Crash.error`/`info`/`setUser`/`setKey`), handler chaining, `_isRecoverable`, test seams, every call site stay same. Multi-backend fan-out = `CompositeCrashBackend` forward each method to delegate list. **Never call provider SDK direct from feature code** — only from backend impl.

## Contents

- [Call-site policy](#call-site-policy)
- [Rules](#rules)
- [Backend interface](#backend-interface)
- [Facade — `abstract final class Crash`](#facade--abstract-final-class-crash)
- [Backends](#backends)
- [`main.dart`](#maindart)
- [Call patterns](#call-patterns)
- [Testing](#testing)
- [Obfuscated builds](#obfuscated-builds)
- [Extending the non-fatal classifier](#extending-the-non-fatal-classifier)
- [Checklist](#checklist)

## Call-site policy

`Crash.error` = notifier layer or app boundary (`FlutterError.onError` /
legacy `runZonedGuarded`, see §Rules) only. Datasources rethrow raw. Repos
may wrap into domain error, still rethrow. Notifier → `AppError` → state →
`Crash.error`. Single catch site per chain. Matches
[state-management.md](state-management.md#error-handling-strategy).

## Rules

1. **MUST** split: `abstract interface class ICrashBackend` + concrete backends (`FirebaseCrashBackend`, `ConsoleCrashBackend`) + static facade `abstract final class Crash`. Feature code call `Crash.x`.
2. **MUST** platform-gate. Web/desktop get console backend, not Firebase.
3. **MUST** chain handlers — preserve prior `FlutterError.onError` / `PlatformDispatcher.onError`, call too. Replace = hide framework logs.
4. **MUST** wire 3 hooks: `FlutterError.onError` (UI Flutter errors), `PlatformDispatcher.onError` (platform/async), `Isolate.current.addErrorListener` (bg isolates). `runZonedGuarded` = **legacy**, misses platform-channel errors, not recommended Flutter 3.3+. Three-hook pattern replaces it.
4. **MUST** classify recoverable exceptions non-fatal (RenderFlex overflow, handshake, past-date scheduling, plugin-missing). Else dashboard flood w/ fake fatals.
5. **MUST** expose `@visibleForTesting` seams: `debugUseBackend`, `debugReset`, `debugConfigure`. Tests swap fake backend — never init Firebase.
6. **MUST** `debugPrint` alongside every send so local dev see event.
7. **MUST** `unawaited(...)` non-fatal sends — caller never block.
8. **NEVER** PII in reasons, keys, breadcrumb extras.

## Backend interface

```dart
abstract interface class ICrashBackend {
  Future<void> log(String message);
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    bool fatal,
    String? reason,
    Iterable<Object> information,
  });
  Future<void> setUser(String? userId);
  Future<void> setKey(String key, Object? value);
  void crash(); // test-crash trigger
}
```

## Facade — `abstract final class Crash`

Static API feature code use. Hold active backend, install handlers, provide test seams.

```dart
abstract final class Crash {
  static ICrashBackend _backend = const ConsoleCrashBackend();
  static bool _isInitialized = false;
  static bool _handlersInstalled = false;
  static FlutterExceptionHandler? _prevFlutterHandler;
  static ErrorCallback? _prevPlatformHandler;
  static RawReceivePort? _isolatePort;

  /// Call once from main() before runApp.
  static Future<void> init() async {
    if (_isInitialized) return;
    if (!_supportsCrashlytics) {
      _isInitialized = true;
      return; // web/desktop: stay on console backend
    }
    try {
      if (Firebase.apps.isEmpty) {
        await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
      }
      final cl = FirebaseCrashlytics.instance;
      await cl.setCrashlyticsCollectionEnabled(true);
      _backend = FirebaseCrashBackend(cl);
      _installHandlers();
    } on Object catch (e, s) {
      FlutterError.reportError(FlutterErrorDetails(
        exception: e, stack: s, library: 'Crash.init',
      ));
      unawaited(const ConsoleCrashBackend().recordError(e, s, reason: 'Crash.init'));
    } finally {
      _isInitialized = true;
    }
  }

  static void info(String message, {Map<String, Object?> extras = const {}}) {
    unawaited(_backend.log(_formatMessage(message, extras)));
  }

  static void error(
    Object error,
    StackTrace stackTrace, {
    bool fatal = false,
    String? reason,
    Map<String, Object?> extras = const {},
  }) {
    final info = extras.entries
        .map((e) => '${e.key}=${_normalize(e.value)}')
        .toList(growable: false);
    unawaited(_backend.recordError(
      error, stackTrace,
      fatal: fatal, reason: reason, information: info,
    ));
  }

  static void setUser(String? userId) => unawaited(_backend.setUser(userId));
  static void setKey(String key, Object? value) => unawaited(_backend.setKey(key, value));

  // ---- platform gate ----
  static bool get _supportsCrashlytics {
    if (kIsWeb) return false;
    return switch (defaultTargetPlatform) {
      TargetPlatform.android || TargetPlatform.iOS => true,
      _ => false,
    };
  }

  // ---- handler chaining ----
  static void _installHandlers() {
    _prevFlutterHandler = FlutterError.onError;
    FlutterError.onError = (details) {
      _prevFlutterHandler?.call(details); // chain, don't replace
      error(
        details.exception,
        details.stack ?? StackTrace.current,
        fatal: !_isRecoverable(details.exception),
        reason: details.context?.toDescription(),
      );
    };

    _prevPlatformHandler = PlatformDispatcher.instance.onError;
    PlatformDispatcher.instance.onError = (e, s) {
      _prevPlatformHandler?.call(e, s);
      error(e, s, fatal: !_isRecoverable(e), reason: 'PlatformDispatcher.onError');
      return true;
    };

    _isolatePort ??= RawReceivePort(_handleIsolateError);
    Isolate.current.addErrorListener(_isolatePort!.sendPort);
    _handlersInstalled = true;
  }

  static void _handleIsolateError(Object? pair) {
    final values = pair is List<Object?> ? pair : <Object?>[pair];
    final e = values.isNotEmpty ? (values.first ?? Exception('Unknown isolate error')) : Exception('Unknown');
    final stackStr = values.length > 1 ? values[1]?.toString() : null;
    error(
      e,
      stackStr == null || stackStr.isEmpty ? StackTrace.current : StackTrace.fromString(stackStr),
      fatal: !_isRecoverable(e),
      reason: 'Isolate.addErrorListener',
    );
  }

  // ---- non-fatal classifier ----
  // Extend this list when the dashboard shows a repeat non-crash as fatal.
  static bool _isRecoverable(Object e) {
    if (e is MissingPluginException || e is TimeoutException || e is HandshakeException) {
      return true;
    }
    final msg = e.toString();
    return msg.contains('A RenderFlex overflowed') ||
        msg.contains('Connection terminated during handshake') ||
        msg.contains('Must be a date in the future');
  }

  // ---- test seams ----
  @visibleForTesting
  static void debugUseBackend(ICrashBackend backend, {bool isInitialized = true}) {
    _restoreHandlers();
    _backend = backend;
    _isInitialized = isInitialized;
  }

  @visibleForTesting
  static void debugReset() {
    _restoreHandlers();
    _isolatePort?.close();
    _isolatePort = null;
    _backend = const ConsoleCrashBackend();
    _isInitialized = false;
    _handlersInstalled = false;
  }

  static void _restoreHandlers() {
    if (!_handlersInstalled) return;
    FlutterError.onError = _prevFlutterHandler;
    PlatformDispatcher.instance.onError = _prevPlatformHandler;
    _handlersInstalled = false;
  }

  // ---- helpers ----
  static String _formatMessage(String msg, Map<String, Object?> extras) {
    if (extras.isEmpty) return msg;
    final s = extras.entries.map((e) => '${e.key}=${_normalize(e.value)}').join(', ');
    return '$msg [$s]';
  }

  static Object _normalize(Object? v) {
    if (v == null) return 'null';
    if (v is bool || v is num || v is String) return v;
    return v.toString();
  }
}
```

## Backends

```dart
class FirebaseCrashBackend implements ICrashBackend {
  const FirebaseCrashBackend(this._cl);
  final FirebaseCrashlytics _cl;

  @override
  Future<void> log(String message) async {
    debugPrint(message);
    await _cl.log(message);
  }

  @override
  Future<void> recordError(Object error, StackTrace stack, {
    bool fatal = false, String? reason, Iterable<Object> information = const [],
  }) async {
    debugPrint('${reason ?? 'Crash'}: $error\n$stack');
    await _cl.recordError(error, stack, fatal: fatal, reason: reason, information: information);
  }

  @override
  Future<void> setUser(String? id) => _cl.setUserIdentifier(id ?? '');
  @override
  Future<void> setKey(String k, Object? v) => _cl.setCustomKey(k, v ?? 'null');
  @override
  void crash() => _cl.crash();
}

class ConsoleCrashBackend implements ICrashBackend {
  const ConsoleCrashBackend();

  @override
  Future<void> log(String message) async => debugPrint(message);

  @override
  Future<void> recordError(Object error, StackTrace stack, {
    bool fatal = false, String? reason, Iterable<Object> information = const [],
  }) async {
    final tail = information.isEmpty ? '' : '\n${information.join('\n')}';
    debugPrint('${reason ?? 'Crash'}: $error\n$stack$tail');
  }

  @override
  Future<void> setUser(String? id) async {}
  @override
  Future<void> setKey(String k, Object? v) async {}
  @override
  void crash() => throw StateError('Crashlytics unavailable on this platform');
}
```

## `main.dart`

```dart
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Crash.init(); // wires handlers, picks backend
  runApp(const ProviderScope(child: App()));
}
```

## Call patterns

| Situation | Call |
|---|---|
| Notifier `catch` before set error state | `Crash.error(e, s, reason: 'X.load'); state = state.copyWith(error: ...);` |
| Local-first fire-and-forget remote sync | `try { await _remote.sync(); } on Exception catch (e, s) { Crash.error(e, s, reason: 'Feature.sync'); }` |
| Transaction rollback | `catch (e, s) { await _rollback(); Crash.error(e, s, reason: '...'); rethrow; }` |
| Breadcrumb before risky work | `Crash.info('Checkout.submit start', extras: {'items': cart.length});` |
| Persistent context | `Crash.setKey('route', '/home');` |
| Identify/clear user | `Crash.setUser(userId);` on login, `Crash.setUser(null)` on logout |
| Fatal before terminate | Skip facade; `await FirebaseCrashlytics.instance.recordError(e, s, fatal: true);` |

## Testing

```dart
setUp(() {
  Crash.debugReset();
  Crash.debugUseBackend(FakeCrashBackend());
});
```

`FakeCrashBackend` record calls for assertion. Tests never touch Firebase.

```dart
final fake = FakeCrashBackend();
Crash.debugUseBackend(fake);
Crash.error(Exception('x'), StackTrace.current, reason: 'test');
expect(fake.errors.single.reason, 'test');
```

## Obfuscated builds

```bash
flutter build apk --obfuscate --split-debug-info=build/symbols
firebase crashlytics:symbols:upload --app=APP_ID build/symbols
```

Wire into CI. Missing symbols = unreadable dashboard.

## Extending the non-fatal classifier

Repeat non-crash appear fatal in dashboard → add marker string or type to `_isRecoverable`. Real-app examples: `RenderFlex overflow`, `MissingPluginException`, `HandshakeException`, `scheduledDate` ArgumentError.

## Checklist

- [ ] `ICrashBackend` interface + `FirebaseCrashBackend` + `ConsoleCrashBackend`
- [ ] `abstract final class Crash` facade hold backend
- [ ] `Crash.init()` in `main()` before `runApp`
- [ ] Platform gate: web/desktop → console backend
- [ ] Handlers chained (prior handler call first)
- [ ] `_isRecoverable` classifier in place + maintained
- [ ] `@visibleForTesting` `debugUseBackend` + `debugReset`
- [ ] `debugPrint` alongside Firebase sends
- [ ] Symbols uploaded in release CI
- [ ] No PII anywhere

## Recap

1. MUST split into three pieces: `abstract interface class ICrashBackend` + concrete backends (`FirebaseCrashBackend`, `ConsoleCrashBackend`) + static facade `abstract final class Crash`. Feature code calls `Crash.error`/`Crash.info` only — NEVER the SDK directly.
2. MUST wire three error hooks: `FlutterError.onError` (Flutter widget errors), `PlatformDispatcher.instance.onError` (platform/async errors), and `Isolate.current.addErrorListener` (background isolate errors). Missing any hook leaves a category of crashes unreported.
3. MUST classify recoverable exceptions as non-fatal (`Crash.error`). NEVER call `Crash.fatal` for RenderFlex overflows, TLS handshakes, past-date scheduling, or plugin-not-found — flooding the fatal dashboard masks real crashes.
