# Crash Reporting

## Read first

1. Existing provider + accepted telemetry/privacy contract = preserve.
2. Adding/replacing/dual-running a provider = material external-data change → explicit approval + `security-review`.
3. `Crash` = one tiny provider-neutral facade; public API = `init`, `log`, `error`.
4. SDK imports/calls = `crash_service.dart` only; feature code calls `Crash`.
5. Startup = one owner; SDK-managed error integration replaces hand-wired zone/framework/dispatcher handlers.
6. Event payloads, breadcrumbs, tags, extras, screenshots, view hierarchy, replay, request capture, and user identity = no PII by default.
7. Current SDK behavior = installed lockfile/API + official package docs; memory/example-version copying = no proof.

## Trigger

Signals = Crashlytics + FirebaseCrashlytics + Sentry + sentry_flutter + DSN + `Crash.error` + symbolication + crash reporting.

Before code = output `Reading: error-reporting.md`.

## Provider branch

| Repository evidence | Action |
|---|---|
| Firebase Crashlytics only | Keep direct Firebase calls inside `Crash`; initialize Firebase once. |
| Sentry only | Initialize with `SentryFlutter.init(..., appRunner: ...)`; `Crash.error` calls `Sentry.captureException`. |
| Explicitly accepted dual reporting | Initialize Firebase before Sentry; Sentry owns `appRunner`; each manual event reaches each provider once. |
| No provider + no accepted telemetry decision | Stop at provider/data/environment decision; do not install a default. |

Dual reporting = requested migration/coverage only; redundancy alone does not justify two providers.

## Facade

```dart
abstract final class Crash {
  static Future<void> init({required FutureOr<void> Function() appRunner});
  static void log(String message, {Map<String, Object?> extras = const {}});
  static void error(
    Object error,
    StackTrace stackTrace, {
    String? reason,
    bool fatal = false,
    Map<String, Object?> extras = const {},
  });
}
```

```dart
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Crash.init(
    appRunner: () => runApp(const ProviderScope(child: App())),
  );
}
```

- Crashlytics branch = initialize Firebase + enable collection + call `appRunner`.
- Sentry branch = configure current installed `sentry_flutter` API + pass `appRunner` to `SentryFlutter.init`.
- Init failure before `appRunner` = local diagnostic + run app without remote telemetry; startup must not brick.
- Send failure = contained fire-and-forget diagnostic; never recurse into `Crash.error`.
- Unexpected provider/transport failure = preserve original error + stack in `Crash.error` before mapping to a user-safe/domain error; never report only the sanitized replacement.
- Expected cancellation/auth/input outcome = typed local state + no remote noise; classification must be explicit and tested.
- Do not add backend interfaces + runtime backend setters + fake/debug implementations + feature constants to the facade.

## Sentry contract

- DSN = public client destination embedded in the app; one environment-aware config owner + empty/disabled test default.
- `SENTRY_AUTH_TOKEN` = build-only secret; never source + app config + runtime bundle + command argument/output.
- `sendDefaultPii = false`; add an event scrubber for app-owned context because this option cannot sanitize custom values.
- Screenshots + view hierarchy + replay + user identity + request bodies/headers + performance/profile sampling = disabled until individually accepted.
- Breadcrumb/extras keys = allowlist; values = bounded non-identity diagnostics.
- Automatic framework/native capture = SDK integration only; do not stack custom global handlers around it.
- Runtime issue inventory/root cause/resolve = global `sentry` skill; this reference owns Flutter wiring only.

## Release + symbols

- Build revision + Sentry release/dist + deployed artifact = exact identity.
- Obfuscated or split-debug-info build = retain matching debug output + upload before/with release through build-only credentials.
- Upload success alone = insufficient; approved controlled event on installed artifact must resolve to expected project/environment/release and show symbolicated in-app frames.
- Missing upload token/config = fail release observability gate; never silently publish an unsymbolicatable release when Sentry is required.

## Proof

- DSN absent/test mode → app starts + no external envelope.
- Init → app runner exactly once on provider success/failure.
- `log`/`error` → no throw; selected provider receives each manual event once.
- Error translation fixture → unexpected raw cause + original stack reported before safe UI error; expected outcomes remain unreported.
- Scrubber fixtures → identity + auth + request-body/header values removed; allowed diagnostics preserved.
- Dual branch → no duplicate call within either provider.
- Approved live proof → controlled event + exact release + symbolicated frame read back through `sentry`.

## Checklist

- [ ] Accepted provider(s) + environments + data categories recorded
- [ ] `crash_service.dart` = only SDK owner
- [ ] Public API = `init` + `error` + `log`
- [ ] SDK-managed startup integration = one owner
- [ ] DSN/config centralized + auth token build-only
- [ ] PII and opt-in capture surfaces disabled/scrubbed
- [ ] Tests prove no-DSN + init failure + once-only send + scrubber
- [ ] Release/symbol identity proven when production reporting is required

## Sources

- [Sentry Flutter package](https://pub.dev/packages/sentry_flutter)
- [Sentry Flutter options API](https://pub.dev/documentation/sentry_flutter/latest/sentry_flutter/SentryFlutterOptions-class.html)
- [Sentry core options API](https://pub.dev/documentation/sentry/latest/sentry/SentryOptions-class.html)
- [Sentry Dart symbol uploader](https://pub.dev/packages/sentry_dart_plugin)
- [Sentry client keys](https://docs.sentry.io/api/organizations/list-an-organizations-client-keys/)
