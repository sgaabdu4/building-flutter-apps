# Widget Previews

## Trigger

Signals: @Preview, AppPreviewShell, widget_previews, provider overrides, preview fakes
Before generating code in this area, output verbatim: `Reading: widget-previews.md`


## Rules

1. **MUST** import `package:flutter/widget_previews.dart` only in preview files or preview-only blocks.
2. **MUST** wrap preview targets in the app theme/shell used by production widgets.
3. **MUST** override Riverpod providers with fakes for repository, datasource, auth, config, and clock dependencies.
4. **MUST NOT** call native plugins, `dart:io`, platform channels, Firebase, Hive boxes, or real HTTP from previews.
5. **MUST NOT** add `@Preview` to stateful app screens that require full runtime boot. Create a small preview surface instead.
6. **MUST** keep preview data deterministic and small.
7. **MUST** preserve the central key registry rule. Use `ValueKey(AppWidgetKeys.someAction)`, never inline string keys.

## File Placement

Prefer one preview file next to the widget:

```text
features/products/presentation/widgets/
  product_card.dart
  product_card_preview.dart
```

If the project already has a preview convention, follow it.

## Preview Shell

Create one app-owned shell so every preview gets theme, localization, text
scale, and provider overrides consistently.

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class AppPreviewShell extends StatelessWidget {
  const AppPreviewShell({
    super.key,
    required this.child,
    this.overrides = const [],
  });

  final Widget child;
  final List<Override> overrides;

  @override
  Widget build(BuildContext context) {
    return ProviderScope(
      overrides: overrides,
      child: MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(body: SafeArea(child: child)),
      ),
    );
  }
}
```

## Riverpod Preview Pattern

Keep the widget itself production-real. Override only dependencies.

```dart
import 'package:flutter/material.dart';
import 'package:flutter/widget_previews.dart';

@Preview(name: 'Product card - in stock')
Widget productCardInStockPreview() {
  return AppPreviewShell(
    overrides: [
      productRepositoryProvider.overrideWithValue(
        FakeProductRepository(
          products: const [
            Product(id: 'preview-1', name: 'Suture Kit', price: 24),
          ],
        ),
      ),
    ],
    child: const ProductCard(productId: 'preview-1'),
  );
}
```

## Preview Fakes

Use simple fakes that implement interfaces. Do not mock notifiers directly.

```dart
class FakeProductRepository implements IProductRepository {
  const FakeProductRepository({required this.products});

  final List<Product> products;

  @override
  Future<List<Product>> fetchAll() async => products;

  @override
  Future<Product?> fetchById(String id) async {
    for (final product in products) {
      if (product.id == id) {
        return product;
      }
    }
    return null;
  }
}
```

## Preview Matrix

For reusable widgets, add enough previews to catch real UI states:

| State | Required preview |
|---|---|
| Empty/null | Empty state surface |
| Loading | Skeleton/spinner state if visible |
| Data | Typical content |
| Long text | Longest likely localized string |
| Error | Non-sensitive failure message |
| Theme | Light and dark when supported |
| Width | Compact and expanded when layout changes |

## Limitations

- Previewer runs in a web-like environment. Native plugins and file/database APIs can fail.
- Previewer is visual feedback. Keep widget/unit/E2E tests for behavior.
- If preview setup needs many overrides, the widget is likely too coupled. Move platform or data work behind interfaces.

## Checklist

- [ ] Preview target imports `package:flutter/widget_previews.dart`.
- [ ] Preview target uses `AppPreviewShell` or the project equivalent.
- [ ] Repositories/datasources/services are faked through provider overrides.
- [ ] No native plugin, Hive, Firebase, platform channel, or real HTTP call runs in preview.
- [ ] Long text, empty, error, and compact/expanded states are covered when applicable.
- [ ] No inline string `ValueKey`s were added.

## Recap

1. MUST wrap every preview target in `AppPreviewShell` — every preview gets theme, localization, and provider overrides. Unwrapped previews render without theming and silently miss provider dependencies.
2. MUST override all Riverpod providers with fakes for repositories, datasources, auth, config, and clock — NEVER use real backends in previews. The previewer environment has no platform channels or network.
3. MUST NOT call native plugins, `dart:io`, Firebase, Hive boxes, or real HTTP from previews — these cannot run in the previewer sandbox and will crash the preview tool silently.

