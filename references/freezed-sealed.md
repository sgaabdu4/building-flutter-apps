# Freezed 3.x Sealed Classes

All Freezed classes use `sealed` for exhaustive pattern matching with Dart's `switch` expressions.

## Setup

```yaml
# pubspec.yaml
dependencies:
  freezed_annotation: ^3.0.0
  json_annotation: ^6.8.0

dev_dependencies:
  build_runner: ^2.4.0
  freezed: ^3.2.5
  json_serializable: ^6.0.0
```

Every file needs:

```dart
import 'package:freezed_annotation/freezed_annotation.dart';

part 'my_file.freezed.dart';
part 'my_file.g.dart';  // only if using fromJson/toJson
```

## Simple Data Classes

Single constructor with `sealed class`:

```dart
@freezed
sealed class Product with _$Product {
  const factory Product({
    required String id,
    required String name,
    required double price,
    @Default(0) int quantity,
    @Default(true) bool isActive,
  }) = _Product;

  factory Product.fromJson(Map<String, dynamic> json) =>
      _$ProductFromJson(json);
}
```

Generated: `copyWith`, `toString`, `==`, `hashCode`, `toJson`.

## Adding Methods and Getters

Add a private constructor first:

```dart
@freezed
sealed class Product with _$Product {
  const Product._();

  const factory Product({
    required String id,
    required String name,
    required double price,
    @Default(0) int quantity,
  }) = _Product;

  factory Product.fromJson(Map<String, dynamic> json) =>
      _$ProductFromJson(json);

  double get totalValue => price * quantity;
  bool get inStock => quantity > 0;
}
```

## Union Types

Multiple constructors create tagged unions with exhaustive matching:

```dart
@freezed
sealed class AuthState with _$AuthState {
  const factory AuthState.authenticated(User user) = Authenticated;
  const factory AuthState.unauthenticated() = Unauthenticated;
  const factory AuthState.loading() = AuthLoading;
}

// Exhaustive switch — compiler enforces all cases
Widget build(BuildContext context, WidgetRef ref) {
  final auth = ref.watch(authProvider);
  return switch (auth) {
    Authenticated(:final user) => HomeScreen(user: user),
    Unauthenticated() => const LoginScreen(),
    AuthLoading() => const LoadingScreen(),
  };
}
```

Use Dart's native `switch` expressions. Do not use Freezed's legacy `when`/`map` methods (removed in Freezed 3.0).

## AsyncValue Pattern Matching

Riverpod's `AsyncValue` is also sealed:

```dart
final asyncData = ref.watch(myAsyncProvider);
return switch (asyncData) {
  AsyncData(:final value) => Text(value.toString()),
  AsyncError(:final error) => Text('Error: $error'),
  AsyncLoading() => const CircularProgressIndicator(),
};
```

New in Riverpod 3.0: `AsyncLoading(progress: 0.5)` for loading progress, `AsyncValue.isFromCache` for offline persistence data.

## Feature State

Combine a state class with a union for multi-state features:

```dart
@freezed
sealed class ProductState with _$ProductState {
  const factory ProductState({
    @Default([]) List<Product> items,
    @Default(false) bool isLoading,
    @Default(false) bool isLoadingMore,
    @Default(false) bool hasMore,
    @Default(0) int page,
    String? error,
    String? searchQuery,
  }) = _ProductState;
}
```

Use `copyWith` to update individual fields:

```dart
state = state.copyWith(isLoading: true);
state = state.copyWith(items: newItems, isLoading: false);
state = state.copyWith(error: null); // clear error
```

## Deep Copy

When Freezed classes nest other Freezed classes, use deep copy:

```dart
@freezed
sealed class Company with _$Company {
  const factory Company({
    String? name,
    required Director director,
  }) = _Company;
}

@freezed
sealed class Director with _$Director {
  const factory Director({
    String? name,
    Assistant? assistant,
  }) = _Director;
}

// Deep copy syntax
Company newCompany = company.copyWith.director.assistant(name: 'John Smith');

// Null-safe deep copy
Company? newCompany = company.copyWith.director.assistant?.call(name: 'John');
```

## JSON Serialization

### Single Constructor

```dart
@freezed
sealed class UserModel with _$UserModel {
  const factory UserModel({
    required String id,
    @JsonKey(name: 'full_name') required String fullName,
    @JsonKey(name: 'created_at') required DateTime createdAt,
  }) = _UserModel;

  factory UserModel.fromJson(Map<String, dynamic> json) =>
      _$UserModelFromJson(json);
}
```

### Union Type Serialization

Uses `runtimeType` discriminator by default:

```dart
@freezed
sealed class ApiResponse with _$ApiResponse {
  const factory ApiResponse.success(dynamic data) = ApiSuccess;
  const factory ApiResponse.error(String message) = ApiError;

  factory ApiResponse.fromJson(Map<String, dynamic> json) =>
      _$ApiResponseFromJson(json);
}
```

Customize the discriminator key:

```dart
@Freezed(unionKey: 'type', unionValueCase: FreezedUnionCase.pascal)
sealed class ApiResponse with _$ApiResponse {
  const factory ApiResponse.success(dynamic data) = ApiSuccess;

  @FreezedUnionValue('ServerError')
  const factory ApiResponse.error(String message) = ApiError;

  factory ApiResponse.fromJson(Map<String, dynamic> json) =>
      _$ApiResponseFromJson(json);
}
```

### Generic Serialization

```dart
@Freezed(genericArgumentFactories: true)
sealed class Paginated<T> with _$Paginated<T> {
  const factory Paginated({
    required List<T> items,
    required int total,
    required int page,
  }) = _Paginated;

  factory Paginated.fromJson(
    Map<String, dynamic> json,
    T Function(Object?) fromJsonT,
  ) => _$PaginatedFromJson(json, fromJsonT);
}
```

## Non-Constant Default Values

Use a private constructor:

```dart
@freezed
sealed class Event with _$Event {
  Event._({DateTime? createdAt}) : createdAt = createdAt ?? DateTime.now();

  factory Event({required String title, DateTime? createdAt}) = _Event;

  @override
  final DateTime createdAt;
}
```

## Inheritance

```dart
class BaseEntity {
  const BaseEntity(this.id);
  final String id;
}

@freezed
sealed class Product extends BaseEntity with _$Product {
  const Product._(super.id) : super();
  const factory Product(String id, String name) = _Product;
}
```

## Mutable Classes

Use `@unfreezed` for mutable state (rare — prefer immutable):

```dart
@unfreezed
sealed class FormData with _$FormData {
  factory FormData({
    required String name,
    required String email,
    required final int id, // final = still immutable
  }) = _FormData;
}
```

## Configuration

Per-class:

```dart
@Freezed(copyWith: false, equal: false, toStringOverride: false)
sealed class Minimal with _$Minimal {
  const factory Minimal(int value) = _Minimal;
}
```

Project-wide via `build.yaml`:

```yaml
targets:
  $default:
    builders:
      freezed:
        options:
          format: false          # faster builds
          copy_with: true
          equal: true
          union_key: type
          union_value_case: pascal
```

## Linting

```yaml
# pubspec.yaml
dev_dependencies:
  custom_lint: ^0.7.0
  freezed_lint: ^1.0.0

# analysis_options.yaml
analyzer:
  plugins:
    - custom_lint
  errors:
    invalid_annotation_target: ignore
```

## Rich Models

**Rule: If a method reads only its own fields, it belongs on the model.**

Add `const Entity._()` to enable getters and methods on Freezed classes:

```dart
@freezed
sealed class Order with _$Order {
  const Order._();

  const factory Order({
    required String id,
    required List<OrderItem> items,
    required DateTime createdAt,
  }) = _Order;

  double get total => items.fold(0, (sum, i) => sum + i.price * i.quantity);
  List<String> get productIds => items.map((i) => i.productId).toList();
  OrderSummary toSummary() => OrderSummary(id: id, itemCount: items.length, total: total);
}
```

| Belongs on model | Goes elsewhere |
|-----------------|---------------|
| Computed getters (`total`, `isExpired`) | Needs external deps (API, DB) → Repository |
| Boolean checks (`inStock`, `isOverdue`) | Reads multiple unrelated models → Repository |
| Collection flattening (`allResults`) | Needs Ref/providers → Notifier |
| Transform to another type (`toClaims()`) | Side effects (HTTP, I/O) → Datasource |
| Format for API (`toFormFields()`) | |

Data models follow the same rule: `toEntity()`, `toRequestBody()`, `toCsvRow()` all belong on the model.

## Deep Serialization (explicitToJson)

Freezed `toJson()` does **not** deep-serialize nested Freezed objects. This causes `type '_XYZ' is not a subtype of type 'Map<String, dynamic>'` in release builds.

**Rule: Add `@JsonSerializable(explicitToJson: true)` on the factory constructor (not the class) when the model has nested Freezed fields.**

```dart
@freezed
sealed class Order with _$Order {
  @JsonSerializable(explicitToJson: true)  // ← on factory, not class
  const factory Order({
    required String id,
    required List<OrderItem> items,  // nested Freezed
    required Customer customer,       // nested Freezed
  }) = _Order;

  factory Order.fromJson(Map<String, dynamic> json) => _$OrderFromJson(json);
}
```

Add when model has `List<FreezedClass>`, `FreezedClass`, or `FreezedClass?` fields. Skip for primitives, `DateTime`, and enums.
