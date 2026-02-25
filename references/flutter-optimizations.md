# Flutter Optimizations

Flutter-specific techniques for rendering, scrolling, animations, layout, concurrency, app size, accessibility, and adaptive UI.

## Keys

Keys preserve widget state when the widget tree changes.

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
- Never create a key inside `build()` — defeats the purpose
- Key only when state preservation matters
- Prefer `ValueKey` > `ObjectKey` > `UniqueKey` > `GlobalKey`

## Slivers

Slivers build scrollable layouts where different sections scroll together. Use `CustomScrollView` instead of nesting `ListView` inside `SingleChildScrollView`.

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

Use `SliverList` when combining multiple scrollable sections. Use `ListView.builder` for simple standalone lists. When all items share the same height, use `SliverFixedExtentList` to skip layout calculation.

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

Pass static subtrees as `child`, not inside `builder`. The builder runs every frame:

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

`Opacity` triggers `saveLayer()`. Use `FadeTransition` or draw with a semi-transparent color:

```dart
// WRONG — calls saveLayer()
Opacity(opacity: 0.5, child: Container(color: Colors.blue))

// RIGHT — no saveLayer
Container(color: Colors.blue.withValues(alpha: 0.5))

// RIGHT — for animated opacity
FadeTransition(opacity: _animation, child: child)
```

### AnimationController Disposal

Always dispose. Use `SingleTickerProviderStateMixin` for one controller, `TickerProviderStateMixin` for multiple:

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

Use `borderRadius` on `Container` instead of wrapping in `ClipRRect`. Avoid `Clip.antiAliasWithSaveLayer` — it allocates an off-screen buffer.

### Intrinsic Layout Passes

`IntrinsicWidth` and `IntrinsicHeight` cause double layout passes. Prefer fixed heights or `ConstrainedBox`:

```dart
// EXPENSIVE — double layout pass
IntrinsicHeight(child: Row(children: [/* many children */]))

// BETTER — fixed height
SizedBox(height: 72, child: Row(children: [/* children */]))
```

## Isolates

Move heavy computation off the main thread. The UI thread must render frames in under 16ms (60fps) or 8ms (120fps).

Use `Isolate.run` (Dart 3.x) for one-shot heavy work. `compute()` is the legacy alternative:

```dart
final products = await Isolate.run(() {
  final parsed = jsonDecode(jsonString) as List;
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

Isolates cannot access `ref`, providers, or Flutter widgets. Pass only simple types or serializable objects.

## App Size

### --split-debug-info

Strips debug symbols. Reduces app size 30–50%:

```bash
flutter build apk --split-debug-info=build/debug-info --obfuscate
flutter build ipa --split-debug-info=build/debug-info --obfuscate
```

Keep the debug info directory for crash symbolication.

### Tree Shaking

Help Dart's compiler remove unreachable code:
- Import specific files, not barrel exports
- Use `show` to import only needed symbols
- Remove unused dependencies from `pubspec.yaml`

### Deferred Loading

Split large features into separate download units:

```dart
import 'heavy_feature.dart' deferred as heavy;

Future<void> loadFeature() async {
  await heavy.loadLibrary();
  // Now safe to use heavy.HeavyWidget()
}
```

### Platform-Specific Assets

Exclude assets from platforms that don't need them:

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

Open the output JSON in DevTools > App Size tool for per-package breakdown.

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

Hide decorative elements: `ExcludeSemantics(child: decorativeWidget)`.

### Checklist

| Requirement | Target |
|-------------|--------|
| Tap targets | Min 48x48 logical pixels |
| Contrast ratio | Min 4.5:1 (text vs background) |
| Color dependence | Never rely on color alone |
| Screen reader | Every interactive widget has a label |
| Scale factors | UI legible at 200% text scale |

Test with TalkBack (Android) and VoiceOver (iOS) on real devices.

## Adaptive & Responsive

### MediaQuery.sizeOf

Use `MediaQuery.sizeOf` instead of `MediaQuery.of` — rebuilds only on size changes. With context extensions (see [extensions-utilities.md](extensions-utilities.md)):

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

Use when sizing depends on parent constraints, not the full window:

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

Always profile in **profile mode**. Debug mode has 10x overhead.

## Impeller

Flutter's rendering engine (default on iOS 3.29+, Android API 29+ in 3.27+). Pre-compiles shaders at build time, eliminating shader compilation jank. No setup required.

## Frame Budget

| Display | Budget | Build + Render |
|---------|--------|----------------|
| 60Hz | 16ms | 8ms + 8ms |
| 120Hz | 8ms | 4ms + 4ms |

If frames exceed budget: profile with DevTools, check rebuild counts, look for intrinsic passes and `saveLayer()`, move heavy work to isolates.

## RepaintBoundary

Wraps a subtree in its own compositing layer. Use for custom paints, charts, maps, and widgets that animate independently. Don't use for simple widgets — each boundary adds compositing overhead.

```dart
RepaintBoundary(child: ComplexChart(data: chartData))
```

## Preserving Tab State

Keep tab content alive when switching tabs:

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

Defer work until after the current frame renders:

```dart
@override
void initState() {
  super.initState();
  WidgetsBinding.instance.addPostFrameCallback((_) {
    SnackBarUtils.showInfo('Welcome');
  });
}
```
