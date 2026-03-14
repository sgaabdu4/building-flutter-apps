---
name: building-flutter-apps
description: Flutter clean architecture with Riverpod 3.x codegen, Freezed 3.x sealed classes, GoRouter, Hive CE persistence, and ShowcaseView guided tours. Use when building, reviewing, or refactoring Flutter apps that use Riverpod for state management. Covers feature module scaffolding, AsyncNotifier patterns, provider select optimization, Freezed unions and JSON serialization, GoRouter redirects, Hive repositories, pagination, forms, anti-patterns, and testing. Does NOT apply to Provider/BLoC/GetX, non-Flutter frameworks, backend-only Dart, or Firebase-only questions.
license: MIT
metadata:
  author: sgaabdu4
  version: "3.4.0"
  tags: flutter, riverpod, freezed, state-management, clean-architecture, dart, hive, persistence, local-storage, showcaseview, guided-tours, onboarding
---

# Flutter Best Practices

Flutter clean architecture skill using Riverpod 3.x (codegen), Freezed 3.x (sealed classes), and GoRouter.

## Core Stack

| Package | Purpose |
|---------|----------|
| flutter_riverpod + riverpod_annotation + riverpod_generator | State management (codegen) |
| freezed + freezed_annotation | Immutable data classes, unions |
| go_router + go_router_builder | Declarative, type-safe routing |
| json_serializable + build_runner | JSON serialization + code generation |
| showcaseview | First-run guided tours |
| hive_ce + hive_ce_flutter | Local persistence |

## Architecture

Four layers. Dependencies flow inward: Presentation → Repository → Domain → Data.

```
lib/
├── core/           # Shared: theme, utils, widgets, navigation, services
├── features/       # Feature modules (auth, products, home, ...)
│   └── feature_x/
│       ├── data/           # Models, datasources (API/local)
│       ├── domain/         # Entities (pure Dart, no dependencies)
│       ├── repositories/   # Orchestrate data sources, map models → entities
│       └── presentation/   # Notifiers, screens, widgets
└── main.dart
```

Each layer has one job. Domain holds pure Dart entities. Data holds models (with `toEntity()`) and datasources. Repositories bridge them — mapping models→entities. Presentation manages state and UI. **Always create separate data models and domain entities** even for simple features; repositories call `model.toEntity()` to convert.

## Critical Rules

1. **Codegen only** — Use `@riverpod` / `@Riverpod(keepAlive: true)`. Legacy providers (`StateProvider`, etc.) are deprecated and lack codegen benefits.
2. **Sealed classes** — All Freezed classes use `sealed class`, not `abstract class`. Dart's `sealed` enables exhaustive `switch` — the compiler catches missing cases.
3. **No prop drilling** — Child widgets watch providers directly. Passing state through constructors couples parent-child and bypasses `select()` optimization.
4. **Guard async** — Check `if (!ref.mounted) return;` after every `await` in notifiers. The notifier may be disposed while the future is in flight.
5. **Single Ref** — Riverpod 3.0 unified all Ref types. `AutoDisposeRef`, `FutureProviderRef`, `ExampleRef` no longer exist.
6. **Equality filtering** — Providers use `==` to skip redundant notifications. Override `updateShouldNotify` only when default equality is insufficient.
7. **Select in leaves** — Use `ref.watch(provider.select((s) => s.field))` in leaf widgets. Watching full state rebuilds the widget on every field change.
8. **One file per class** — Each entity, model, notifier, screen, and widget gets its own file. Avoids circular imports and keeps codegen output manageable.

## Provider Decision Tree

```
Is it a repository, datasource, or service?
  → @Riverpod(keepAlive: true) — lives forever

Is it a feature notifier (manages mutable state)?
  → @Riverpod(keepAlive: true) class FeatureNotifier extends _$FeatureNotifier

Is it a computed value or one-time fetch?
  → @riverpod (auto-disposes when unused)

Does it need parameters?
  → Add parameters to the generated function (family via codegen)
```

## Freezed Patterns

```dart
// Simple data class
@freezed
sealed class Product with _$Product {
  const Product._();  // Required for adding methods/getters

  const factory Product({
    required String id,
    required String name,
    @Default(0) int quantity,
  }) = _Product;

  factory Product.fromJson(Map<String, dynamic> json) => _$ProductFromJson(json);

  // Rich domain methods — derive from own fields
  bool get inStock => quantity > 0;
}

// Union type (exhaustive pattern matching)
@freezed
sealed class AuthState with _$AuthState {
  const factory AuthState.authenticated(User user) = Authenticated;
  const factory AuthState.unauthenticated() = Unauthenticated;
  const factory AuthState.loading() = AuthLoading;
}
```

## Notifier Pattern

```dart
@Riverpod(keepAlive: true)
class ProductNotifier extends _$ProductNotifier {
  @override
  ProductState build() {
    _load();
    return const ProductState();
  }

  Future<void> _load() async {
    state = state.copyWith(isLoading: true);
    try {
      final items = await ref.read(productRepositoryProvider).fetchAll();
      if (!ref.mounted) return;
      state = state.copyWith(items: items, isLoading: false);
    } catch (e) {
      if (!ref.mounted) return;
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }
}
```

## Code Generation

```bash
# Watch mode (recommended during development)
dart run build_runner watch -d

# One-time build
dart run build_runner build -d

# Clean build (resolve conflicts)
dart run build_runner clean && dart run build_runner build -d
```

## Anti-Patterns

| Wrong | Right | Why |
|-------|-------|-----|
| `StateProvider` | `@riverpod` codegen | Legacy, moved to `legacy.dart` |
| `abstract class` with Freezed | `sealed class` | Enables exhaustive matching |
| Parent watches, passes to child | Child watches directly | Prop drilling |
| Missing `ref.mounted` check | `if (!ref.mounted) return;` | Crash on disposed notifier |
| `ref.read` in `initState` | `addPostFrameCallback` then read | Provider not ready |
| `AutoDisposeNotifier` | `Notifier` (unified in 3.0) | Duplicate removed |
| `ExampleRef ref` in codegen | `Ref ref` in codegen | Ref subclasses removed |
| Try-catch at every layer | Catch once in notifier | Useless rethrows |
| `context.go('/path')` string routes | `const MyRoute().go(context)` typed | No compile-time safety |
| Anemic model + extraction in repo/datasource | Rich Model with methods on the model | Keep behavior with data |
| Per-class `@JsonSerializable(explicitToJson: true)` | `explicit_to_json: true` in `build.yaml` | One global config; no per-class annotations |
| Entity directly in datasources | Data `Model` with `toEntity()` in repository | Domain stays pure; repo maps model→entity |
| `@Freezed(toJson: true)` when `fromJson` exists | Plain `@freezed` | Freezed auto-generates `toJson` when `fromJson` uses `=>` |
| Using `context` after `await` | `if (!context.mounted) return;` | Context may be invalid after async gap |
| Raw `Map`/`List` as `.family` param | Use Freezed object or primitives | `==` fails on collections, breaks provider caching |
| Provider for ephemeral local state | `StatefulWidget` local state | Providers are for shared/cross-widget state |
| Omitting fields in remote data object | Include every schema field in push | Silent default overwrites remote value |
| Hardcoding one scope in sync restore | Iterate all scopes from centralized list | Partial restore; other screens replay |

Router, sync, and utility anti-patterns are in their reference files:
[common-patterns.md](references/common-patterns.md) (GoRouter redirect, delta sync) |
[extensions-utilities.md](references/extensions-utilities.md) (context extensions, SnackBarUtils)

## Reference Files

Consult the relevant reference when working on that topic. Each file has a Contents line at the top.

| Topic | File | Consult when |
|-------|------|--------------|
| Architecture layers, file structure | [architecture.md](references/architecture.md) | Creating feature modules, choosing layers |
| Atomic design: tokens → pages | [atomic-design.md](references/atomic-design.md) | Building shared widgets in `core/widgets/` |
| Riverpod 3.x codegen patterns | [riverpod-codegen.md](references/riverpod-codegen.md) | Writing providers, mutations, lifecycle |
| Freezed sealed classes, unions, Rich Models | [freezed-sealed.md](references/freezed-sealed.md) | Creating entities, models, unions, serialization |
| State management, async, notifiers | [state-management.md](references/state-management.md) | Writing notifiers, error handling, cross-provider |
| Testing with ProviderContainer.test | [testing.md](references/testing.md) | Writing unit or widget tests |
| Pagination, search, forms, delta sync | [common-patterns.md](references/common-patterns.md) | Lists, search, forms, GoRouter, sync |
| Performance, rebuilds, optimization | [performance.md](references/performance.md) | Debugging slow rebuilds, memory |
| Keys, slivers, animations, isolates, accessibility, adaptive | [flutter-optimizations.md](references/flutter-optimizations.md) | Scrolling, animation, concurrency, a11y |
| Context extensions, string/date utils, validators, DRY utilities | [extensions-utilities.md](references/extensions-utilities.md) | Adding utilities, extensions, validators |
| Hive CE persistence, @GenerateAdapters, TypeAdapters | [hive-persistence.md](references/hive-persistence.md) | Local storage, Hive adapters |
| Showcase guided tours, mixin, v5 API, sync | [showcase-tours.md](references/showcase-tours.md) | Adding tours, syncing tour state across devices |
