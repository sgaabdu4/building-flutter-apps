# Common Patterns — Lists, Forms, and Workflows


## Read first

1. Use Freezed state plus `@Riverpod` codegen for pagination, search, and forms.
2. Debounce high-frequency input in the notifier/helper owner and dispose it with `ref.onDispose`.
3. After async repository work, guard with `if (!ref.mounted) return;` before state writes.

## Trigger

Signals: pagination, infinite scroll, cursor loading, search debounce, form validation, batch processing, pull-to-refresh.

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
    unawaited(.microtask(() => _loadPage(0))); // Defer — see notifier-structure.md.
    return const PaginatedState(isLoading: true);
  }

  Future<void> _loadPage(int page) async {
    if (!ref.mounted) return;
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
class PaginatedProductListScreen extends ConsumerWidget {
  const PaginatedProductListScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final items = ref.watch(
      paginatedProductProvider.select((s) => s.items),
    );
    final hasMore = ref.watch(
      paginatedProductProvider.select((s) => s.hasMore),
    );

    return NotificationListener<ScrollNotification>(
      onNotification: (scroll) {
        if (scroll.metrics.pixels >= scroll.metrics.maxScrollExtent - 200) {
          unawaited(ref.read(paginatedProductProvider.notifier).loadMore());
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

// Uses Debouncer from core/extensions/ helper owner.
// See references/extensions/collections-helpers.md for the Debouncer class.
@Riverpod(keepAlive: true)
class SearchNotifier extends _$SearchNotifier {
  final _debouncer = Debouncer(const Duration(milliseconds: 150));

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

    _debouncer.call(() => unawaited(_runSearch(query)));
  }

  Future<void> _runSearch(String query) async {
    try {
      final results = await ref.read(productRepositoryProvider).search(query);
      if (!ref.mounted) return;
      state = state.copyWith(results: results, isSearching: false);
    } catch (e) {
      if (!ref.mounted) return;
      state = state.copyWith(isSearching: false);
    }
  }
}
```

## Local Filter (No API Call)

Filter items in state, no refetch:

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
  filterableProvider.select((s) => s.displayItems),
);
```

## Form Validation

Notifiers store typed validation errors; the UI maps them to localized copy
([localization.md](../localization.md#notifier-boundary)).

```dart
enum ProductNameError { required, tooShort }

enum ProductPriceError { invalidNumber, notPositive }

@freezed
sealed class ProductFormState with _$ProductFormState {
  const factory ProductFormState({
    @Default('') String draftName,
    @Default('') String draftDescription,
    @Default(0.0) double draftPrice,
    ProductNameError? nameError,
    ProductPriceError? priceError,
    @Default(false) bool isSubmitting,
  }) = _ProductFormState;

  const ProductFormState._();

  bool get isValid =>
      nameError == null &&
      priceError == null &&
      draftName.trim().isNotEmpty &&
      draftPrice > 0;
}

@Riverpod(keepAlive: true)
class ProductFormNotifier extends _$ProductFormNotifier {
  static const _minNameLength = 3;

  @override
  ProductFormState build() => const ProductFormState();

  void setName(String value) {
    ProductNameError? nameError;
    if (value.length < _minNameLength) nameError = .tooShort;
    if (value.isEmpty) nameError = .required;
    state = state.copyWith(draftName: value, nameError: nameError);
  }

  void setPrice(String value) {
    final parsed = double.tryParse(value);
    ProductPriceError? priceError;
    if (parsed == null) priceError = .invalidNumber;
    if (parsed != null && parsed <= 0) priceError = .notPositive;
    state = state.copyWith(
      draftPrice: parsed ?? 0,
      priceError: priceError,
    );
  }

  Future<void> submit() async {
    if (!state.isValid || state.isSubmitting) return;

    state = state.copyWith(isSubmitting: true);
    try {
      await ref.read(productRepositoryProvider).create(
        Product(
          id: DateTimeX.nowUtc().millisecondsSinceEpoch.toString(),
          name: state.draftName.trim(),
          price: state.draftPrice,
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

```dart
// Screen build: map the typed error to localized copy for the field's errorText.
final l10n = context.l10n;
final nameError = ref.watch(productFormProvider.select((s) => s.nameError));
final nameErrorText = switch (nameError) {
  .required => l10n.productNameRequired,
  .tooShort => l10n.productNameTooShort,
  null => null,
};
```

## Batch Processing

Extract to `core/utils/batch_utils.dart` for cross-feature reuse:

```dart
import 'dart:math';

/// Process items in parallel batches to avoid overwhelming the server.
Future<void> parallelBatch<T>({
  required List<T> items,
  required Future<void> Function(T) action,
  int batchSize = 50,
}) async {
  for (int i = 0; i < items.length; i += batchSize) {
    final end = min(i + batchSize, items.length);
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
      productProvider.select((s) => s.items),
    );

    return RefreshIndicator(
      onRefresh: () async {
        await ref.read(productProvider.notifier).refresh();
      },
      child: ListView.builder(
        itemCount: items.length,
        itemBuilder: (context, index) => ProductCard(product: items[index]),
      ),
    );
  }
}
```
