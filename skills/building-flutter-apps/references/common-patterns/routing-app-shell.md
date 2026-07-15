# Common Patterns — Routing and App Shell


## Read first

1. Use `go_router_builder` typed route classes as the navigation API; route definitions own paths.
2. `GoRouter.redirect` uses `ref.read`, never `ref.watch`; redirect policy is a pure matrix-tested resolver.
3. `MaterialApp.router` stays declarative. Bootstrap listeners live in a sibling root `ConsumerWidget` under `ProviderScope`.

## Trigger

Signals: typed route, GoRouter redirect, auth-protected route, router provider, app shell, `MaterialApp.router`, `ProviderScope`, startup bootstrap.
Before code: output `Reading: routing-app-shell.md`.

## Typed GoRouter Route SSOT

Use `go_router_builder` for type-safe route definitions. The generated route
classes are the app navigation API. Widgets, notifiers, and services call the
generated helpers directly.

### Setup

```yaml
# pubspec.yaml — see ../core-stack.md for canonical versions
dependencies:
  go_router: <version>

dev_dependencies:
  build_runner: <version>
  go_router_builder: <version>
```

### Route Definitions

```dart
// core/router/app_routes.dart
part 'app_routes.g.dart';

@TypedGoRoute<HomeRoute>(
  path: '/',
  routes: [
    TypedGoRoute<ProductListRoute>(
      path: 'products',
      routes: [
        TypedGoRoute<ProductDetailRoute>(path: ':id'),
        TypedGoRoute<ProductCreateRoute>(path: 'new'),
      ],
    ),
  ],
)
class HomeRoute extends GoRouteData with $HomeRoute {
  const HomeRoute();

  @override
  Widget build(BuildContext context, GoRouterState state) =>
      const HomeScreen();
}

class ProductListRoute extends GoRouteData with $ProductListRoute {
  const ProductListRoute();

  @override
  Widget build(BuildContext context, GoRouterState state) =>
      const ProductListScreen();
}

class ProductDetailRoute extends GoRouteData with $ProductDetailRoute {
  const ProductDetailRoute({required this.id});
  final String id;

  @override
  Widget build(BuildContext context, GoRouterState state) =>
      ProductDetailScreen(productId: id);
}

class ProductCreateRoute extends GoRouteData with $ProductCreateRoute {
  const ProductCreateRoute();

  @override
  Widget build(BuildContext context, GoRouterState state) =>
      const ProductCreateScreen();
}

@TypedGoRoute<LoginRoute>(path: '/login')
class LoginRoute extends GoRouteData with $LoginRoute {
  const LoginRoute({this.from});
  final String? from;  // query parameter

  @override
  Widget build(BuildContext context, GoRouterState state) =>
      LoginScreen(from: from);
}
```

### Router Provider with Auth Redirect

Create GoRouter once. Use `ref.listen()` + `refreshListenable` to trigger redirect re-evaluation. NEVER `ref.watch()` in redirect — recreates router every state change, resets route stack.

Keep redirect decisions pure. The GoRouter closure should read providers, call a pure resolver, and return the result. Matrix-test the resolver.

**Redirect rules for apps with multi-step setup (profile completion, roles):**

- **During loading, MUST stay put.** Return `null` — NEVER bounce to splash. On web refresh, redirecting `/chat` → `/` → `/home` loses URL. One exception: authenticated users on login/signup redirect to splash.
- **Initial sync MUST NOT hold splash.** Once auth/setup state is known, redirect from splash to the shell and keep sync/data refresh running in the background. A cover screen that waits on `InitialSyncStatus.syncing` blocks startup on network, remote query, and local merge latency. Lint: `router_splash_waits_for_initial_sync`.
- **Auth pages MUST navigate explicitly.** Add `ref.listen(authProvider)` in login/signup pages, navigate on auth success. `refreshListenable` timing unreliable; explicit nav guarantees transition.
- **OAuth MUST skip auth-level `isLoading`.** Use per-button loading (`isGoogleLoading`). Auth `isLoading` triggers premature splash redirect.
- **keepAlive providers survive hot reload.** Redirect closure changes need hot restart.

```dart
@Riverpod(keepAlive: true)
GoRouter router(Ref ref) {
  final refreshNotifier = ValueNotifier<Object?>(null);
  ref.listen(setupInfoProvider, (_, __) {
    refreshNotifier.value = Object();
  });
  ref.onDispose(refreshNotifier.dispose);

  return GoRouter(
    initialLocation: const SplashRoute().location,
    refreshListenable: refreshNotifier,
    routes: $appRoutes,
    redirect: (context, state) {
      final setupStatus = ref.read(setupInfoProvider).status;
      final location = state.matchedLocation;

      return resolveAppRedirect(location: location, setupStatus: setupStatus);
    },
  );
}
```

```dart
@visibleForTesting
String? resolveAppRedirect({
  required String location,
  required SetupStatus setupStatus,
}) {
  switch (setupStatus) {
    case SetupStatus.loading:
      return null; // Stay put — preserves URL on web refresh.
    case SetupStatus.unauthenticated:
      return _isPublicPage(location) ? null : const LoginRoute().location;
    case SetupStatus.needsProfileCompletion:
      return location == '/profile-completion' ? null : '/profile-completion';
    case SetupStatus.setupComplete:
      return _isSetupPage(location) ? const HomeRoute().location : null;
  }
}
```

Test the matrix: loading, signed out, signed in, setup incomplete, setup complete, stale deep links, update-required gates, and auth pages.

### Page Navigation

The route class owns the path, params, query params, and generated helper.
Call it at the event boundary:

```dart
// features/products/presentation/widgets/product_card.dart
class ProductCard extends StatelessWidget {
  const ProductCard({required this.id, super.key});

  final String id;

  @override
  Widget build(BuildContext context) {
    return ProductTile(
      onTap: () => ProductDetailRoute(id: id).go(context),
    );
  }
}
```

```dart
// Belt-and-suspenders: auth pages navigate directly on authentication.
class AppLoginPage extends ConsumerWidget {
  const AppLoginPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.listen(authProvider, (prev, next) {
      if (next.isAuthenticated && !(prev?.isAuthenticated ?? false)) {
        const HomeRoute().go(context);
      }
    });
    return const LoginPageContent();
  }
}
```

For pushed screens that may also be opened by deep link, pop when possible and
otherwise go to a typed fallback route:

```dart
void closeEditor(BuildContext context) {
  if (context.canPop()) {
    context.pop();
    return;
  }
  const ProductListRoute().go(context);
}
```

Keep this helper generic if it appears in multiple places; it must take a
`GoRouteData` fallback, never a raw string. Generic `BuildContext` fallback
helpers are allowed when they do not create route-specific APIs. Do not put
route-specific helpers on `BuildContext`; call the generated typed route helper
directly at the event boundary.

### Dialogs and Sheets

Dialogs and sheets are local presentation, not page routes. Use semantic helper
methods such as `context.showScrollableBottomSheet<T>(...)` or
`showConfirmDialog(...)`. Dismiss from inside the modal widget with
`Navigator.pop(context, result)` / `Navigator.of(context).maybePop()`.

Modals are pop-with-result, not mutation hosts. The dialog widget never
subscribes to a provider its own action mutates, never runs code after
`Navigator.pop`, and never owns its caller's teardown. See
[Modal Snapshot Pattern](modals-navigation.md#modal-snapshot-pattern).

## Long-Running Sync/Auth Cancellation

Guard with a generation token or cancellation signal before every state write or remote connection change.

```dart
class SyncCoordinator {
  int _generation = 0;
  String? _activeUserId;

  Future<void> syncFor(String userId) async {
    final generation = ++_generation;
    _activeUserId = userId;

    await pull();
    if (!_isActive(userId, generation)) return;

    await push();
    if (!_isActive(userId, generation)) return;

    markComplete();
  }

  void cancel() {
    _generation++;
    _activeUserId = null;
  }

  bool _isActive(String userId, int generation) =>
      _generation == generation && _activeUserId == userId;
}
```

### Type-Safe Navigation

```dart
// Navigate with compile-time checked route parameters.
const HomeRoute().go(context);
const ProductListRoute().go(context);
ProductDetailRoute(id: product.id).go(context);

// Push with return value.
final result = await ProductCreateRoute(parentId: product.id).push<bool>(context);

// Replace when entering a same-flow child route whose success exits the whole flow
// (auth/login/signup, onboarding step, destructive confirm, import wizard).
const LoginRoute().pushReplacement(context);

// Safe pop with typed fallback.
if (context.canPop()) {
  context.pop(result);
} else {
  const ProductListRoute().go(context);
}
```

**Forbidden (lint enforced)** — every form below has a typed-route replacement above:

| Anti-pattern | Lint |
|---|---|
| String route path from feature code | `router_string_nav` |
| Direct `GoRouter.of(context)` usage | `router_gorouter_of` |
| Injected router or `context.go(route.location)` usage | `router_direct_route_call` |
| Raw `GoRouter` / `GoRoute` definitions outside the router boundary or shared test router helper | `router_raw_route_definition` |
| Direct `Navigator` page route usage | `router_untyped_navigator_push` |
| Splash/cover waits for initial sync | `router_splash_waits_for_initial_sync` |
| Extra navigation wrapper around typed routes | navigation SSOT lints |

### StatefulShellRoute Tabs

Use `StatefulNavigationShell.goBranch()` for tab changes. Do not push tab root
routes to switch tabs.

```dart
class AppShellScaffold extends StatelessWidget {
  const AppShellScaffold({required this.navigationShell, super.key});

  final StatefulNavigationShell navigationShell;

  @override
  Widget build(BuildContext context) {
    return BottomNavigationBar(
      currentIndex: navigationShell.currentIndex,
      onTap: navigationShell.goBranch,
      items: const [...],
    );
  }
}
```

- In reusable sheets/overlays, pass callback from shell-owned caller, don't route in child.

**GoRouter 17.x — `ShellRoute` propagates to root observers.** Since 17.0.0
`ShellRoute`/`StatefulShellRoute` notify root `NavigatorObserver`s by default.
Most want this (analytics on shell push). Root `RouteObserver` should fire
**only** for top-level nav? Pass `notifyRootObserver: false` on `ShellRoute`.
- Use typed route `.go(context)` to enter shell from outside, or `goBranch()`
  when the shell is already available.

```dart
BentoWorkoutSelectorSheet(
  onCreateWorkout: () async {
    await Navigator.of(sheetContext).maybePop();
    if (!sheetContext.mounted) return;
    navigationShell.goBranch(1);
  },
)
```

Wrong for shell tabs:

```dart
const ExercisesRoute().push<void>(context); // stacks another route
const ExercisesRoute().go(context);         // bypasses branch-switch semantics
```

### App Shell + Bootstrap Boundary

`WidgetRef.listen` is designed to be used at the root of `build` for UI side effects (navigation, dialogs/snackbars, logging, splash removal). Do not mix those bootstrap listeners into the same widget that returns `MaterialApp` / `CupertinoApp` / `WidgetsApp`.

Use a dedicated bootstrap widget under `ProviderScope`:

```dart
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Crash.init();
  runApp(
    const ProviderScope(
      child: AppBootstrap(child: MyApp()),
    ),
  );
}

class AppBootstrap extends ConsumerWidget {
  const AppBootstrap({required this.child, super.key});

  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Eager provider initialization: use watch so the provider stays alive.
    // Select a stable readiness field when the provider exposes state.
    ref.watch(startupProvider.select((state) => state.isReady));

    // UI side effects: listen at the root of build.
    ref.listen(authProvider, (previous, next) {
      if (next case Authenticated()) {
        const HomeRoute().go(context);
      }
    });

    return child;
  }
}

class MyApp extends ConsumerWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    return MaterialApp.router(routerConfig: router);
  }
}
```

`MyApp` remains declarative shell config. `AppBootstrap` owns root lifetime side effects.

---
