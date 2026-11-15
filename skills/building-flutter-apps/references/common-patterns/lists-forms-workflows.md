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
    @Default(false) bool isLoadingMore,
    @Default(true) bool hasMore,
    @Default(0) int page,
    @Default(0) int refreshFailedSerial,
  }) = _PaginatedState;
}

// noRetry: the failed view shows at once. See ../riverpod-codegen.md#automatic-retry.
@Riverpod(keepAlive: true, retry: noRetry)
class PaginatedProductNotifier extends _$PaginatedProductNotifier {
  static const _pageSize = 20;
  bool _refreshing = false;

  // The first read or watch loads page 0; AsyncValue carries first-load loading and error.
  @override
  Future<PaginatedState> build() async {
    final items = await ref.read(productRepositoryProvider).fetchPage(0, _pageSize);
    return PaginatedState(items: items, hasMore: items.length >= _pageSize);
  }

  // The scroll event that reaches the end calls this.
  Future<void> loadMore() async {
    final current = state.value;
    if (_refreshing || current == null || current.isLoadingMore || !current.hasMore) return;
    state = AsyncData(current.copyWith(isLoadingMore: true));
    try {
      final page = current.page + 1;
      final items = await ref.read(productRepositoryProvider).fetchPage(page, _pageSize);
      if (!ref.mounted) return;
      state = AsyncData(
        current.copyWith(
          items: [...current.items, ...items],
          page: page,
          hasMore: items.length >= _pageSize,
          isLoadingMore: false,
        ),
      );
    } catch (e) {
      if (!ref.mounted) return;
      state = AsyncData(current.copyWith(isLoadingMore: false));
    }
  }

  // The pull-to-refresh event or a button calls this; RefreshIndicator awaits it.
  Future<void> refresh() async {
    final previous = state.value;
    if (previous == null) {
      ref.invalidateSelf();
      return;
    }
    if (_refreshing || previous.isLoadingMore) return;
    _refreshing = true;
    try {
      final items = await ref.read(productRepositoryProvider).fetchPage(0, _pageSize);
      if (!ref.mounted) return;
      state = AsyncData(
        previous.copyWith(items: items, page: 0, hasMore: items.length >= _pageSize),
      );
    } catch (error, stackTrace) {
      Crash.error(error, stackTrace, reason: 'refresh');
      if (!ref.mounted) return;
      state = AsyncData(
        previous.copyWith(refreshFailedSerial: previous.refreshFailedSerial + 1),
      );
    } finally {
      _refreshing = false;
    }
  }
}
```

Widget with scroll detection:

```dart
class PaginatedProductListScreen extends ConsumerWidget {
  const PaginatedProductListScreen({super.key});

  bool _onScroll(WidgetRef ref, ScrollNotification scroll) {
    if (scroll.metrics.pixels >= scroll.metrics.maxScrollExtent - 200) {
      unawaited(ref.read(paginatedProductProvider.notifier).loadMore());
    }
    return false;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final items = ref.watch(
      paginatedProductProvider.select((s) => s.value?.items),
    );
    final failed = ref.watch(
      paginatedProductProvider.select((s) => s.hasError && !s.isLoading),
    );
    final hasMore = ref.watch(
      paginatedProductProvider.select((s) => s.value?.hasMore ?? false),
    );

    if (items == null && failed) {
      return ProductLoadFailedView(
        onRetry: () => unawaited(ref.read(paginatedProductProvider.notifier).refresh()),
      );
    }
    if (items == null) return const Center(child: CircularProgressIndicator());

    return NotificationListener<ScrollNotification>(
      onNotification: (scroll) => _onScroll(ref, scroll),
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

`Debouncer` = [collections-helpers.md](../extensions/collections-helpers.md#debouncer).

```dart
@freezed
sealed class SearchState with _$SearchState {
  const factory SearchState({
    @Default('') String query,
    @Default([]) List<Product> results,
    @Default(false) bool isSearching,
  }) = _SearchState;
}

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

The pull event calls the notifier's `refresh()` from the pagination example above, and `RefreshIndicator` awaits it. With a list on screen, `refresh()` fetches page 0 itself and does not re-run `build()`, because a re-run would reset `refreshFailedSerial` to 0, and the screen would read that fall as a new failure. The notifier sets `retry: noRetry` ([automatic retry](../riverpod-codegen.md#automatic-retry)), so a failed first load and a failed manual retry show their error at once. Without it, Riverpod 3 keeps a failing load in the loading state through about ten retries, roughly 38 seconds, and the failed view would stay hidden. A failed refresh does not escape the future that `RefreshIndicator` awaits. `refresh()` reports the failure, keeps the old list and raises `refreshFailedSerial`. The screen listens for that serial and shows a message, once for each failed refresh. A later refresh that succeeds keeps the serial, so it shows no message. With no list on screen there is nothing to refresh. `refresh()` then re-runs `build()` and returns without waiting, and the retry button of the failed view calls it. A pull while the next page loads does nothing, and the next page does not load while a refresh runs.

```dart
class RefreshableProductListScreen extends ConsumerWidget {
  const RefreshableProductListScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final items = ref.watch(
      paginatedProductProvider.select((s) => s.value?.items),
    );
    final failed = ref.watch(
      paginatedProductProvider.select((s) => s.hasError && !s.isLoading),
    );

    ref.listen(
      paginatedProductProvider.select((s) => s.value?.refreshFailedSerial ?? 0),
      (previous, next) {
        if (previous != next && context.mounted) {
          showProductsRefreshFailedSnackBar(context, context.l10n);
        }
      },
    );

    if (items == null && failed) {
      return ProductLoadFailedView(
        onRetry: () => unawaited(ref.read(paginatedProductProvider.notifier).refresh()),
      );
    }
    if (items == null) return const Center(child: CircularProgressIndicator());

    return RefreshIndicator(
      onRefresh: () => ref.read(paginatedProductProvider.notifier).refresh(),
      child: ListView.builder(
        itemCount: items.length,
        itemBuilder: (context, index) => ProductCard(product: items[index]),
      ),
    );
  }
}
```
