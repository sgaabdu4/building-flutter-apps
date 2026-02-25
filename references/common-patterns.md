# Common Patterns

Reusable patterns for pagination, search, forms, debouncing, and batch processing.

## Pagination

```dart
@freezed
sealed class PaginatedState with _$PaginatedState {
  const factory PaginatedState({
    @Default([]) List<Product> items,
    @Default(false) bool isLoading,
    @Default(false) bool isLoadingMore,
    @Default(true) bool hasMore,
    @Default(0) int page,
  }) = _PaginatedState;
}

@Riverpod(keepAlive: true)
class PaginatedProductNotifier extends _$PaginatedProductNotifier {
  static const _pageSize = 20;

  @override
  PaginatedState build() {
    _loadPage(0);
    return const PaginatedState();
  }

  Future<void> _loadPage(int page) async {
    state = state.copyWith(isLoading: page == 0, isLoadingMore: page > 0);
    try {
      final items = await ref.read(productRepositoryProvider).fetchPage(page, _pageSize);
      if (!ref.mounted) return;
      state = state.copyWith(
        items: page == 0 ? items : [...state.items, ...items],
        page: page,
        hasMore: items.length >= _pageSize,
        isLoading: false,
        isLoadingMore: false,
      );
    } catch (e) {
      if (!ref.mounted) return;
      state = state.copyWith(isLoading: false, isLoadingMore: false);
    }
  }

  Future<void> loadMore() async {
    if (state.isLoadingMore || !state.hasMore) return;
    await _loadPage(state.page + 1);
  }

  Future<void> refresh() async => _loadPage(0);
}
```

Widget with scroll detection:

```dart
class PaginatedProductList extends ConsumerWidget {
  const PaginatedProductList({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final items = ref.watch(
      paginatedProductNotifierProvider.select((s) => s.items),
    );
    final hasMore = ref.watch(
      paginatedProductNotifierProvider.select((s) => s.hasMore),
    );

    return NotificationListener<ScrollNotification>(
      onNotification: (scroll) {
        if (scroll.metrics.pixels >= scroll.metrics.maxScrollExtent - 200) {
          ref.read(paginatedProductNotifierProvider.notifier).loadMore();
        }
        return false;
      },
      child: ListView.builder(
        itemCount: items.length + (hasMore ? 1 : 0),
        itemBuilder: (context, index) {
          if (index >= items.length) {
            return const Center(child: CircularProgressIndicator());
          }
          return ProductCard(product: items[index]);
        },
      ),
    );
  }
}
```

## Search with Debounce

```dart
@freezed
sealed class SearchState with _$SearchState {
  const factory SearchState({
    @Default('') String query,
    @Default([]) List<Product> results,
    @Default(false) bool isSearching,
  }) = _SearchState;
}

// Uses Debouncer from core/utils/debouncer.dart
// See extensions-utilities.md for the Debouncer class
@Riverpod(keepAlive: true)
class SearchNotifier extends _$SearchNotifier {
  final _debouncer = Debouncer();

  @override
  SearchState build() {
    ref.onDispose(_debouncer.dispose);
    return const SearchState();
  }

  void search(String query) {
    state = state.copyWith(query: query, isSearching: query.isNotEmpty);

    if (query.isEmpty) {
      _debouncer.cancel();
      state = state.copyWith(results: [], isSearching: false);
      return;
    }

    _debouncer.call(() async {
      try {
        final results = await ref.read(productRepositoryProvider).search(query);
        if (!ref.mounted) return;
        state = state.copyWith(results: results, isSearching: false);
      } catch (e) {
        if (!ref.mounted) return;
        state = state.copyWith(isSearching: false);
      }
    });
  }
}
```

## Local Filter (No API Call)

Filter items already in state without refetching:

```dart
@freezed
sealed class FilterableState with _$FilterableState {
  const factory FilterableState({
    @Default([]) List<Product> allItems,
    @Default('') String searchQuery,
  }) = _FilterableState;

  const FilterableState._();

  List<Product> get displayItems => searchQuery.isEmpty
      ? allItems
      : allItems
          .where((item) =>
              item.name.toLowerCase().contains(searchQuery.toLowerCase()))
          .toList();
}

// Widget — use .select() on the computed getter
final items = ref.watch(
  filterableNotifierProvider.select((s) => s.displayItems),
);
```

## Form Validation

```dart
@freezed
sealed class ProductFormState with _$ProductFormState {
  const factory ProductFormState({
    @Default('') String name,
    @Default('') String description,
    @Default(0.0) double price,
    String? nameError,
    String? priceError,
    @Default(false) bool isSubmitting,
  }) = _ProductFormState;

  const ProductFormState._();

  bool get isValid =>
      nameError == null &&
      priceError == null &&
      name.isNotEmpty &&
      price > 0;
}

@Riverpod(keepAlive: true)
class ProductFormNotifier extends _$ProductFormNotifier {
  @override
  ProductFormState build() => const ProductFormState();

  void setName(String value) {
    String? error;
    if (value.isEmpty) error = 'Name required';
    if (value.length < 3) error = 'Name too short';
    state = state.copyWith(name: value, nameError: error);
  }

  void setPrice(String value) {
    final parsed = double.tryParse(value);
    String? error;
    if (parsed == null) error = 'Invalid number';
    if (parsed != null && parsed <= 0) error = 'Must be positive';
    state = state.copyWith(
      price: parsed ?? 0,
      priceError: error,
    );
  }

  Future<void> submit() async {
    if (!state.isValid || state.isSubmitting) return;

    state = state.copyWith(isSubmitting: true);
    try {
      await ref.read(productRepositoryProvider).create(
        Product(
          id: DateTime.now().millisecondsSinceEpoch.toString(),
          name: state.name,
          price: state.price,
        ),
      );
      if (!ref.mounted) return;
      // Reset or navigate
      state = const ProductFormState();
    } catch (e) {
      if (!ref.mounted) return;
      state = state.copyWith(isSubmitting: false);
    }
  }
}
```

## Batch Processing

Extract to `core/utils/batch_utils.dart` for reuse across features:

```dart
/// Process items in parallel batches to avoid overwhelming the server.
Future<void> parallelBatch<T>({
  required List<T> items,
  required Future<void> Function(T) action,
  int batchSize = 50,
}) async {
  for (var i = 0; i < items.length; i += batchSize) {
    final end = (i + batchSize).clamp(0, items.length);
    final batch = items.sublist(i, end);
    await Future.wait(batch.map(action));
    await Future<void>.value(); // yield to event loop
  }
}

// Usage in repository
Future<void> updateAll(List<Product> products) async {
  await parallelBatch(
    items: products,
    action: (p) => _remote.update(p),
    batchSize: 50,
  );
}
```

## Pull-to-Refresh

```dart
class ProductListScreen extends ConsumerWidget {
  const ProductListScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final items = ref.watch(
      productNotifierProvider.select((s) => s.items),
    );

    return RefreshIndicator(
      onRefresh: () async {
        await ref.read(productNotifierProvider.notifier).refresh();
      },
      child: ListView.builder(
        itemCount: items.length,
        itemBuilder: (context, index) => ProductCard(product: items[index]),
      ),
    );
  }
}
```

## Navigation with Typed GoRouter

Use `go_router_builder` for type-safe routes. Every route is a class extending `GoRouteData` with a generated mixin. The compiler catches route parameter errors at build time.

### Route Definitions

```dart
// core/navigation/routes.dart
part 'routes.g.dart';

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

Create GoRouter once. Use `ref.listen()` + `refreshListenable` to trigger redirect re-evaluation. Never `ref.watch()` in the redirect — it recreates the router on every state change, resetting the route stack.

**Redirect rules for apps with multi-step setup (profile completion, roles):**

- **During loading, stay put.** Return `null` — never bounce to splash. On web refresh, redirecting `/chat` → `/` → `/home` loses the URL. One exception: authenticated users on login/signup should redirect to splash.
- **Auth pages navigate explicitly.** Add `ref.listen(authProvider)` in login/signup pages that navigates on auth success. `refreshListenable` timing is unreliable; explicit navigation guarantees the transition.
- **OAuth skips auth-level `isLoading`.** Use per-button loading (`isGoogleLoading`). Auth `isLoading` triggers premature splash redirect.
- **keepAlive providers survive hot reload.** Redirect closure changes require hot restart.

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

      switch (setupStatus) {
        case SetupStatus.loading:
          // Move authenticated users off login to splash.
          if (ref.read(authProvider).isAuthenticated && _isPublicPage(location)) {
            return const SplashRoute().location;
          }
          return null; // Stay put — preserves URL on web refresh.

        case SetupStatus.unauthenticated:
          return _isPublicPage(location) ? null : const LoginRoute().location;

        case SetupStatus.needsProfileCompletion:
          return location == '/profile-completion' ? null : '/profile-completion';

        case SetupStatus.setupComplete:
          return _isSetupPage(location) ? const HomeRoute().location : null;
      }
    },
  );
}

// Belt-and-suspenders: auth pages navigate directly on authentication.
class AppLoginPage extends ConsumerWidget {
  const AppLoginPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.listen(authProvider, (prev, next) {
      if (next.isAuthenticated && !(prev?.isAuthenticated ?? false)) {
        const SplashRoute().go(context);
      }
    });
    return const LoginPageContent();
  }
}
```

### Type-Safe Navigation

```dart
// Navigate with compile-time checked parameters
const HomeRoute().go(context);
const ProductListRoute().go(context);
ProductDetailRoute(id: product.id).go(context);
const ProductCreateRoute().go(context);

// Push (adds to stack)
ProductDetailRoute(id: product.id).push(context);

// Push with return value
final result = await ProductDetailRoute(id: product.id).push<bool>(context);

// WRONG — string-based navigation (no type safety)
// context.go('/products/${product.id}');
```

### main.dart

```dart
class MyApp extends ConsumerWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    return MaterialApp.router(routerConfig: router);
  }
}
```

