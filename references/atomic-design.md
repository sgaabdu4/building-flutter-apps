# Atomic Design

Build UI from small, composable pieces: tokens → atoms → molecules → organisms → templates → pages.

## Hierarchy

```
Tokens     →  Raw values: colors, spacing, radii, typography
Atoms      →  Single-purpose widgets: buttons, badges, text fields
Molecules  →  Combine atoms: avatar tiles, stat cards, search bars
Organisms  →  Business-aware groups: data grids, navigation headers
Templates  →  Page structures with slots for organisms
Pages      →  Screens that compose templates and connect state
```

## Tokens

No widget hardcodes a color, spacing, radius, font size, or icon size. Use token classes.

### Spacing

```dart
// core/theme/spacing.dart
abstract final class Spacing {
  static const double s4 = 4;
  static const double s8 = 8;
  static const double s12 = 12;
  static const double s16 = 16;
  static const double s24 = 24;
  static const double s32 = 32;
  static const double s48 = 48;
  static const double s64 = 64;
}
```

### Radii

```dart
// core/theme/radii.dart
abstract final class Radii {
  static const double r8 = 8;
  static const double r12 = 12;
  static const double r16 = 16;
  static const double full = 999;

  static const rounded8 = BorderRadius.all(Radius.circular(r8));
  static const rounded12 = BorderRadius.all(Radius.circular(r12));
  static const rounded16 = BorderRadius.all(Radius.circular(r16));
  static const roundedFull = BorderRadius.all(Radius.circular(full));
}
```

### Icon Sizes

```dart
// core/theme/icon_sizes.dart
abstract final class IconSizes {
  static const double s16 = 16;
  static const double s20 = 20;
  static const double s24 = 24;
  static const double s32 = 32;
  static const double s48 = 48;
}
```

### Typography

Extend the Material `TextTheme`:

```dart
// core/theme/app_theme.dart
ThemeData buildAppTheme() {
  return ThemeData(
    colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
    textTheme: const TextTheme(
      headlineLarge: TextStyle(fontSize: 32, fontWeight: FontWeight.bold),
      titleMedium: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      bodyMedium: TextStyle(fontSize: 14),
      labelSmall: TextStyle(fontSize: 11, letterSpacing: 0.5),
    ),
  );
}
```

Access via `context.textTheme.titleMedium` (see [extensions-utilities.md](extensions-utilities.md)), never a raw `TextStyle(fontSize: 16)`.

### Colors

Use `ColorScheme` from Material 3 via `context.colors`:

```dart
final colors = context.colors;
Container(
  color: colors.primaryContainer,
  child: Text('Title', style: TextStyle(color: colors.onPrimaryContainer)),
)
```

For semantic constants (status, charts):

```dart
// core/theme/semantic_colors.dart
abstract final class SemanticColors {
  static const success = Color(0xFF2E7D32);
  static const warning = Color(0xFFF9A825);
  static const error = Color(0xFFC62828);
  static const info = Color(0xFF1565C0);
}
```

## Atoms

Single-element, stateless widgets. No business logic, no provider access.

### Rules

- One visual element per atom
- Accept data through constructor parameters only
- No `ref.watch` or `ref.read`
- Always `const` constructor
- Use tokens for all measurements

### Example

```dart
// core/widgets/atoms/app_badge.dart
class AppBadge extends StatelessWidget {
  const AppBadge({super.key, required this.label, this.color});

  final String label;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final scheme = context.colors;
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: Spacing.s8,
        vertical: Spacing.s4,
      ),
      decoration: BoxDecoration(
        color: color ?? scheme.primaryContainer,
        borderRadius: Radii.roundedFull,
      ),
      child: Text(
        label,
        style: context.textTheme.labelSmall?.copyWith(
          color: scheme.onPrimaryContainer,
        ),
      ),
    );
  }
}
```

Common atoms: `AppBadge`, `AppIconButton`, `AppTextField`, `LoadingIndicator`, `AppDivider`, `AppAvatar`.

## Molecules

Combine 2–4 atoms into a unit. No provider access.

### Rules

- Compose atoms and basic layout/Material widgets (`ListTile`, `Card`, `Column`, `Row`)
- Wrap frequently restyled Material components as atoms first
- No `ref.watch` or `ref.read`
- Accept data via constructor

### Examples

```dart
// core/widgets/molecules/user_tile.dart
class UserTile extends StatelessWidget {
  const UserTile({
    super.key,
    required this.name,
    required this.subtitle,
    this.avatarUrl,
    this.onTap,
  });

  final String name;
  final String subtitle;
  final String? avatarUrl;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: AppAvatar(url: avatarUrl, fallback: name[0]),
      title: Text(name, style: context.textTheme.titleMedium),
      subtitle: Text(subtitle),
      onTap: onTap,
    );
  }
}
```

```dart
// core/widgets/molecules/stat_card.dart
class StatCard extends StatelessWidget {
  const StatCard({
    super.key,
    required this.label,
    required this.value,
    this.icon,
    this.trend,
  });

  final String label;
  final String value;
  final IconData? icon;
  final double? trend;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(Spacing.s16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                if (icon != null) ...[
                  Icon(icon, size: IconSizes.s20, color: colors.primary),
                  const SizedBox(width: Spacing.s8),
                ],
                Text(label, style: context.textTheme.labelSmall),
              ],
            ),
            const SizedBox(height: Spacing.s8),
            Text(value, style: context.textTheme.headlineLarge),
            if (trend != null) ...[
              const SizedBox(height: Spacing.s4),
              AppBadge(
                label: '${trend! >= 0 ? '+' : ''}${trend!.toStringAsFixed(1)}%',
                color: trend! >= 0 ? SemanticColors.success : SemanticColors.error,
              ),
            ],
          ],
        ),
      ),
    );
  }
}
```

## Organisms

Groups of molecules and atoms that form a distinct UI section.

### Rules

- May use `ref.watch` and `ref.read` (not required — data-only organisms are valid)
- Compose molecules and atoms
- Represent a distinct page section (header, grid, comment list)
- Feature-specific: `features/x/presentation/widgets/`
- Shared: `core/widgets/organisms/`

### Examples

```dart
// core/widgets/organisms/stats_row.dart
class StatsRow extends StatelessWidget {
  const StatsRow({super.key, required this.stats});

  final List<({String label, String value, IconData? icon, double? trend})> stats;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: stats
          .map((s) => Expanded(
                child: StatCard(
                  label: s.label,
                  value: s.value,
                  icon: s.icon,
                  trend: s.trend,
                ),
              ))
          .toList(),
    );
  }
}
```

```dart
// features/products/presentation/widgets/product_grid.dart
class ProductGrid extends ConsumerWidget {
  const ProductGrid({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final items = ref.watch(
      productProvider.select((s) => s.items),
    );

    return GridView.builder(
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 2,
        mainAxisSpacing: Spacing.s12,
        crossAxisSpacing: Spacing.s12,
        childAspectRatio: 0.75,
      ),
      itemCount: items.length,
      itemBuilder: (context, index) => ProductCard(product: items[index]),
    );
  }
}
```

## Templates

Define page structure with slots. No business logic, no provider access.

### Rules

- No `ref.watch` or `ref.read`
- Accept widgets via constructor (slots)
- Handle responsive breakpoints here

### Examples

```dart
// core/widgets/templates/list_detail_template.dart
class ListDetailTemplate extends StatelessWidget {
  const ListDetailTemplate({
    super.key,
    required this.list,
    required this.detail,
    this.listFlex = 1,
    this.detailFlex = 2,
  });

  final Widget list;
  final Widget detail;
  final int listFlex;
  final int detailFlex;

  @override
  Widget build(BuildContext context) {
    if (context.isExpanded) {
      return Row(
        children: [
          Expanded(flex: listFlex, child: list),
          const VerticalDivider(width: 1),
          Expanded(flex: detailFlex, child: detail),
        ],
      );
    }
    return list;
  }
}
```

```dart
// core/widgets/templates/dashboard_template.dart
class DashboardTemplate extends StatelessWidget {
  const DashboardTemplate({
    super.key,
    required this.header,
    required this.stats,
    required this.body,
  });

  final PreferredSizeWidget header;
  final Widget stats;
  final Widget body;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: header,
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(Spacing.s16),
            child: stats,
          ),
          Expanded(child: body),
        ],
      ),
    );
  }
}
```

## Pages

Pages compose templates with organisms. Connect state to layout here.

### Rules

- Always `ConsumerWidget` or `ConsumerStatefulWidget`
- Watch providers via `ref.watch` with `.select()`
- Compose templates and organisms — no raw layout
- One screen per route

### Example

```dart
// features/products/presentation/screens/product_dashboard_screen.dart
class ProductDashboardScreen extends ConsumerWidget {
  const ProductDashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final isLoading = ref.watch(
      productProvider.select((s) => s.isLoading),
    );

    if (isLoading) {
      return const Scaffold(body: Center(child: LoadingIndicator()));
    }

    return DashboardTemplate(
      header: AppHeader(
        title: 'Products',
        actions: [
          AppIconButton(
            icon: Icons.add,
            onPressed: () => const ProductCreateRoute().go(context),
            tooltip: 'Add product',
          ),
        ],
      ),
      stats: const ProductStatsRow(),
      body: const ProductGrid(),
    );
  }
}
```

## Placement Rules

| Level | Location | Provider Access |
|-------|----------|----------------|
| Tokens | `core/theme/` | No |
| Atoms | `core/widgets/atoms/` | No |
| Molecules | `core/widgets/molecules/` | No |
| Organisms (shared) | `core/widgets/organisms/` | Yes |
| Organisms (feature) | `features/x/widgets/` | Yes |
| Templates | `core/widgets/templates/` | No |
| Pages | `features/x/screens/` | Yes |

## Promotion Rules

- Move to `core/widgets/` when two or more features use a widget with no feature-specific logic
- Extract a new atom when you repeat the same styled element across molecules
- Split an organism that exceeds ~150 lines or handles two unrelated concerns

## Accessibility

For `Semantics` wrappers, `MergeSemantics`, 48x48 tap targets, and contrast ratios, see the Accessibility section in [flutter-optimizations.md](flutter-optimizations.md).

## Theming

Every widget reads from the theme. No raw constants:

```dart
// WRONG
Text('Title', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold))
// RIGHT
Text('Title', style: context.textTheme.titleMedium)

// WRONG
Container(color: Color(0xFF1565C0))
// RIGHT
Container(color: context.colors.primary)
```

Exceptions: `SemanticColors` and `Spacing` tokens — static constants independent of theme mode.
