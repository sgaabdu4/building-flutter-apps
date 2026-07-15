# Deep Linking


## Read first

1. Typed routes + generated helpers for every in-app nav call.
2. Redirect policy lives in a pure resolver; matrix-test auth/setup/location states.
3. Validate params at route boundary; missing/stale resources render fallback/typed redirect, never throw in `build()`.
4. App Links/Universal Links require hosted association files + cold/warm signed-state E2E.
5. Deep links still pass auth/setup/update gates.

## Trigger

Signals: deep linking, Universal Links, App Links, GoRouter redirect, assetlinks.json, apple-app-site-association
Before code: output `Reading: deep-linking.md`


## Rules

1. **MUST** use typed routes (`go_router_builder`) for in-app navigation.
2. **MUST** keep redirect decisions in a pure resolver and matrix-test them.
3. **MUST** validate route parameters before using them. Missing or invalid IDs render fallback UI or redirect to a typed fallback.
4. **MUST** configure Android App Links and iOS Universal Links when URLs should open the installed app.
5. **MUST** test cold-start, warm-start, signed-out, signed-in, setup-incomplete, and stale-link paths.
6. **MUST** navigate with generated route helpers such as `SomeRoute(...).go(context)` / `.push<T>(context)`.
7. **MUST NOT** assume deep links bypass auth/setup/update gates. The resolver owns that policy.

## Web URL Strategy

Use path URLs for web apps that need shareable links.

```dart
import 'package:flutter_web_plugins/url_strategy.dart';

Future<void> main() async {
  usePathUrlStrategy();
  runApp(const ProviderScope(child: AppRoot()));
}
```

## Route Parameter Safety

Never throw from widget `build()` for a missing route ID. Parse at the route
boundary, then use nullable by-id providers and fallback UI.

```dart
class ProductRoute extends GoRouteData {
  const ProductRoute({required this.id});

  final String id;

  @override
  Widget build(BuildContext context, GoRouterState state) {
    if (id.isEmpty) {
      return const ProductMissingScreen();
    }
    return ProductDetailScreen(productId: id);
  }
}
```

## Redirect Resolver

Keep the closure thin.

```dart
@visibleForTesting
String? resolveAppRedirect({
  required String location,
  required AuthStatus authStatus,
  required SetupStatus setupStatus,
}) {
  if (authStatus == AuthStatus.loading) {
    return null;
  }

  if (authStatus == AuthStatus.signedOut) {
    return isPublicLocation(location) ? null : const LoginRoute().location;
  }

  if (setupStatus == SetupStatus.incomplete) {
    return location == const SetupRoute().location
        ? null
        : const SetupRoute().location;
  }

  return null;
}
```

Test the resolver matrix before shipping any auth/setup/deep-link route change.

## Route Boundary

Deep links enter through GoRouter, and app code navigates through the generated
typed route helpers. Keep route definitions, redirect resolver wiring, and
generated-route `.location` usage in the router boundary.

```dart
ProductDetailRoute(id: productId).go(context);
```

## Android App Links

Add an intent filter inside the main activity:

```xml
<intent-filter android:autoVerify="true">
  <action android:name="android.intent.action.VIEW" />
  <category android:name="android.intent.category.DEFAULT" />
  <category android:name="android.intent.category.BROWSABLE" />
  <data android:scheme="https" android:host="example.com" />
</intent-filter>
```

Host `https://example.com/.well-known/assetlinks.json`:

```json
[
  {
    "relation": ["delegate_permission/common.handle_all_urls"],
    "target": {
      "namespace": "android_app",
      "package_name": "com.example.app",
      "sha256_cert_fingerprints": ["YOUR_SHA256_CERT_FINGERPRINT"]
    }
  }
]
```

Validation:

```bash
adb shell am start -a android.intent.action.VIEW -c android.intent.category.BROWSABLE -d "https://example.com/products/123" com.example.app
```

## iOS Universal Links

Enable associated domains:

```xml
<key>com.apple.developer.associated-domains</key>
<array>
  <string>applinks:example.com</string>
</array>
```

If using Flutter default deep linking:

```xml
<key>FlutterDeepLinkingEnabled</key>
<true/>
```

If a third-party deep-link plugin owns links, set Flutter default handling off
to avoid duplicate dispatch.

Host `https://example.com/.well-known/apple-app-site-association` without a
file extension:

```json
{
  "applinks": {
    "apps": [],
    "details": [
      {
        "appIDs": ["TEAMID.com.example.app"],
        "components": [
          { "/": "/products/*" },
          { "/": "/invite/*" }
        ]
      }
    ]
  }
}
```

Validation:

```bash
xcrun simctl openurl booted https://example.com/products/123
```

## E2E Matrix

| Case | Expected proof |
|---|---|
| Cold start signed out | Link opens login or public page, then resumes intended path after sign-in if supported |
| Cold start signed in | Link opens target screen after loading gates settle |
| Setup incomplete | Resolver sends user to setup without losing intended target when required |
| Missing resource | Fallback/empty screen, no build throw |
| Revoked permission | Blocked or fallback state; no stale detail data |
| Web refresh | Current path survives loading state |

## Checklist

- [ ] Typed routes exist for link targets and call sites use generated route helpers.
- [ ] Redirect resolver is pure and matrix-tested.
- [ ] Android App Links or iOS Universal Links are configured when required.
- [ ] Hosted association files match app IDs, bundle IDs, package names, and SHA fingerprints.
- [ ] Cold/warm, signed-in/signed-out, setup, stale, and permission-denied paths are E2E tested.
- [ ] Missing route params or missing resources do not throw from widget `build()`.
