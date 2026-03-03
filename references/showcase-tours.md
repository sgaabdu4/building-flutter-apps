# Showcase Guided Tours

First-run guided tours using `showcaseview` v5. Each screen manages its own tour via a shared mixin, a styled wrapper widget, and a persistence service.

## Package

```yaml
dependencies:
  showcaseview: ^5.0.1
```

## Architecture

Six files form the showcase system:

| File | Type | Purpose |
|------|------|---------|
| `showcase_screen_mixin.dart` | Mixin | Lifecycle: register scope, check, start, dispose |
| `app_showcase_target.dart` | StatelessWidget | Styled `Showcase` wrapper bound to design tokens |
| `showcase_service.dart` | Interface + Impl + Signal | Persists tour completion; `ShowcaseResetSignal` notifies alive screens |
| `showcase_keys.dart` | Abstract final class | `GlobalKey` registry and ordered tour lists |
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

Mixin on `ConsumerState`. Screens override three getters and call two lifecycle methods:

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
| `showcaseScope` | `String` | A `ShowcaseConstants.*` scope name |
| `showcaseTour` | `ShowcaseTour` | Enum from `showcase_service.dart` |
| `showcaseKeys` | `List<GlobalKey>` | Ordered list from `ShowcaseKeys.*Tour` |

### Lifecycle methods

| Method | When to call |
|--------|-------------|
| `initShowcase()` | In `initState()`. Pass `autoSchedule: false` when a loading gate hides targets. |
| `scheduleShowcase()` | After loading gate resolves, to trigger the tour check manually. |
| `disposeShowcase()` | In `dispose()`. |

### Loading gate pattern

Screens that show a loading indicator before content:

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

1. `initShowcase()` calls `ShowcaseView.register(scope:, enableAutoScroll: true, onFinish:, onDismiss:)`.
2. Post-frame callback checks `TickerMode.of(context)`. If `false` (offstage tab), defers via `_needsShowcaseRetry`.
3. If active, reads `showcaseServiceProvider` to check if tour was already seen.
4. If unseen, calls `ShowcaseView.getNamed(scope).startShowCase(keys, delay: Duration(milliseconds: 300))`.
5. `onFinish` and `onDismiss` both call `completeInProgressTour()` on the service, persisting completion.

### TickerMode and offstage branches

`StatefulShellRoute` keeps all branch screens alive but wraps inactive ones in `TickerMode(enabled: false)`. Without a guard, offstage screens call `startShowCase()` and fight the active tab's tour.

The mixin handles this with two fields and a `didChangeDependencies` override:

- `_needsShowcaseRetry` — set `true` when `TickerMode` is `false` at schedule time.
- `_dependenciesInitialised` — skips the first `didChangeDependencies` call (fires before build).
- On tab activation (`TickerMode` flips to `true`), `didChangeDependencies` re-calls `scheduleShowcase()`.

## AppShowcaseTarget

Thin wrapper around `Showcase` that applies design tokens:

```dart
AppShowcaseTarget(
  showcaseKey: ShowcaseKeys.myFeatureStep1,
  title: ShowcaseStrings.myFeatureStep1Title,
  description: ShowcaseStrings.myFeatureStep1Description,
  child: const SomeChildWidget(),
)
```

### Target placement

Wrap the *specific* widget you want highlighted — not a parent container. The tooltip anchors to the wrapped widget's bounds. Wrapping a large parent makes the highlight appear on the entire section instead of the intended element.

### Parameters

| Param | Required | Default | Notes |
|-------|----------|---------|-------|
| `showcaseKey` | Yes | — | `GlobalKey` from `ShowcaseKeys` |
| `title` | Yes | — | String from `ShowcaseStrings` |
| `description` | Yes | — | String from `ShowcaseStrings` |
| `child` | Yes | — | Widget to highlight |
| `tooltipPosition` | No | Auto | Force tooltip above/below/left/right |
| `targetPadding` | No | `EdgeInsets.zero` | Padding around highlight |
| `disposeOnTap` | No | `null` | Dismiss tooltip on tap |
| `onTargetClick` | No | `null` | Callback when target tapped |
| `onBarrierClick` | No | `null` | Callback when barrier tapped |

### Applied design tokens

The wrapper should apply your app's design tokens consistently. Typical values:

```dart
tooltipBackgroundColor: theme.surfaceBright,   // a visible surface color
overlayColor: theme.background,
overlayOpacity: 0.85,
targetBorderRadius: BorderRadius.circular(radiusLg),
disableMovingAnimation: true,
```

Arrow color inherits `tooltipBackgroundColor`. No skip/next buttons.

## ShowcaseService

Riverpod provider wrapping `SharedPreferences`. Tracks tour completion per user scope with session and persistent keys.

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

One case per screen that has a tour:

```dart
enum ShowcaseTour { screenA, screenB, screenC }
```

### Key storage scheme

Two keys per tour:
- **Session:** `showcase_session_{tour}_{scope}_v{version}` — prevents re-run during same app session
- **Persistent:** `showcase_seen_{tour}_{scope}_v{version}` — survives app restart

Version bump forces a clean replay for existing installs.

## ShowcaseKeys

Static `GlobalKey` instances and ordered tour lists:

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

Order in the list determines step order in the guided tour.

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
     showcaseKey: ShowcaseKeys.myFeatureStep1,
     title: ShowcaseStrings.myFeatureStep1Title,
     description: ShowcaseStrings.myFeatureStep1Description,
     child: const MyWidget(),
   )
   ```

## Testing

Override `showcaseServiceProvider` in tests to prevent tours from starting:

```dart
final container = ProviderContainer(
  overrides: [
    showcaseServiceProvider.overrideWith(
      (ref) async => FakeShowcaseService(),
    ),
  ],
);
```

`FakeShowcaseService` returns `false` from `shouldShowTour` so no tour runs during tests.

### Widgets containing AppShowcaseTarget

When a widget's `build()` includes `AppShowcaseTarget`, its `Showcase` child calls `ShowcaseService.instance.getScope()` in `initState`. Without a registered scope, tests throw. Add a `setUp` call:

```dart
setUp(() => ShowcaseView.register());
```

This registers a default scope so `Showcase` can resolve its parent. No `scope:` argument needed — the default suffices for tests that don't start actual tours.

## Resetting Tours (Shell Route Caveat)

`StatefulShellRoute` keeps branch screens alive. After `resetAllKnownScopes()` clears storage, each screen's `_hasAttemptedTour` flag is still `true` — so `scheduleShowcase()` returns early. Solution: a reset-signal provider that alive screens listen to.

```dart
// In showcase_service.dart
@Riverpod(keepAlive: true)
class ShowcaseResetSignal extends _$ShowcaseResetSignal {
  @override
  int build() => 0;

  void notify() => state++;
}
```

The mixin listens and resets on change:

```dart
// In initShowcase()
ref.listenManual(showcaseResetSignalProvider, (prev, next) {
  if (prev != null && prev != next) {
    _hasAttemptedTour = false;
    _needsShowcaseRetry = true;
    scheduleShowcase();
  }
});
```

After resetting tours, trigger the signal:

```dart
await service.resetAllKnownScopes();
ref.read(showcaseResetSignalProvider.notifier).notify();
```

## Constraints

- **v5 API only.** Do not use v4 patterns (`ShowCaseWidget.of(context)`).
- **No skip/next buttons.** Users tap anywhere on the overlay to advance.
- **Never filter keys** with `key.currentContext != null` before passing to `startShowCase()`. Pass the full list.
- **`ShowcaseView.getNamed(scope)`** throws if scope is not registered. The mixin wraps this in try-catch.
- **Do not use `disposeOnTap` without `onTargetClick`** — causes assertion failures in tests.
