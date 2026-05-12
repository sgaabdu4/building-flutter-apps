# Mixin vs Interface vs Extension

## Trigger

Signals: mixin, ConnectivityMixin, ShowcaseScreenMixin, on ConsumerState, abstract interface class
Before generating code in this area, output verbatim: `Reading: mixins.md`


**Contents:** [Rules](#rules--never-violate) | [Decision Tree](#decision-tree) | [Quick Reference](#quick-reference) | [Common Flutter Mixins](#common-flutter-mixins) | [Custom Mixin Example](#custom-mixin-example) | [Restricted Mixin](#mixin-with-on-clause-restricted)

## Rules — NEVER Violate

0. **MUST extract shared behavior to a mixin the moment it appears in 2+ classes.** When the same code shows up in two notifiers, two widgets, or two services, stop copy-pasting and write a mixin. `mixin XxxMixin on Y` with the right `on` constraint. Suffix `Mixin`. Copy-paste sharing across notifiers / widgets / services is forbidden.

1. **MUST** use `mixin` for reusable behavior across unrelated classes. NEVER inherit to share behavior without "is-a".
2. **MUST** use `abstract interface class` for contracts (what class must do). MUST use `mixin` for capabilities (what class can do).
3. **MUST** keep mixins small, focused — one capability per mixin (SRP).
4. **MUST** suffix mixin names with `Mixin` (e.g., `LoggingMixin`, `ConnectivityMixin`).
5. **MUST** use `on` clause when mixin needs `super` access or must restrict users (e.g., `mixin ShowcaseScreenMixin on ConsumerState`).
6. **MUST NEVER** put mutable state fields in mixins — hidden side effects across unrelated classes. Pass state via ctor or method args.
7. **MUST NEVER** use `mixin class` unless type needs both direct instantiation AND mixing in. Prefer pure `mixin`.
8. **MUST** use `extension` for adding methods to types you don't own (e.g., `String`, `BuildContext`). NEVER mixin for this.

## Decision Tree

```mermaid
graph TD
  Q1{Need to share<br/>behavior across<br/>unrelated classes?}
  Q1 -->|Yes| Q2{Does it need<br/>'super' access or<br/>depend on a type?}
  Q2 -->|Yes| M1["mixin X on SuperType"]
  Q2 -->|No| M2["mixin X"]
  Q1 -->|No| Q3{Defining a contract<br/>for dependency injection<br/>or testability?}
  Q3 -->|Yes| I1["abstract interface class"]
  Q3 -->|No| Q4{Adding methods<br/>to a type you<br/>don't own?}
  Q4 -->|Yes| E1["extension on Type"]
  Q4 -->|No| Q5{Base implementation<br/>for an 'is-a'<br/>hierarchy?}
  Q5 -->|Yes| A1["abstract class"]
  Q5 -->|No| C1["Concrete class"]
```

## Quick Reference

| Tool | Keyword | Purpose | Multiple? | Constructors? |
|------|---------|---------|-----------|---------------|
| Mixin | `mixin` | Add capabilities ("can do") | Yes — `with A, B, C` | No |
| Interface | `abstract interface class` | Define contract ("must do") | Yes — `implements A, B` | Yes |
| Extension | `extension on Type` | Add methods to existing types | N/A | N/A |
| Abstract class | `abstract class` | Base impl ("is-a") | No — single `extends` | Yes |
| Mixin class | `mixin class` | Both class and mixin (rare) | One `with`, one `extends` | Limited |

## Common Flutter Mixins

| Mixin | `on` Constraint | Use Case |
|-------|----------------|----------|
| `SingleTickerProviderStateMixin` | `State` | One `AnimationController` — provides `vsync` |
| `TickerProviderStateMixin` | `State` | Multiple `AnimationController`s |
| `AutomaticKeepAliveClientMixin` | `State` | Keep tab/page alive in `PageView`/`TabBarView` |
| `WidgetsBindingObserver` | — | App lifecycle events (`didChangeAppLifecycleState`) |

## Custom Mixin Example

```dart
// core/mixins/connectivity_mixin.dart

/// Adds connectivity check capability to any notifier.
/// Keeps the mixin stateless — calls an injected service.
mixin ConnectivityMixin {
  bool checkConnectivity(ConnectivityService service) {
    return service.isConnected;
  }
}

// Usage in a notifier
class ProductNotifier extends _$ProductNotifier with ConnectivityMixin {
  @override
  ProductState build() {
    Future.microtask(_load); // Defer — see "Sync Notifier Initialization Trap"
    return const ProductState();
  }

  Future<void> _load() async {
    if (!ref.mounted) return;
    final connected = checkConnectivity(
      ref.read(connectivityServiceProvider),
    );
    if (!connected) {
      state = state.copyWith(error: 'No connection');
      return;
    }
    // ...fetch from remote
  }
}
```

## Mixin with `on` Clause (Restricted)

```dart
// core/mixins/showcase_screen_mixin.dart

/// Restricts this mixin to ConsumerState subclasses only.
mixin ShowcaseScreenMixin on ConsumerState {
  String get showcaseScope;
  List<GlobalKey> get showcaseKeys;

  void initShowcase() {
    // Can access 'ref' and 'widget' because of 'on ConsumerState'
  }

  void disposeShowcase() { /* cleanup */ }
}
```

## Retry-With-Backoff Helper (Data-Layer Mixin)

Bulk-I/O mixin (e.g. `AppwritePaginationMixin.saveAllRows`) → pair w/ **module-level** `retryWithBackoff<T>()` + typed exception. Free-standing, not mixin method — non-mixin sites reuse.

```dart
// core/services/appwrite_pagination_mixin.dart
import 'dart:io';
import 'dart:math' as math;

final _retryRng = math.Random(); // hoisted — no per-call alloc

class SaveRowResult<T> {
  const SaveRowResult.ok(this.item) : error = null, stackTrace = null;
  const SaveRowResult.err(this.item, this.error, this.stackTrace);
  final T item;
  final Object? error;
  final StackTrace? stackTrace;
  bool get isOk => error == null;
}

class SaveAllRowsException implements Exception {
  const SaveAllRowsException(this.failures);
  final List<SaveRowResult<Object?>> failures;
  @override
  String toString() =>
      'SaveAllRowsException: ${failures.length} item(s) failed; first=${failures.first.error}';
}

/// Retries [fn] on transient failures: Appwrite 429/503, [SocketException],
/// [HttpException]. Non-retryable errors rethrow immediately.
/// Base 200ms, doubled each retry, ±50ms jitter. Default 3 attempts.
bool _defaultShouldRetry(Object e) {
  if (e is SocketException || e is HttpException) return true;
  if (e is AppwriteException) return e.code == 429 || e.code == 503;
  return false;
}

Future<T> retryWithBackoff<T>(
  Future<T> Function() fn, {
  int maxAttempts = 3,
  Duration baseDelay = const Duration(milliseconds: 200),
  bool Function(Object)? shouldRetry,
}) async {
  final retryable = shouldRetry ?? _defaultShouldRetry;
  int attempt = 0;
  while (true) {
    try {
      return await fn();
    } on Object catch (e) {
      attempt++;
      if (attempt >= maxAttempts || !retryable(e)) rethrow;
      final backoff = baseDelay * (1 << (attempt - 1));
      final jitterMs = _retryRng.nextInt(101) - 50; // [-50, +50] ms
      await Future<void>.delayed(backoff + Duration(milliseconds: jitterMs));
    }
  }
}
```

Rules:
- **Module-level RNG**: hoist once. No `math.Random()` per call.
- **Retryable set explicit**: 429/503 + network IO only. Validation/4xx rethrow immediate.
- **Partial-failure**: bulk op collects `SaveRowResult` per item. `throwOnPartialFailure` → `SaveAllRowsException` w/ failure list. No silent drop.
- **Concurrency cap**: bulk default 4 (avoid 429 bucket swamp). Each item in `retryWithBackoff`.
- **Not in widgets**: retry = infra. Notifier → datasource → mixin.

## Recap

1. MUST use `mixin` for reusable behavior across unrelated classes — NEVER inherit to share behavior without an "is-a" relationship.
2. MUST NEVER put mutable state fields in mixins.
3. MUST suffix mixin names with `Mixin` and keep them single-responsibility.

