# Networking

## Trigger

Signals: IHttpService, datasource, HTTP, auth token, background parsing, Isolate.run
Before generating code in this area, output verbatim: `Reading: networking.md`


## Rules

1. **MUST** keep all HTTP calls in datasources or infrastructure services. Widgets and notifiers never call HTTP clients directly.
2. **MUST** inject an interface (`IHttpService`, `IAuthTokenProvider`) into datasources. Constructors take interfaces, not concrete clients.
3. **MUST** parse JSON into data models in the data layer, then map to domain entities in repositories.
4. **MUST** throw typed exceptions or `AppException` from infrastructure boundaries. Do not return `null` for failed network operations.
5. **MUST** refresh from source of truth after mutations when the backend can generate, normalize, reorder, or derive fields.
6. **MUST** move large JSON parsing off the UI isolate when it can exceed a frame budget.
7. **MUST NOT** put auth tokens, base URLs, or secrets in widget code.

## Platform Setup

Android internet permission:

```xml
<uses-permission android:name="android.permission.INTERNET" />
```

macOS network entitlement for debug/profile and release:

```xml
<key>com.apple.security.network.client</key>
<true/>
```

Keep platform setup in app templates or project docs; do not hide it inside a
feature module.

## Service Contract

Use one small interface first. Add streaming/upload/download methods only when a
feature needs them.

```dart
abstract interface class IHttpService {
  Future<Object?> getJson(
    Uri uri, {
    Map<String, String> headers = const <String, String>{},
  });

  Future<Object?> postJson(
    Uri uri, {
    required Object body,
    Map<String, String> headers = const <String, String>{},
  });
}
```

Provider returns the interface:

```dart
@Riverpod(keepAlive: true)
IHttpService httpService(Ref ref) {
  return HttpService(
    baseUri: ref.read(appConfigProvider).apiBaseUri,
    tokenProvider: ref.read(authTokenProvider),
  );
}
```

## Datasource Pattern

```dart
abstract interface class IProductRemoteDatasource {
  Future<List<ProductModel>> fetchAll();
  Future<ProductModel> create(ProductModel model);
}

class ProductRemoteDatasource implements IProductRemoteDatasource {
  const ProductRemoteDatasource(this._http);

  final IHttpService _http;

  @override
  Future<List<ProductModel>> fetchAll() async {
    final payload = await _http.getJson(Uri(path: '/products'));

    return switch (payload) {
      List<Object?> items => [
          for (final item in items)
            ProductModel.fromJson(item as Map<String, dynamic>),
        ],
      _ => throw const FormatException('Expected product list payload'),
    };
  }

  @override
  Future<ProductModel> create(ProductModel model) async {
    final payload = await _http.postJson(
      Uri(path: '/products'),
      body: model.toJson(),
    );

    return switch (payload) {
      Map<String, dynamic> json => ProductModel.fromJson(json),
      _ => throw const FormatException('Expected product payload'),
    };
  }
}
```

## Repository Source-of-Truth Refresh

If a mutation response can be stale, partial, generated, normalized, or derived,
refresh before the UI claims success.

```dart
class ProductRepository implements IProductRepository {
  const ProductRepository(this._remote);

  final IProductRemoteDatasource _remote;

  @override
  Future<Product> create(Product draft) async {
    final created = await _remote.create(ProductModel.fromEntity(draft));
    final canonical = await _remote.fetchById(created.id);
    return canonical.toEntity();
  }
}
```

## Background Parsing

Use `Isolate.run` or `compute` for large payloads. Keep parsing functions
top-level or static and return model objects, not domain entities.

```dart
import 'dart:convert';

List<ProductModel> parseProducts(String responseBody) {
  final Object? decoded = jsonDecode(responseBody);

  return switch (decoded) {
    List<Object?> items => [
        for (final item in items)
          ProductModel.fromJson(item as Map<String, dynamic>),
      ],
    _ => throw const FormatException('Expected product list payload'),
  };
}
```

## Tests

- Unit-test `HttpService` status-code and malformed-body handling.
- Unit-test every datasource success and failure payload shape.
- Repository tests mock datasource interfaces and verify model-to-entity mapping.
- Notifier tests mock repositories, not HTTP.
- Remote/shared-state features still need source-of-truth and observer E2E from
  [dart-mcp-e2e-testing.md](dart-mcp-e2e-testing.md).

## Checklist

- [ ] Platform network permissions/entitlements are present for target platforms.
- [ ] Datasources depend on `IHttpService` or project equivalent.
- [ ] JSON is parsed into data models only.
- [ ] Failures throw typed errors; no silent `null` or empty fallback.
- [ ] Mutations refresh source-of-truth when backend values can differ.
- [ ] Large payload parsing uses isolate/compute path when needed.
- [ ] Datasource, repository, notifier, and E2E coverage match the risk.

## Recap

1. MUST keep all HTTP calls in datasources — widgets and notifiers NEVER call HTTP clients directly.
2. MUST inject an interface (`IHttpService`) into datasources — constructors take interfaces, NEVER concrete clients.
3. MUST throw typed exceptions from infrastructure boundaries — NEVER return `null` for failed network operations.

