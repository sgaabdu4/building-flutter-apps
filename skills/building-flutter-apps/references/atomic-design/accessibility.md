# Atomic Design — Accessibility

## Read first

1. Accessibility is UI correctness, not polish.
2. Visible labels, tooltips, semantic labels, and accessibility copy are localized through `AppLocalizations`.
3. Verify text scale and contrast locally; do not globally clamp text scale to hide layout problems.

## Trigger

Signals: semantics, tooltip, semanticLabel, image alt text, tap target, contrast, text scaling, icon-only button.
Before code: output `Reading: accessibility.md`.

## Controls

Action/icon buttons need localized tooltips and at least 48x48 tap targets:

```dart
IconButton(
  tooltip: l10n.deleteOrderTooltip,
  icon: const Icon(Icons.delete_outline),
  onPressed: onDelete,
)
```

Lints: `prefer_action_button_tooltip`, `avoid_hardcoded_strings`.

## Images

Informative images need localized semantic labels:

```dart
Image.network(
  product.imageUrl,
  semanticLabel: l10n.productImageLabel(product.name),
)
```

Decorative images are excluded:

```dart
Image.asset(
  'assets/confetti.png',
  excludeFromSemantics: true,
)
```

Lint: `avoid_missing_image_alt`.

## Styled copy

Prefer `Text.rich` over raw `RichText` so app text configuration, scaling, and defaults are preserved.

Lint: `prefer_text_rich`.

## Text scale

Do not clamp app-wide text scale in `MaterialApp.builder`. Fix the layout where overflow occurs and test large text locally.

Lint: `a11y_text_scale_clamp`.

## Design-system placement

Accessibility behavior belongs in atoms and promoted primitives where it can be reused. Feature widgets should consume accessible primitives rather than repeat tooltip, target-size, and contrast logic.

## Related

- [atomic-design.md](../atomic-design.md#accessibility)
- [flutter-optimizations.md](../flutter-optimizations.md#semantics)
