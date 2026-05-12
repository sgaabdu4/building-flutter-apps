# Flutter Optimizations

Flutter tricks: render, scroll, animate, layout, concurrency, size, a11y, adaptive.

## Trigger

Signals: shrinkWrap, FadeTransition, Sliver, RepaintBoundary, Impeller, Isolate.run, AnimationController
Before generating code in this area, output verbatim: `Reading: flutter-optimizations.md`


## Contents

- [Keys](#keys)
- [Slivers](#slivers)
- [Avoid `shrinkWrap: true`](#avoid-shrinkwrap-true)
- [Animations](#animations)
- [Rendering Costs](#rendering-costs)
- [Isolates](#isolates)
- [App Size](#app-size)
- [Accessibility](#accessibility)
- [Adaptive & Responsive](#adaptive--responsive)
- [Build Modes](#build-modes)
- [Impeller](#impeller)
- [Frame Budget](#frame-budget)
- [RepaintBoundary](#repaintboundary)
- [Preserving Tab State](#preserving-tab-state)
- [Post-Frame Callbacks](#post-frame-callbacks)

## Keys

| Situation | Key Type | Example |
|-----------|----------|---------|
| Reorderable list | `ValueKey` | `ValueKey(item.id)` |
| Heterogeneous children | `ValueKey` | Items with different types |
| Multiple similar siblings | `ObjectKey` | `ObjectKey(item)` |
| Force widget recreation | `UniqueKey` | `UniqueKey()` |
| Access widget state from parent | `GlobalKey` | Form validation |

```dart
ListView.builder(
  itemCount: items.length,
  itemBuilder: (context, index) => ProductCard(
    key: ValueKey(items[index].id),
    product: items[index],
  ),
)
```

Rules:
- Never make key inside `build()` — defeat purpose
- Key only when state preservation matter
- Prefer `ValueKey` > `ObjectKey` > `UniqueKey` > `GlobalKey`

## Slivers

Use `CustomScrollView`, not `ListView` in `SingleChildScrollView`.

```dart
CustomScrollView(
  slivers: [
    SliverAppBar(
      expandedHeight: 200,
      pinned: true,
      flexibleSpace: FlexibleSpaceBar(
        title: Text('Products'),
        background: Image.network(url, fit: BoxFit.cover),
      ),
    ),
    SliverPadding(
      padding: const EdgeInsets.all(Spacing.s16),
      sliver: SliverGrid(
        delegate: SliverChildBuilderDelegate(
          (context, index) => ProductCard(product: items[index]),
          childCount: items.length,
        ),
        gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: 2,
          mainAxisSpacing: Spacing.s12,
          crossAxisSpacing: Spacing.s12,
        ),
      ),
    ),
  ],
)
```

`SliverList` for multi scroll section. `ListView.builder` for simple standalone list. Same-height items → `SliverFixedExtentList` skip layout calc.

## Avoid `shrinkWrap: true`

`shrinkWrap: true` on `ListView`/`GridView` kill lazy load. Measure all children upfront — slow big lists.

| Parent Context | Fix |
|----------------|-----|
| Column/Row | Wrap in `Expanded` or fixed-height `SizedBox` |
| Bottom sheet | `DraggableScrollableSheet` with scroll controller |
| Nested scroll | `CustomScrollView` + `SliverList` (see [Slivers](#slivers)) |

```dart
// WRONG — measures all children at once.
ListView.builder(
  shrinkWrap: true,
)
```

```dart
Column(
  children: [
    const Header(),
    Expanded(
      child: ListView.builder(
        itemBuilder: (context, index) => const SizedBox.shrink(),
      ),
    ),
  ],
)
```

```dart
DraggableScrollableSheet(
  builder: (context, scrollController) => ListView.builder(
    controller: scrollController,
    itemBuilder: (context, index) => const SizedBox.shrink(),
  ),
)
```

## Animations

### Implicit vs Explicit

```
Does the animation repeat or need manual control?
  → No:  Implicit (AnimatedContainer, AnimatedOpacity, AnimatedSwitcher)
  → Yes: Explicit (AnimationController + AnimatedBuilder)
```

```dart
AnimatedContainer(
  duration: const Duration(milliseconds: 300),
  curve: Curves.easeInOut,
  padding: EdgeInsets.all(isExpanded ? Spacing.s24 : Spacing.s8),
  decoration: BoxDecoration(
    color: isSelected ? colors.primaryContainer : colors.surface,
    borderRadius: Radii.rounded12,
  ),
  child: child,
)
```

### AnimatedBuilder — Pass Child

Pass static subtree as `child`, not `builder`. Builder run every frame:

```dart
AnimatedBuilder(
  animation: _controller,
  child: const Icon(Icons.refresh, size: 48),  // built once
  builder: (context, child) {
    return Transform.rotate(
      angle: _controller.value * 2 * pi,
      child: child,  // reused every frame
    );
  },
)
```

### Opacity — Avoid the Widget

`Opacity` trigger `saveLayer()`. Use `FadeTransition` or semi-transparent color:

```dart
// WRONG — calls saveLayer()
Opacity(opacity: 0.5, child: Container(color: Colors.blue))

// RIGHT — no saveLayer
Container(color: Colors.blue.withValues(alpha: 0.5))

// RIGHT — for animated opacity
FadeTransition(opacity: _animation, child: child)
```

### AnimationController Disposal

Always dispose. `SingleTickerProviderStateMixin` one controller, `TickerProviderStateMixin` many:

```dart
class _MyWidgetState extends State<MyWidget>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      duration: const Duration(milliseconds: 300),
      vsync: this,
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }
}
```

## Rendering Costs

### saveLayer() Triggers

| Widget | Trigger |
|--------|---------|
| `Opacity` | Always |
| `ShaderMask` | Always |
| `ColorFilter` | Always |
| `Chip` | When `disabledColorAlpha != 0xff` |
| `Text` | When using `overflowShader` |

### Clipping

Use `borderRadius` on `Container`, not `ClipRRect` wrap. Avoid `Clip.antiAliasWithSaveLayer` — allocate off-screen buffer.

### Intrinsic Layout Passes

`IntrinsicWidth`/`IntrinsicHeight` cause double layout pass. Prefer fixed height or `ConstrainedBox`:

```dart
// EXPENSIVE — double layout pass
IntrinsicHeight(child: Row(children: [/* many children */]))

// BETTER — fixed height
SizedBox(height: 72, child: Row(children: [/* children */]))
```

## Isolates

Move heavy compute off main thread. UI thread render frame <16ms (60fps) or <8ms (120fps).

`Isolate.run` (Dart 3.x) for one-shot heavy work. `compute()` legacy alt:

```dart
final products = await Isolate.run(() {
  final parsed = jsonDecode(jsonString) as List<Object?>;
  return parsed
      .cast<Map<String, dynamic>>()
      .map(ProductModel.fromJson)
      .map((m) => m.toEntity())
      .toList();
});
```

| Task | Use Isolate? |
|------|-------------|
| Parse <100 items | No |
| Parse 1000+ items | Yes |
| Image processing | Yes |
| Cryptographic hashing | Yes |
| Simple math / File I/O | No |

Isolate no access `ref`, providers, Flutter widgets. Pass only simple or serializable objects.

## App Size

### --split-debug-info

Strip debug symbols. Cut size 30–50%:

```bash
flutter build apk --split-debug-info=build/debug-info --obfuscate
flutter build ipa --split-debug-info=build/debug-info --obfuscate
```

Keep debug info dir for crash symbolication.

### Tree Shaking

Help Dart compiler drop dead code:
- Import specific files, not barrel export
- Use `show` to import only needed symbols
- Remove unused deps from `pubspec.yaml`

### Deferred Loading

Split big features into separate download unit:

```dart
import 'heavy_feature.dart' deferred as heavy;

Future<void> loadFeature() async {
  await heavy.loadLibrary();
  // Now safe to use heavy.HeavyWidget()
}
```

### Platform-Specific Assets

Exclude assets from platforms not needing:

```yaml
flutter:
  assets:
    - path: assets/logo.png
    - path: assets/web_worker.js
      platforms: [web]
    - path: assets/desktop_icon.png
      platforms: [windows, linux, macos]
```

### Analyze Build Size

```bash
flutter build apk --analyze-size
```

Open output JSON in DevTools > App Size tool for per-package breakdown.

## Accessibility

### Semantics

```dart
Semantics(
  label: 'Delete product ${product.name}',
  button: true,
  child: IconButton(
    icon: const Icon(Icons.delete),
    onPressed: () => onDelete(product.id),
  ),
)
```

Hide decorative: `ExcludeSemantics(child: decorativeWidget)`.

### Checklist

| Requirement | Target |
|-------------|--------|
| Tap targets | Min 48x48 logical pixels |
| Contrast ratio | Min 4.5:1 (text vs background) |
| Color dependence | Never rely on color alone |
| Screen reader | Every interactive widget has a label |
| Scale factors | UI legible at 200% text scale |

Test with TalkBack (Android) + VoiceOver (iOS) on real devices.

## Adaptive & Responsive

### MediaQuery.sizeOf

Use `MediaQuery.sizeOf`, not `MediaQuery.of` — rebuild only on size change. With context extensions (see [extensions-utilities.md](extensions-utilities.md)):

```dart
@override
Widget build(BuildContext context) {
  if (context.isExpanded) {
    return const TabletLayout();
  }
  return const PhoneLayout();
}
```

### LayoutBuilder

Use when sizing depend on parent constraints, not full window:

```dart
LayoutBuilder(
  builder: (context, constraints) {
    final crossAxisCount = constraints.maxWidth > 600 ? 3 : 2;
    return GridView.builder(
      gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: crossAxisCount,
      ),
      itemBuilder: (context, index) => ItemCard(items[index]),
      itemCount: items.length,
    );
  },
)
```

### Breakpoints

Follow Material 3 window size classes:

| Class | Width | UI |
|-------|-------|-----|
| Compact | < 600 | Single column, bottom nav |
| Medium | 600–839 | Two columns, rail nav |
| Expanded | 840+ | Multi-pane, permanent nav |

## Build Modes

| Mode | Use | Optimizations |
|------|-----|---------------|
| Debug | Development | Hot reload, asserts, no tree shaking |
| Profile | Performance testing | Optimized, with profiling overhead |
| Release | Production | Full AOT, tree shaking, no asserts |

Always profile in **profile mode**. Debug 10x overhead.

## Impeller

Flutter render engine (default iOS 3.29+, Android API 29+ in 3.27+). Pre-compile shaders at build time, kill shader compile jank. No setup.

## Frame Budget

| Display | Budget | Build + Render |
|---------|--------|----------------|
| 60Hz | 16ms | 8ms + 8ms |
| 120Hz | 8ms | 4ms + 4ms |

Frame exceed budget: profile DevTools, check rebuild count, look for intrinsic pass + `saveLayer()`, move heavy work to isolate.

## RepaintBoundary

Wrap subtree in own compositing layer. Use for custom paint, chart, map, widget animate independently. Don't wrap simple widget — each boundary add compositing overhead.

```dart
RepaintBoundary(child: ComplexChart(data: chartData))
```

## Preserving Tab State

Keep tab content alive on switch:

```dart
class _ProductTabState extends State<ProductTab>
    with AutomaticKeepAliveClientMixin {
  @override
  bool get wantKeepAlive => true;

  @override
  Widget build(BuildContext context) {
    super.build(context);  // required
    return const ProductGrid();
  }
}
```

## Post-Frame Callbacks

Defer work til after current frame render:

```dart
@override
void initState() {
  super.initState();
  WidgetsBinding.instance.addPostFrameCallback((_) {
    if (!context.mounted) return;
    ref.read(welcomeProvider.notifier).maybeShowWelcomeMessage();
  });
}

## Recap

1. NEVER use `shrinkWrap: true` on `ListView`/`GridView`. It defeats lazy rendering and causes O(N) layout on every rebuild. Replace with `Slivers` (`SliverList`, `SliverGrid`) inside a `CustomScrollView`.
2. Use `FadeTransition` instead of the `Opacity` widget for fade animations. `Opacity` triggers `saveLayer()` which allocates an offscreen framebuffer on every frame; `FadeTransition` avoids this overhead.
3. MUST dispose every `AnimationController` in `dispose()` or `ref.onDispose()`. Undisposed controllers keep `Ticker` alive, preventing garbage collection and causing memory leaks.

```
