# Services, Singletons, Fire-and-Forget

Three patterns, one topic: code outside widget tree, no `ref.watch`. How structure, how test.

## When & Why

Default = Riverpod provider. Other two = fallback.

### Static-only class (`abstract final class Foo { static ... }`)

**When.** Pure functions. No state. No I/O. Grouped by topic. Ex: `DateUtils.format`, `StringCasing.camel`, `Bytes.humanize`.

**Why.** Namespace. No instance = no lifecycle = no test setup. Dart blocks `new Foo()` via `abstract final` — intent enforced.

**Not when.** Touches Firebase / disk / network / time / random. Need seam. Static = unseamable = unmockable = flaky tests.

**Exception.** Static facade **over** swappable backend (see [crashlytics.md](crashlytics.md)). Facade static; backend injectable via `debugUseBackend`. Namespace ergonomics + test swap.

### Singleton (`static final instance = Foo._()`)

**When.** Never write new. Use only when SDK force (`FirebaseAuth.instance`, `SharedPreferences.getInstance()`).

**Why avoid.** Global mutable state. Leaks between tests. Hidden dep — caller signature lie. No override path.

**If forced.** Wrap SDK singleton in provider. Feature code watch provider, not SDK.

```dart
@Riverpod(keepAlive: true)
FirebaseAuth auth(Ref ref) => FirebaseAuth.instance;
```

Now testable: `overrides: [authProvider.overrideWithValue(FakeAuth())]`.

### Riverpod provider (`@Riverpod(keepAlive: true)`)

**When.** Stateful service. I/O. Anything mockable. Default pick.

**Why.** One instance per container. Lifecycle tied to container. Override in tests. Dispose hooks. No global mutation.

**Not when.** Zero-dep pure helper → static class lighter.

## Decision — one-liner

> Pure + stateless → **static-only class**. SDK-forced one-instance → **singleton wrapped in provider**. Else → **provider**.

## 1. Static-only class (namespace)

`abstract final class` with only `static` members. **Not singleton** — no instance. Use for pure functions grouped by topic.

```dart
abstract final class Crash {
  static void error(Object e, StackTrace s, {String? reason}) {
    unawaited(FirebaseCrashlytics.instance.recordError(e, s, reason: reason));
  }
  static void log(String msg) => FirebaseCrashlytics.instance.log(msg);
}
```

Lint: `prefer-abstract-final-static-class` (DCM) flags static-only classes missing `abstract final`.

### Testing

Hard to seam direct. Two options:

- **Inject at boundary.** Don't call `Crash.error` from tests. Keep wrapper thin so tests skip it (e.g. don't init Firebase in tests → call no-ops or throws — wrap in provider below).
- **Wrap in Riverpod provider** (preferred) — static class becomes impl detail:

```dart
@Riverpod(keepAlive: true)
CrashReporter crashReporter(Ref ref) => const FirebaseCrashReporter();

// In tests:
ProviderScope(overrides: [crashReporterProvider.overrideWithValue(FakeCrashReporter())]);
```

Rule: static-only class **only** for dep-free helpers (pure math, formatters). Touches Firebase / network / disk → provider.

## 2. Singleton

One instance, global reach. Use **only** when library force (e.g. SDK holds own singleton).

```dart
final class AudioPlayer {
  AudioPlayer._();
  static final AudioPlayer instance = AudioPlayer._();
  final _queue = <Clip>[];
}
```

### Testing

Singletons test-hostile. State leaks between tests. Fixes:

- **Wrap in provider** so tests override:

```dart
@Riverpod(keepAlive: true)
AudioPlayer audio(Ref ref) => AudioPlayer.instance;

ProviderScope(overrides: [audioProvider.overrideWithValue(FakeAudioPlayer())]);
```

- **Reset hook** for tests that must touch real singleton:

```dart
@visibleForTesting
void debugReset() { _queue.clear(); }
```

Rule: **don't write new singletons.** Write `final class Foo { ... }` + `keepAlive: true` provider. Riverpod give one instance per container, override for tests, dispose on container dispose.

## 3. Fire-and-Forget

Future you intentionally don't `await`. Five rules:

1. Mark with `unawaited(foo())` — explicit intent, satisfies `unawaited_futures` + `discarded_futures` lints.
2. `Future<void>` signature, never `void async` (`avoid_void_async`).
3. Catch internally. Uncaught throws leak to `PlatformDispatcher.onError` → logged **fatal** (wrong).
4. No ordering dep on other fire-and-forget calls.
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

Anything UI awaits, anything surfacing toast, anything caller read return value of.

### Testing

- In tests, `await` future direct — production `unawaited(...)` wrapper not on returned Future itself.
- Fake service (via provider override) to capture calls sync:

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

Never assert against real Firebase backend in unit/widget tests.

## Decision

| Need | Use |
|---|---|
| Stateless helpers (format, parse) | `abstract final class` |
| Stateful service, mockable | Riverpod provider wrapping `final class` |
| Library-forced singleton (Firebase, SharedPreferences) | Riverpod provider returning SDK instance |
| Async side effect not blocking UI | `unawaited(service.method())` with internal catch |

Default: **provider**. Pick static-only or singleton only when provider don't fit.