# Services, Singletons, Fire-and-Forget

Three patterns, one topic: code that lives outside the widget tree and can't go through `ref.watch`. How to structure, how to test.

## When & Why

Default = Riverpod provider. Other two = fallback.

### Static-only class (`abstract final class Foo { static ... }`)

**When.** Pure functions. No state. No I/O. Grouped by topic. Ex: `DateUtils.format`, `StringCasing.camel`, `Bytes.humanize`.

**Why.** Namespace. No instance = no lifecycle = no test setup. Dart disallows `new Foo()` via `abstract final` — enforced intent.

**Not when.** Touches Firebase / disk / network / time / random. Those need a seam. Static = unseamable = unmockable = flaky tests.

**Exception.** Static facade **over** a swappable backend (see [crashlytics.md](crashlytics.md)). Facade is static; backend is injectable via `debugUseBackend`. Combines namespace ergonomics with test swap.

### Singleton (`static final instance = Foo._()`)

**When.** Never write new one. Use only when SDK forces it (`FirebaseAuth.instance`, `SharedPreferences.getInstance()`).

**Why avoid.** Global mutable state. Leaks between tests. Hidden dependency — caller signature lies. No override path.

**If forced.** Wrap SDK singleton in provider. Feature code watches provider, not SDK.

```dart
@Riverpod(keepAlive: true)
FirebaseAuth auth(Ref ref) => FirebaseAuth.instance;
```

Now testable: `overrides: [authProvider.overrideWithValue(FakeAuth())]`.

### Riverpod provider (`@Riverpod(keepAlive: true)`)

**When.** Stateful service. I/O. Anything mockable. Default pick.

**Why.** One instance per container. Lifecycle tied to container. Override in tests. Dispose hooks. No global mutation.

**Not when.** Zero-dep pure helper → static class is lighter.

## Decision — one-liner

> Pure + stateless → **static-only class**. SDK-forced one-instance → **singleton wrapped in provider**. Everything else → **provider**.

## 1. Static-only class (namespace)

`abstract final class` with only `static` members. **Not a singleton** — no instance exists. Use for pure functions grouped by topic.

```dart
abstract final class Crash {
  static void error(Object e, StackTrace s, {String? reason}) {
    unawaited(FirebaseCrashlytics.instance.recordError(e, s, reason: reason));
  }
  static void log(String msg) => FirebaseCrashlytics.instance.log(msg);
}
```

Lint: `prefer-abstract-final-static-class` (DCM) flags classes with only static members that omit `abstract final`.

### Testing

Hard to seam directly. Two options:

- **Inject at the boundary.** Don't call `Crash.error` from tests. Keep the wrapper thin enough that tests skip it (e.g. don't init Firebase in tests → the call no-ops or throws — wrap in a provider below).
- **Wrap in a Riverpod provider** (preferred) — then static class becomes an impl detail:

```dart
@Riverpod(keepAlive: true)
CrashReporter crashReporter(Ref ref) => const FirebaseCrashReporter();

// In tests:
ProviderScope(overrides: [crashReporterProvider.overrideWithValue(FakeCrashReporter())]);
```

Rule: use static-only class **only** for dependency-free helpers (pure math, formatters). Anything touching Firebase / network / disk → provider.

## 2. Singleton

One instance, globally reachable. Use **only** when a library forces it (e.g. an SDK that itself holds a singleton).

```dart
final class AudioPlayer {
  AudioPlayer._();
  static final AudioPlayer instance = AudioPlayer._();
  final _queue = <Clip>[];
}
```

### Testing

Singletons are test-hostile. State leaks between tests. Fixes:

- **Wrap in a provider** so tests override it:

```dart
@Riverpod(keepAlive: true)
AudioPlayer audio(Ref ref) => AudioPlayer.instance;

ProviderScope(overrides: [audioProvider.overrideWithValue(FakeAudioPlayer())]);
```

- **Reset hook** for tests that must touch the real singleton:

```dart
@visibleForTesting
void debugReset() { _queue.clear(); }
```

Rule: **don't write new singletons.** Write a `final class Foo { ... }` + a `keepAlive: true` provider. Riverpod gives you one instance per container, override for tests, dispose on container dispose.

## 3. Fire-and-Forget

Future you intentionally don't `await`. Five rules:

1. Mark with `unawaited(foo())` — explicit intent, satisfies `unawaited_futures` + `discarded_futures` lints.
2. `Future<void>` signature, never `void async` (`avoid_void_async`).
3. Catch internally. Uncaught throws leak to `PlatformDispatcher.onError` → logged **fatal** (wrong).
4. No ordering dependency on other fire-and-forget calls.
5. Never fire-and-forget in tests — leaked futures pollute next test.

### Canonical shape

```dart
Future<void> trackEvent(String name) async {
  try {
    await _analytics.logEvent(name: name);
  } on Exception catch (e, s) {
    Crash.error(e, s, reason: 'Analytics.$name');
  }
}

// Call site:
unawaited(ref.read(analyticsProvider).trackEvent('sign_in'));
```

### When to fire-and-forget

Analytics, non-fatal `Crash.error`, breadcrumb `Crash.log`, local-first remote mirror sync, perf trace `stop()`, push-token refresh, cache eviction, session heartbeat.

### When NOT to

Anything the UI awaits, anything surfacing a toast, anything the caller reads the return value of.

### Testing

- In tests, `await` the future directly — the production `unawaited(...)` wrapper doesn't exist on the returned Future itself.
- Fake the service (via provider override) to capture calls synchronously:

```dart
final fake = FakeAnalyticsClient();
await tester.pumpWidget(ProviderScope(
  overrides: [analyticsProvider.overrideWithValue(fake)],
  child: const App(),
));
await tester.tap(find.byKey(signInKey));
await tester.pumpAndSettle();
expect(fake.events, contains('sign_in'));
```

Never assert against the real Firebase backend in unit/widget tests.

## Decision

| Need | Use |
|---|---|
| Stateless helpers (format, parse) | `abstract final class` |
| Stateful service, mockable | Riverpod provider wrapping `final class` |
| Library-forced singleton (Firebase, SharedPreferences) | Riverpod provider returning the SDK instance |
| Async side effect not blocking UI | `unawaited(service.method())` with internal catch |

Default: **provider**. Pick static-only or singleton only when provider doesn't fit.
