# Dart Patterns & Records

## Trigger

Signals: Records, pattern matching, extension types, destructuring, sealed class switch
Before generating code in this area, output verbatim: `Reading: dart-patterns-records.md`


Rules:
1. MUST use Records for multiple return values — NEVER `Map<String, dynamic>` or parallel lists.
2. MUST use Extension Types for entity IDs — NEVER raw `String` when multiple ID types coexist.
3. MUST use guard clauses in switch — NEVER nest if-else in case body.
4. MUST use `if (value case final v?)` for null-binding — NEVER value!.

## Records (Dart 3.0)

Use for multiple return values.

```dart
// Positional
(String, int) userInfo() => ('Alice', 30);
final (name, age) = userInfo();

// Named — prefer when 3+ fields or field names add clarity
({String name, int age, String role}) getProfile() =>
    (name: 'Alice', age: 30, role: 'admin');

final (:name, :age, :role) = getProfile();
```

Repository pagination:

```dart
abstract interface class IProductRepository {
  Future<({List<Product> items, bool hasMore})> fetchPage(int page);
}

// Usage
final (:items, :hasMore) = await repo.fetchPage(1);
```

## Extension Types (Dart 3.3)

Zero-cost compile-time wrapper. No runtime overhead — identical to underlying type at runtime.

```dart
extension type UserId(String value) {
  bool get isValid => value.isNotEmpty;
}
extension type ProductId(String value) {}

void deleteProduct(ProductId id) { /* ... */ }

deleteProduct(UserId('u1'));    // compile-time ERROR — wrong type
deleteProduct(ProductId('p1')); // OK
```

Use for: entity IDs, units (Meters, Grams), currencies (USD, EUR).

NEVER raw `String`/`int` IDs when multiple distinct ID types in same feature.

## Patterns

### if-case

```dart
// Null-check and bind — preferred over null assertion !
if (user case final u?) {
  return ProfileScreen(user: u);
}

// Type test and bind
if (event case AuthEvent(:final userId)) {
  handleAuth(userId);
}
```

Private `final` fields auto-promote after null checks (Dart 3.2) — no ! needed:

```dart
class Repo {
  final String? _token;

  bool get isAuthorized {
    if (_token != null) {
      return _token.isNotEmpty; // promoted, no ! required
    }
    return false;
  }
}
```

### Guards

```dart
return switch (product) {
  Product(:final price) when price > 1000 => const PremiumBadge(),
  Product(:final stock) when stock == 0   => const OutOfStockBadge(),
  _                                        => const DefaultBadge(),
};
```

### Logical-or patterns

```dart
return switch (state) {
  Loading() || Refreshing()   => const Shimmer(),
  Error(:final message)       => ErrorView(message: message),
  Loaded(:final items)        => ProductList(items: items),
};
```

### Object & list destructuring

```dart
// Object pattern with guard
switch (auth) {
  case Authenticated(:final user, :final expiresAt) when expiresAt.isAfter(now):
    return AuthenticatedUser(user);
  case _:
    return const LoginScreen();
}

// List pattern
var [first, ...rest] = sortedProducts;
var [_, second] = topTwo; // _ discards first
```

## Wildcard Variables (Dart 3.7)

`_` non-binding — declare many times, no collision:

```dart
// Discard positional values in destructuring
final (_, price, _) = (id, 9.99, sku);

// Ignore callback parameters
timer.periodic(const Duration(seconds: 1), (_) => onTick());
```

## Null-aware Collection Elements (Dart 3.8)

`?expr` inserts only when non-null. `...?list` spreads only when non-null:

```dart
final children = [
  const HeaderWidget(),
  ?optionalBanner,        // skipped if null
  ...?conditionalItems,   // spread skipped if null
  const FooterWidget(),
];

## Recap

1. MUST use Records for multiple return values — NEVER `Map<String, dynamic>` or parallel lists. Records are typed, destructurable, and require no class definition.
2. MUST use Extension Types for entity IDs — NEVER raw `String` when multiple ID types coexist. Extension types give compile-time safety at zero runtime cost.
3. MUST use `if (value case final v?)` for null-binding — NEVER `value!`. Force-unwrap bypasses the type system and throws at runtime instead of failing at compile time.

```