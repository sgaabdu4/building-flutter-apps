# Showcase Guided Tours

## Trigger

Signals: showcaseview, ShowcaseScreenMixin, ShowcaseKeys, GlobalKey, tour
Before generating code in this area, output verbatim: `Reading: showcase-tours.md`


## Contents

- [Package](#package)
- [Architecture](#architecture)
- [ShowcaseScreenMixin](#showcasescreenmixin)
- [AppShowcaseTarget](#appshowasetarget)
- [ShowcaseService](#showcaseservice)
- [ShowcaseKeys](#showcasekeys)
- [Adding a Tour to a New Screen](#adding-a-tour-to-a-new-screen)
- [Testing](#testing)
- [Resetting Tours (Shell Route Caveat)](#resetting-tours-shell-route-caveat)
- [Test-Env Safe Service Read](#test-env-safe-service-read)
- [Sync Integration](#sync-integration)
- [Constraints](#constraints)

## Package

```yaml
dependencies:
  showcaseview: ^5.0.2
```

**Migrating from 4.x.** v5.0.0 removed `height`/`width` from `Showcase`
([#541](https://github.com/SimformSolutionsPvtLtd/showcaseview/issues/541)).
Tooltip now content-sized. Used those params? Wrap child in
`SizedBox(height: …, width: …)`. Pre-5 callers compile silent, wrong layout
— grep `Showcase(.*height:` + `Showcase(.*width:` before upgrade.

## Architecture

Six files form showcase system:

| File | Type | Purpose |
|------|------|---------|
| `showcase_screen_mixin.dart` | Mixin | Lifecycle: register scope, check, start, dispose |
| `app_showcase_target.dart` | StatefulWidget | Styled `Showcase` wrapper. Bind named scope before build |
| `showcase_service.dart` | Interface + Impl + Signal | Persist tour completion. `ShowcaseResetSignal` notify alive screens |
| `showcase_keys.dart` | Abstract final class | `GlobalKey` registry + ordered tour lists |
| `showcase_constants.dart` | Abstract final class | Scope name constants |
| `showcase_strings.dart` | Class | Tooltip title/description strings |

```
lib/core/
├── mixins/
│   └── showcase_screen_mixin.dart
├── services/
│   ├── showcase_keys.dart
│   └── showcase_service.dart
├── constants/
│   ├── showcase_constants.dart
│   └── showcase_strings.dart
└── widgets/atoms/
    └── app_showcase_target.dart
```

## ShowcaseScreenMixin

Mixin on `ConsumerState`. Screens override three getters, call two lifecycle methods:

```dart
class MyFeatureScreenState extends ConsumerState<MyFeatureScreen>
    with ShowcaseScreenMixin {

  @override
  String get showcaseScope => ShowcaseConstants.myFeatureScope;
  @override
  ShowcaseTour get showcaseTour => ShowcaseTour.myFeature;
  @override
  List<GlobalKey> get showcaseKeys => ShowcaseKeys.myFeatureTour;

  @override
  void initState() {
    super.initState();
    initShowcase(); // register scope, schedule tour check
  }

  @override
  void dispose() {
    disposeShowcase(); // unregister scope
    super.dispose();
  }
}
```

### Required overrides

| Getter | Type | What to provide |
|--------|------|----------------|
| `showcaseScope` | `String` | `ShowcaseConstants.*` scope name |
| `showcaseTour` | `ShowcaseTour` | Enum from `showcase_service.dart` |
| `showcaseKeys` | `List<GlobalKey>` | Ordered list from `ShowcaseKeys.*Tour` |

### Lifecycle methods

| Method | When to call |
|--------|-------------|
| `initShowcase()` | In `initState()`. Pass `autoSchedule: false` when loading gate hide targets. |
| `scheduleShowcase()` | After loading gate resolve. Trigger tour check manually. |
| `disposeShowcase()` | In `dispose()`. |

### Loading gate pattern

Screens show loading indicator before content:

```dart
@override
void initState() {
  super.initState();
  initShowcase(autoSchedule: false); // don't check yet
}

@override
Widget build(BuildContext context) {
  final isLoading = ref.watch(myProvider.select((s) => s.isLoading));

  // Catch the loading → loaded transition.
  ref.listen(myProvider.select((s) => s.isLoading), (prev, next) {
    if (prev == true && next == false) scheduleShowcase();
  });

  // Handle already-cached data (prev is null on first listen attachment).
  if (!isLoading) scheduleShowcase();

  // ...
}
```

### How the mixin works

1. `initShowcase()` call `ShowcaseView.register(scope:, enableAutoScroll: true, onFinish:, onDismiss:)`.
2. Post-frame callback check `TickerMode.of(context)`. If `false` (offstage tab), defer via `_needsShowcaseRetry`.
3. If active, read `showcaseServiceProvider`, check if tour seen.
4. If unseen, call `ShowcaseView.getNamed(scope).startShowCase(keys, delay: Duration(milliseconds: 300))`.
5. `onFinish` + `onDismiss` both call `completeInProgressTour()` on service, persist completion.

### TickerMode and offstage branches

`StatefulShellRoute` keep all branch screens alive but wrap inactive ones in `TickerMode(enabled: false)`. No guard → offstage screens call `startShowCase()`, fight active tab tour.

Mixin handle via two fields + `didChangeDependencies` override:

- `_needsShowcaseRetry` — set `true` when `TickerMode` is `false` at schedule time.
- `_dependenciesInitialised` — skip first `didChangeDependencies` call (fires before build).
- On tab activation (`TickerMode` flips to `true`), `didChangeDependencies` re-call `scheduleShowcase()`.

## AppShowcaseTarget

Stateful wrapper around `Showcase`. Must stay aligned with screen's named scope.

```dart
AppShowcaseTarget(
  scope: ShowcaseConstants.myFeatureScope,
  showcaseKey: ShowcaseKeys.myFeatureStep1,
  title: ShowcaseStrings.myFeatureStep1Title,
  description: ShowcaseStrings.myFeatureStep1Description,
  child: const SomeChildWidget(),
)
```

### Target placement

Wrap *specific* widget to highlight — not parent container. Tooltip anchor to wrapped widget bounds. Wrap big parent → highlight cover whole section not intended element.

### Parameters

| Param | Required | Default | Notes |
|-------|----------|---------|-------|
| `scope` | Yes | — | Same `ShowcaseConstants.*` screen registered in `ShowcaseScreenMixin` |
| `showcaseKey` | Yes | — | `GlobalKey` from `ShowcaseKeys` |
| `title` | Yes | — | String from `ShowcaseStrings` |
| `description` | Yes | — | String from `ShowcaseStrings` |
| `child` | Yes | — | Widget to highlight |
| `tooltipPosition` | No | Auto | Force tooltip above/below/left/right |
| `targetPadding` | No | `EdgeInsets.zero` | Padding around highlight |
| `disposeOnTap` | No | `null` | Dismiss on tap. **Must pair w/ `onTargetClick`** — alone asserts in tests (see [Constraints](#constraints)). |
| `onTargetClick` | No | `null` | Callback when target tapped |
| `onBarrierClick` | No | `null` | Callback when barrier tapped |

### Applied design tokens

Wrapper apply app design tokens consistently. Typical values:

```dart
tooltipBackgroundColor: theme.surfaceBright,   // a visible surface color
overlayColor: theme.background,
overlayOpacity: 0.85,
targetBorderRadius: BorderRadius.circular(radiusLg),
disableMovingAnimation: true,
```

Arrow color inherit `tooltipBackgroundColor`. No skip/next buttons.

### Scope rule

Named scopes strict.

- Pass same `scope` screen registered in `initShowcase()`.
- Do not build `Showcase` before scope exist.
- Scope not registered yet → render raw `child`.

Avoid runtime assertion:

```text
Please register [ShowcaseView] first by calling [ShowcaseView.register()]
```

### Scope identity (v5 re-registration bug)

`isRegistered` guard not enough alone. `showcaseview` v5 can replace the `ShowcaseScope` object in its internal map when `ShowcaseView.register` is called for an existing scope name. Existing `Showcase` widgets still hold old `ShowcaseScope` ref via `_showCaseWidgetManager` field. Next `didUpdateWidget`, `_updateControllerValues` detect identity flip, reassign field, call `_controller` getter — lookup controller in **new** (empty) `ShowcaseScope`. Assertion fires:

```text
'package:showcaseview/src/showcase/showcase_service.dart':
Failed assertion: line 177 pos 7: 'controller != null'
```

Debug → resulting `ErrorWidget` has unbounded intrinsic width, produce massive `RenderFlex overflowed` errors inside `Row` (e.g. `AppBar.actions`).

Triggers: any path calling `ShowcaseView.register` twice for same scope name during single widget lifetime (hot reload races, duplicate screen instances during navigation transitions, `MediaQuery` rebuild cascades, etc.).

**Defense in `AppShowcaseTarget`:** track `ShowcaseScope` object `identityHashCode` between builds. On change, skip rendering `Showcase` one frame so stale `_ShowcaseState` dispose clean, then remount so `initState` re-register controller under new scope.

```dart
class _AppShowcaseTargetState extends State<AppShowcaseTarget> {
  int? _lastScopeIdentity;
  bool _skipShowcaseThisFrame = false;

  @override
  Widget build(BuildContext context) {
    final service = ShowcaseService.instance;
    if (!service.isRegistered(scope: widget.scope)) {
      _lastScopeIdentity = null;
      return widget.child;
    }

    final currentIdentity =
        identityHashCode(service.getScope(scope: widget.scope));
    if (_lastScopeIdentity != null &&
        _lastScopeIdentity != currentIdentity &&
        !_skipShowcaseThisFrame) {
      _skipShowcaseThisFrame = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!context.mounted) return;
        setState(() => _skipShowcaseThisFrame = false);
      });
    }
    _lastScopeIdentity = currentIdentity;

    if (_skipShowcaseThisFrame) return widget.child;

    return Showcase(/* ... */);
  }
}
```

`Showcase` `GlobalKey` tolerate one-frame absence from tree. Do not wrap in `KeyedSubtree` with swapped key — `GlobalKey` migrate state across remount, bug persist.

## ShowcaseService

Riverpod provider wrapping `SharedPreferences`. Track tour completion per user scope with session + persistent keys.

```dart
@Riverpod(keepAlive: true)
Future<IShowcaseService> showcaseService(Ref ref) async { ... }
```

### Interface

```dart
abstract interface class IShowcaseService {
  Future<bool> shouldShowTour(ShowcaseTour tour, {required String scope});
  Future<void> markTourSeen(ShowcaseTour tour, {required String scope});
  void setInProgressTour(ShowcaseTour tour, {required String scope});
  Future<void> completeInProgressTour();
  Future<void> resetToursForScope(String scope);
  Future<void> resetAllKnownScopes();
}
```

### Tour enum

One case per screen with tour:

```dart
enum ShowcaseTour { screenA, screenB, screenC }
```

### Key storage scheme

Two keys per tour:
- **Session:** `showcase_session_{tour}_{scope}_v{version}` — prevent re-run during same app session
- **Persistent:** `showcase_seen_{tour}_{scope}_v{version}` — survive app restart

Version bump force clean replay for existing installs.

## ShowcaseKeys

Static `GlobalKey` instances + ordered tour lists:

```dart
abstract final class ShowcaseKeys {
  // Individual keys — one per highlighted widget
  static final featureStepA = GlobalKey();
  static final featureStepB = GlobalKey();
  static final featureStepC = GlobalKey();

  // Ordered tour list — order = step order
  static List<GlobalKey> featureTour = [
    featureStepA,
    featureStepB,
    featureStepC,
  ];
}
```

## Adding a Tour to a New Screen

1. **Add scope** in `ShowcaseConstants`:
   ```dart
   static const String myFeatureScope = 'my-feature';
   ```

2. **Add keys** in `ShowcaseKeys`:
   ```dart
   static final myFeatureStep1 = GlobalKey();
   static final myFeatureStep2 = GlobalKey();
   static List<GlobalKey> myFeatureTour = [myFeatureStep1, myFeatureStep2];
   ```

3. **Add tour enum** in `ShowcaseService`:
   ```dart
   enum ShowcaseTour { ..., myFeature }
   ```

4. **Add strings** in `ShowcaseStrings`:
   ```dart
   static const String myFeatureStep1Title = '...';
   static const String myFeatureStep1Description = '...';
   ```

5. **Mix into screen**:
   ```dart
   class MyScreenState extends ConsumerState<MyScreen> with ShowcaseScreenMixin {
     @override String get showcaseScope => ShowcaseConstants.myFeatureScope;
     @override ShowcaseTour get showcaseTour => ShowcaseTour.myFeature;
     @override List<GlobalKey> get showcaseKeys => ShowcaseKeys.myFeatureTour;

     @override void initState() { super.initState(); initShowcase(); }
     @override void dispose() { disposeShowcase(); super.dispose(); }
   }
   ```

6. **Wrap targets** in `build()`:
   ```dart
   AppShowcaseTarget(
     scope: ShowcaseConstants.myFeatureScope,
     showcaseKey: ShowcaseKeys.myFeatureStep1,
     title: ShowcaseStrings.myFeatureStep1Title,
     description: ShowcaseStrings.myFeatureStep1Description,
     child: const MyWidget(),
   )
   ```

## Testing

Override `showcaseServiceProvider` in tests to prevent tours starting:

```dart
final container = ProviderContainer(
  overrides: [
    showcaseServiceProvider.overrideWith(
      (ref) async => FakeShowcaseService(),
    ),
  ],
);
```

`FakeShowcaseService` return `false` from `shouldShowTour` → no tour run in tests.

### Widgets containing AppShowcaseTarget

Most widget tests need no extra setup. Scope-aware wrapper render raw `child` until named scope exist.

Test need real `Showcase` behavior → register same named scope as production:

```dart
setUp(() => ShowcaseView.register(scope: ShowcaseConstants.myFeatureScope));
```

Do not register default anonymous scope when production use named scope.

## Resetting Tours (Shell Route Caveat)

`StatefulShellRoute` keep branch screens alive. After `resetAllKnownScopes()` clear storage, each screen `_hasAttemptedTour` flag still `true` → `scheduleShowcase()` return early. Solution: reset-signal provider alive screens listen to.

```dart
// In showcase_service.dart
@Riverpod(keepAlive: true)
class ShowcaseResetSignal extends _$ShowcaseResetSignal {
  @override
  int build() => 0;

  void notify() => state++;
}
```

Mixin listen + reset on change. MUST store `ProviderSubscription` handle + close in `disposeShowcase()`. Bare `ref.listenManual` leaks across long-lived shell branch lifetime.

```dart
ProviderSubscription<int>? _showcaseResetSubscription;

// In initShowcase()
_showcaseResetSubscription?.close();
_showcaseResetSubscription = ref.listenManual(showcaseResetSignalProvider, (prev, next) {
  if (prev == next) return;
  _hasAttemptedTour = false;
  _needsShowcaseRetry = true;
  scheduleShowcase();
});

void disposeShowcase() {
  _showcaseResetSubscription?.close();
  _showcaseResetSubscription = null;
  // ... unregister scope etc.
}
```

The `prev == next` guard handles all transitions, including the first
post-reset signal. Do not require `prev != null`.

After reset tours, trigger signal:

```dart
await service.resetAllKnownScopes();
ref.read(showcaseResetSignalProvider.notifier).notify();
```

### Replay not starting: first checks

1. `startShowCase()` must receive the full ordered tour key list.
2. Do not pre-filter with `key.currentContext` or mounted checks.
3. Reset listener must react on value change (`prev == next` early return),
   not `prev != null`.

Anti-pattern:

```dart
final activeKeys = ShowcaseKeys.settingsTour
    .where((key) => key.currentContext?.mounted ?? false)
    .toList();
if (activeKeys.isEmpty) return;
ShowcaseView.getNamed(scope).startShowCase(activeKeys);
```

Correct:

```dart
ShowcaseView.getNamed(scope).startShowCase(
  List<GlobalKey>.from(ShowcaseKeys.settingsTour),
);
```

## Test-Env Safe Service Read

Widget tests lack Hive init. Raw `await ref.read(showcaseServiceProvider.future)` throws `Box not found` → bubbles into fire-and-forget (`onFinish`/`onDismiss`/`scheduleShowcase`), spams logs.

Wrap in mixin-local helper. Fire-and-forget callers null-check + early-return.

```dart
Future<IShowcaseService?> _readShowcaseServiceOrNull() async {
  try {
    return await ref.read(showcaseServiceProvider.future);
  } on Object catch (e, st) {
    if (_isTestEnvBoxMissing(e)) return null;
    Crash.error(e, st, reason: 'ShowcaseScreenMixin.readService');
    return null;
  }
}

bool _isTestEnvBoxMissing(Object e) {
  final text = e.toString();
  return text.contains('Box not found') || text.contains('provider that is in error state');
}
```

Call sites drop `try/catch`. Null = skip:

```dart
onFinish: () {
  unawaited(Future<void>.microtask(() async {
    final service = await _readShowcaseServiceOrNull();
    if (service == null) return;
    await service.completeInProgressTour();
  }));
}
```

## Sync Integration

Tour state local by default. Apps with remote sync must push + pull tour completion so tours don't replay on new devices.

### The Problem

Tour completion live in per-scope local service. Remote settings live in separate repo. Settings push omit tour state → every sync silently reset it. Settings pull restore tour state for only one scope → other screens replay tours.

### Push: Include Tour State in Remote Settings

Remote settings object must include `tourCompleted` field (or equivalent boolean). Callback pattern avoids tight coupling:

```dart
// Repository interface
typedef TourCompletionGetter = Future<bool> Function();

abstract interface class ISettingsRepository {
  void setTourCompletionGetter(TourCompletionGetter getter);
  // ...
}

// During sync setup
settingsRepo.setTourCompletionGetter(
  () => showcaseService.hasAnyCompletedTour(),
);

// In the push method
final tourCompleted = await _tourCompletionGetter?.call() ?? false;
```

**Rule:** Build remote data object → include every field schema define. Omit field → send default, overwrite remote copy.

### Pull: Restore All Scopes

Single boolean (`tourCompleted: true`) mean user completed tours on at least one screen. On new device, mark **every** scope so no screen replay tour.

```dart
if (remoteSettings.tourCompleted) {
  for (final scope in allScopes) {
    await showcaseService.markAllToursCompleted(scope: scope);
  }
}
```

Keep centralized scope list → new scopes handled auto.

**Rule:** Boolean representing multiple scopes must restore all. Hardcode single scope → partial restoration.

### Cleanup

Null callback on logout or remote disconnect. Stale ref to disposed service crash next push.

### Checklist

Sync tour state (or any cross-service field):

1. Add callback on repo interface to query external service.
2. Wire callback during sync setup.
3. Null it during cleanup.
4. Include field in both push + pull paths.
5. Restore all scopes/variants in pull path.
6. Test: push include field, pull restore all scopes, cleanup null callback.

## Constraints

- **v5 API only.** No v4 patterns (`ShowCaseWidget.of(context)`).
- **No skip/next buttons.** User tap anywhere on overlay to advance.
- **Never filter keys** with `key.currentContext != null` before passing to `startShowCase()`. Pass full list.
  In `showcaseview` v5, key presence in the internal controller registry is
  the readiness source; `currentContext` checks can drop valid tour keys.
- **`ShowcaseView.getNamed(scope)`** throw if scope not registered. Mixin wrap in try-catch.
- **Every `AppShowcaseTarget` must get same named scope** screen registered in `ShowcaseScreenMixin`. Default and named scopes not interchangeable.
- **Do not build `Showcase` before named scope exist.** Render plain child until registration done.
- **Do not use `disposeOnTap` without `onTargetClick`** — cause assertion failures in tests.

## Recap

1. MUST use `ShowcaseScreenMixin on ConsumerState` — call `initShowcase()` in `initState()` and `disposeShowcase()` in `dispose()`. Skipping either leaks the named scope registration and breaks subsequent tour starts.
2. MUST use `AppShowcaseTarget` styled wrapper for all showcase targets — NEVER use the bare `Showcase` widget. The wrapper enforces consistent styling and the named-scope requirement.
3. MUST NOT start tours during loading state transitions — `ref.listen` on loading state and guard `scheduleShowcase()` so it only fires after the loading gate resolves. Starting during load drops tour keys before they are registered.

