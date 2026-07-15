# Services, Singletons, Fire-and-Forget


## Read first

1. Singletons and static service facades are allowed only for fire-and-forget infrastructure.
2. Plain singleton = private constructor + one `static final instance` (or private static final + trivial getter) + public methods that return only `void` / `Future<void>`.
3. Plain static facade = `abstract final class` with a tiny `void` / `Future<void>` API over an SDK singleton (`Crash`, analytics/logging wrappers).
4. Do not add backend interfaces, fake implementations, debug injection, service locators, or Riverpod wrappers only to test singleton wiring.
5. If the service returns data, exposes state, owns mutable resources, or needs replacement in tests, it is not a singleton. Use a repository/datasource or Riverpod provider.
6. Fire-and-forget uses `unawaited(foo())`; never `void async` callbacks. The callee catches internally.
7. Riverpod service/repository/datasource/client factories wire stable deps with `ref.read`. Use `ref.watch` only for the provider that intentionally owns reactivity.
8. For Android exact alarms with `flutter_local_notifications`, use `AndroidFlutterLocalNotificationsPlugin.canScheduleExactNotifications()` / `requestExactAlarmsPermission()`. Do not launch `android.settings.REQUEST_SCHEDULE_EXACT_ALARM` manually; the plugin owns the app-specific settings intent and permission re-check.
9. For platform-specific plugin APIs, assign `resolvePlatformSpecificImplementation<T>()` to a local variable or narrow helper getter before use. Explicitly handle `null`; do not chain directly into `?.method()`, `?.property`, or `!.method()`.

## Trigger

Signals: abstract final class, singleton, unawaited, fire-and-forget, static facade
Before code: output `Reading: services-and-singletons.md`

## Decision

| Need | Use |
|---|---|
| Pure stateless helper | `abstract final class` static namespace |
| Tiny fire-and-forget SDK/service facade | `abstract final class` with direct SDK calls and `void` / `Future<void>` API |
| Fire-and-forget app singleton | `final class` + private constructor + `static final instance` + no returned data/state |
| Non-fire-and-forget service needing `Ref`, config reactivity, dispose, state, returned data, or test override | `@Riverpod(keepAlive: true)` provider |
| Async side effect | `unawaited(foo())` + internal catch |

Default: boring code. Do not build indirection before the product needs it.

## 1. Static-only class (namespace or tiny facade)

`abstract final class` with only `static` members.

```dart
// Pure helper — no I/O, no SDK ref.
abstract final class StringCasing {
  static String camel(String input) => /* ... */;
  static String snake(String input) => /* ... */;
}
```

Tiny infrastructure facades may call SDK singletons directly. Keep the public API
small, purpose-specific, and fire-and-forget (`void` / `Future<void>` only).

```dart
abstract final class AnalyticsLog {
  static FirebaseAnalytics get _analytics => FirebaseAnalytics.instance;

  static Future<void> event(String name, {Map<String, Object> params = const {}}) async {
    try {
      await _analytics.logEvent(
        name: name,
        parameters: params.isEmpty ? null : params,
      );
    } on Exception catch (e, s) {
      Crash.error(e, s, reason: 'AnalyticsLog.event');
    }
  }
}
```

`Crash` exposes only `init`, `error`, and `log`; see
[crashlytics.md](crashlytics.md).

### Do not add

- `IAnalyticsBackend`, `FirebaseAnalyticsBackend`, `FakeAnalyticsBackend`
- `debugUseBackend`, `debugReset`, `setClient`, `setInstance`
- `ProviderScope`/Riverpod wrapper only to override the facade in tests
- service locator / factory layer
- broad public API (`init`, `log`, `error`, `setUser`, `setKey`, `classify`, ...)
- manual `AndroidIntent(action: 'android.settings.REQUEST_SCHEDULE_EXACT_ALARM')` flows when `flutter_local_notifications` provides `requestExactAlarmsPermission()`
- direct chains from `resolvePlatformSpecificImplementation<T>()` into nullable member calls/properties

Lint: `use_local_notifications_exact_alarm_permission_api` flags manual exact-alarm settings intents. `resolve_platform_specific_implementation_before_use` flags direct platform-specific implementation member chains. `prefer-abstract-final-static-class` flags static-only classes missing
`abstract final`. `service_static_side_effect` flags static facades that become
wide or overbuilt.

### Testing

Smoke test only: unsupported platform does not throw, methods return/catch. Do
not fake the singleton/facade itself. Feature tests should fake the repository,
datasource, or caller-owned boundary instead.

## 2. Singleton

One process-wide instance. Use only for fire-and-forget infrastructure where the
caller never reads state/data back. Keep the shape boring:

```dart
final class PushTokenRefresh {
  PushTokenRefresh._();

  static final PushTokenRefresh instance = PushTokenRefresh._();

  Future<void> refresh() async {
    try {
      await FirebaseMessaging.instance.getToken();
    } on Exception catch (e, s) {
      Crash.error(e, s, reason: 'PushTokenRefresh.refresh');
    }
  }
}

// Call site:
unawaited(PushTokenRefresh.instance.refresh());
```

Allowed alternate shape when a getter reads better:

```dart
final class PushTokenRefresh {
  PushTokenRefresh._();

  static final PushTokenRefresh _instance = PushTokenRefresh._();
  static PushTokenRefresh get instance => _instance;

  Future<void> refresh() async { /* fire-and-forget work */ }
}
```

### Do not add

- public constructor plus `instance`
- mutable/lazy `_instance` setter
- `debugConfigure`, `debugUse`, `setInstance`, `setBackend`, `setClient`
- `Fake*Service` solely for singleton tests
- provider/service-locator wrapper solely for singleton tests
- public getters / state / streams / controllers / caches / queues
- public methods that return data (`Future<User>`, `String`, `bool`, etc.)

### Testing

Prefer testing callers through a repository/datasource/provider boundary. Tests
may `await` the fire-and-forget method directly to verify it does not throw.

```dart
void main() {
  test('refresh does not throw', () async {
    await PushTokenRefresh.instance.refresh();
  });
}
```

If a service needs replacement in tests, config changes, lifecycle disposal,
user scope, mutable state, or returned data, it is not a plain singleton. Use a
Riverpod provider or a repository/datasource boundary instead.

Lint: `service_singleton` allows boring fire-and-forget singleton shapes and
flags stateful/data-returning/debug/fake/backend singleton seams.

## 3. Fire-and-Forget

Future intentionally no `await`. Five rules:

1. Mark `unawaited(foo())` — explicit intent, satisfy `unawaited_futures` + `discarded_futures` lints.
2. `Future<void>` signature, never `void async` (`avoid_void_async`).
3. Catch internally. Uncaught async errors become unhandled runtime/test failures.
4. No ordering dep on other fire-and-forget calls.
5. Never fire-and-forget in tests — leaked future pollutes the next test.

### Canonical shape

```dart
Future<void> trackEvent(String name) async {
  try {
    await AnalyticsLog.event(name);
  } on Exception catch (e, s) {
    Crash.error(e, s, reason: 'Analytics.$name');
  }
}

// Call site:
unawaited(trackEvent('sign_in'));
```

### When to fire-and-forget

Analytics, non-fatal `Crash.error`, breadcrumb `Crash.log`, local-first remote
mirror sync, perf trace `stop()`, push-token refresh, cache eviction, session
heartbeat.

### When NOT to

UI await, toast surface, caller reads return value.

### Testing

Tests `await` the future directly. Do not assert against a real Firebase backend
in unit/widget tests.

```dart
await trackEvent('sign_in');
```

## Checklist

- [ ] Singleton has private constructor + one `static final instance` or trivial getter
- [ ] Singleton/facade public API returns only `void` / `Future<void>`
- [ ] Singleton/facade is fire-and-forget only: no public getters, returned data, or mutable state
- [ ] Static facade public API is tiny and purpose-specific
- [ ] No backend/fake/debug injection seam added just for tests
- [ ] Fire-and-forget singleton/facade is not wrapped in a provider just for testing
- [ ] Provider used only for non-fire-and-forget `Ref`, config reactivity, dispose, override, returned data, or UI state
- [ ] Fire-and-forget caller uses `unawaited(...)`
- [ ] Fire-and-forget callee catches and reports internally
- [ ] Android exact-alarm permission uses `flutter_local_notifications` `canScheduleExactNotifications()` / `requestExactAlarmsPermission()`, not a manual `AndroidIntent` settings launch (`use_local_notifications_exact_alarm_permission_api`)
- [ ] Platform-specific plugin APIs resolve `resolvePlatformSpecificImplementation<T>()` before use and handle `null` explicitly; no direct `?.method()`, `?.property`, or `!.method()` chain (`resolve_platform_specific_implementation_before_use`)
