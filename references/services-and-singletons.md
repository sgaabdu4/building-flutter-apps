# Services, Singletons, Fire-and-Forget

## Trigger

Signals: abstract final class, singleton, unawaited, fire-and-forget, static facade
Before generating code in this area, output verbatim: `Reading: services-and-singletons.md`


## When & Why

Default = Riverpod provider. Other two = fallback.

### Static-only class (`abstract final class Foo { static ... }`)

**When.** Pure fn. No state. No I/O. Grouped by topic. Ex: `DateUtils.format`, `StringCasing.camel`, `Bytes.humanize`.

**Why.** Namespace. No instance = no lifecycle = no test setup. Dart block `new Foo()` via `abstract final` — intent enforced.

**Not when.** Touch Firebase/disk/network/time/random. Need seam. Static = unseamable = unmockable = flaky test.

**Exception.** Static facade **over** swappable backend (see [crashlytics.md](crashlytics.md)). Facade static; backend injectable via `debugUseBackend`. Namespace ergonomics + test swap.

### Singleton (`static final instance = Foo._()`)

**When.** Never write new. Use only when SDK force (`FirebaseAuth.instance`, `SharedPreferences.getInstance()`).

**Why avoid.** Global mutable state. Leak between tests. Hidden dep — caller signature lie. No override path.

**If forced.** Wrap SDK singleton in provider. Feature code watch provider, not SDK.

```dart
@Riverpod(keepAlive: true)
FirebaseAuth auth(Ref ref) => FirebaseAuth.instance;
```

Now testable: `overrides: [authProvider.overrideWithValue(FakeAuth())]`.

### Riverpod provider (`@Riverpod(keepAlive: true)`)

**When.** Stateful service. I/O. Mockable. Default pick.

**Why.** One instance per container. Lifecycle tied to container. Override in tests. Dispose hooks. No global mutation.

**Not when.** Zero-dep pure helper → static class lighter.

## Decision — one-liner

> Pure + stateless → **static-only class**. SDK-forced one-instance → **singleton wrapped in provider**. Else → **provider**.

## 1. Static-only class (namespace)

`abstract final class` with only `static` members. **Not singleton** — no instance. Pure fn grouped by topic.

```dart
// Pure helper — no I/O, no SDK ref. Safe static-only.
abstract final class StringCasing {
  static String camel(String input) => /* ... */;
  static String snake(String input) => /* ... */;
}
```

Infrastructure facades (`Crash`, `SnackBarUtils`) = thin shim **over swappable
backend** — see [crashlytics.md](crashlytics.md). Static never references
`FirebaseCrashlytics.instance` direct. Backend injected via `Crash.init(backend)`
— tests swap `FakeCrashBackend`.

Lint: `prefer-abstract-final-static-class` (DCM) flag static-only class missing `abstract final`.

### Testing

Hard seam direct. Two options:

- **Inject at boundary.** No `Crash.error` from tests. Keep wrapper thin so tests skip (e.g. no Firebase init in tests → no-op/throw — wrap in provider below).
- **Wrap in Riverpod provider** (preferred) — static class = impl detail:

```dart
@Riverpod(keepAlive: true)
CrashReporter crashReporter(Ref ref) => const FirebaseCrashReporter();

// In tests:
ProviderScope(overrides: [crashReporterProvider.overrideWithValue(FakeCrashReporter())]);
```

Rule: static-only class **only** for dep-free helper (pure math, formatters). Touch Firebase/network/disk → provider.

## 2. Singleton

One instance, global reach. Use **only** when library force (SDK hold own singleton).

```dart
final class AudioPlayer {
  AudioPlayer._();
  static final AudioPlayer instance = AudioPlayer._();
  final _queue = <Clip>[];
}
```

### Testing

Singleton test-hostile. State leak between tests. Fixes:

- **Wrap in provider** so tests override:

```dart
@Riverpod(keepAlive: true)
AudioPlayer audio(Ref ref) => AudioPlayer.instance;

ProviderScope(overrides: [audioProvider.overrideWithValue(FakeAudioPlayer())]);
```

- **Reset hook** for tests must touch real singleton:

```dart
@visibleForTesting
void debugReset() { _queue.clear(); }
```

Rule: **no new singletons.** Write `final class Foo { ... }` + `keepAlive: true` provider. Riverpod give one instance per container, override for tests, dispose on container dispose.

## 3. Fire-and-Forget

Future intentionally no `await`. Five rules:

1. Mark `unawaited(foo())` — explicit intent, satisfy `unawaited_futures` + `discarded_futures` lints.
2. `Future<void>` signature, never `void async` (`avoid_void_async`).
3. Catch internally. Uncaught throw leak to `PlatformDispatcher.onError` → logged **fatal** (wrong).
4. No ordering dep on other fire-and-forget calls.
5. Never fire-and-forget in tests — leaked future pollute next test.

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

UI await, toast surface, caller read return value.

### Testing

- Tests `await` future direct — prod `unawaited(...)` wrapper not on returned Future itself.
- Fake service (via provider override) capture calls sync:

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

No assert vs real Firebase backend in unit/widget tests.

## Decision

| Need | Use |
|---|---|
| Stateless helpers (format, parse) | `abstract final class` |
| Stateful service, mockable | Riverpod provider wrapping `final class` |
| Library-forced singleton (Firebase, SharedPreferences) | Riverpod provider returning SDK instance |
| Async side effect not blocking UI | `unawaited(service.method())` with internal catch |

Default: **provider**. Static-only or singleton only when provider don't fit.

## Recap

1. Pure stateless helpers → `abstract final class` with only `static` members; stateful services with I/O → `@Riverpod(keepAlive: true)` provider. NEVER reach for a singleton when a provider fits.
2. NEVER write new singletons — wrap any SDK-forced singleton (FirebaseAuth, SharedPreferences, Hive) in a Riverpod provider so it is mockable and scoped correctly.
3. Fire-and-forget MUST use `unawaited(foo())`, NEVER `void async` lambda. The call MUST catch internally — uncaught throws escape to `PlatformDispatcher.onError` and appear as false fatals in crash reporting.
