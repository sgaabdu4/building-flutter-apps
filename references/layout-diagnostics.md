# Layout Diagnostics

## Trigger

Signals: layout exception, unbounded height, viewport, LayoutBuilder, Expanded, Flexible
Before generating code in this area, output verbatim: `Reading: layout-diagnostics.md`


## Core Rule

Flutter layout is constraints-first: constraints go down, sizes go up, parent
sets position.

## Error Map

| Error | Usual cause | Preferred fix |
|---|---|---|
| `Vertical viewport was given unbounded height` | `ListView`/`GridView` inside unconstrained `Column` | Use `Expanded`, `Flexible`, fixed constraints, or slivers |
| `InputDecorator cannot have an unbounded width` | `TextField` inside unconstrained `Row` | Wrap field in `Expanded` or `Flexible` |
| `RenderFlex overflowed` | Row/Column child wider/taller than available space | Constrain the child, allow wrapping, or change layout at breakpoint |
| `Incorrect use of ParentDataWidget` | `Expanded`, `Flexible`, or `Positioned` under wrong parent | Move it directly under `Row`/`Column`/`Flex` or `Stack` |
| `RenderBox was not laid out` | Cascading symptom after earlier constraint failure | Fix the first constraint error in logs |

## List in Column

```dart
class ProductListPanel extends StatelessWidget {
  const ProductListPanel({super.key, required this.products});

  final List<Product> products;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        const ProductListHeader(),
        Expanded(
          child: ListView.builder(
            itemCount: products.length,
            itemBuilder: (context, index) {
              return ProductTile(product: products[index]);
            },
          ),
        ),
      ],
    );
  }
}
```

Do not reach for `shrinkWrap` to silence the error. It changes scroll
performance and usually hides the wrong parent constraint.

## Text Field in Row

```dart
class ProductSearchBar extends StatelessWidget {
  const ProductSearchBar({super.key, required this.controller});

  final TextEditingController controller;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        const Icon(Icons.search),
        const SizedBox(width: Spacing.s8),
        Expanded(
          child: TextField(
            controller: controller,
          ),
        ),
      ],
    );
  }
}
```

## Long Text in Row

```dart
class ProductStatusRow extends StatelessWidget {
  const ProductStatusRow({super.key, required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        const Icon(Icons.info),
        const SizedBox(width: Spacing.s8),
        Expanded(
          child: Text(message),
        ),
      ],
    );
  }
}
```

## ParentDataWidget Check

`Expanded` and `Flexible` must be direct children of `Row`, `Column`, or `Flex`.
`Positioned` must be a direct child of `Stack`.

```dart
class CorrectExpandedPlacement extends StatelessWidget {
  const CorrectExpandedPlacement({super.key});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: const [
        HeaderBar(),
        Expanded(child: ProductListView()),
      ],
    );
  }
}
```

## Adaptive Decisions

Base layout on available space, not hardware class or orientation.

```dart
class ProductHomeLayout extends StatelessWidget {
  const ProductHomeLayout({super.key});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth >= 840) {
          return const ProductExpandedLayout();
        }
        if (constraints.maxWidth >= 600) {
          return const ProductMediumLayout();
        }
        return const ProductCompactLayout();
      },
    );
  }
}
```

Material 3 width classes:

| Class | Width | Common pattern |
|---|---:|---|
| Compact | `< 600` | Single column, bottom navigation |
| Medium | `600-839` | Two columns, navigation rail |
| Expanded | `>= 840` | Multi-pane, permanent navigation |

## Keyboard and Insets

- Use `MediaQuery.viewInsetsOf(context)` for keyboard insets.
- Prefer scrollable form bodies over clipping fixed-height forms.
- Keep submit actions reachable with keyboard open.
- Do not globally clamp text scale to fix overflow. Fix the local layout.

## Debug Workflow

1. Read the first layout exception in logs. Ignore cascading errors below it.
2. Identify the nearest unbounded axis: height for vertical scrollables, width for rows/text fields.
3. Add the smallest correct constraint.
4. Resize the app window across compact, medium, and expanded widths.
5. Test large text scale and keyboard-open state.
6. Run widget tests for the changed layout branch when practical.

## Checklist

- [ ] First layout error, not cascading symptom, was fixed.
- [ ] Scrollables inside columns have real constraints.
- [ ] Text fields and long text inside rows are constrained.
- [ ] ParentDataWidgets are direct children of the required parent.
- [ ] Layout decisions use `LayoutBuilder` or `MediaQuery.sizeOf`, not device type.
- [ ] Compact, medium, expanded, keyboard-open, and large text-scale states were checked.

## Recap

1. Fix the FIRST layout exception in the log — cascading errors below it are symptoms, not causes. Fixing a downstream error while the root persists wastes time.
2. NEVER use `shrinkWrap: true` to silence unbounded-height errors — add real constraints or switch to Slivers. `shrinkWrap` forces a full layout pass and is prohibited project-wide.
3. Base adaptive layout decisions on `LayoutBuilder` or `MediaQuery.sizeOf` — NEVER on device type or orientation. Screen size is the correct input; platform/orientation assumptions break on foldables and tablets.

