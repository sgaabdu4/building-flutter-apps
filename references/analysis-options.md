# analysis_options.yaml

Standard project linter configuration. Use as-is — no exceptions.

## Rules — NEVER Violate

1. **MUST** keep `strict-casts`, `strict-inference`, `strict-raw-types` enabled — NEVER disable.
2. **MUST** keep `avoid_dynamic_calls` enabled — NEVER allow `dynamic` method calls.
3. **MUST** exclude all generated files (`*.g.dart`, `*.freezed.dart`).
4. **MUST** keep `invalid_annotation_target: ignore` — required for Freezed + Riverpod codegen.
5. **NEVER** disable `unawaited_futures` — missing `await` is a logic bug.
6. **NEVER** disable `cancel_subscriptions` or `close_sinks` — resource leaks.

## analysis_options.yaml

Copy verbatim into every project root:

```yaml
# Start with the official Flutter baseline
include: package:flutter_lints/flutter.yaml

# Dart 3.10+ new plugin system (auto-discovered by `dart analyze` / `flutter analyze`)
# Requires Dart >= 3.10 / Flutter >= 3.38
plugins:
  many_lints:
    diagnostics:
      # Disable Codegen & Freezed conflicts
      prefer_overriding_parent_equality: false

      # Disable all BLoC rules (project uses Riverpod)
      use_bloc_suffix: false
      prefer_immutable_bloc_state: false
      prefer_multi_bloc_provider: false
      prefer_bloc_extensions: false
      avoid_bloc_public_methods: false
      avoid_passing_bloc_to_bloc: false
      avoid_passing_build_context_to_blocs: false

      # Disable syntactic dot-shorthand enforcement
      use_gap: false
      prefer_shorthands_with_enums: false
      prefer_shorthands_with_constructors: false
      prefer_returning_shorthands: false
      prefer_switch_expression: false
      prefer_shorthands_with_static_fields: false

      # Explicitly enable: enforces `case final` destructuring over manual null checks
      # (lints from new plugin system are disabled by default — must opt in)
      prefer_class_destructuring: true

  # riverpod_lint 3.1+ uses analysis_server_plugin — NOT custom_lint
  # All rules are warnings (auto-enabled); disable selectively here if needed
  riverpod_lint:

analyzer:
  exclude:
    - "**/*.g.dart"
    - "**/*.freezed.dart"
    - "**/*.gr.dart"
    - "**/*.arb"

  # Legacy plugin system — still required for freezed_lint (uses custom_lint)
  plugins:
    - custom_lint

  language:
    strict-casts: true
    strict-inference: true
    strict-raw-types: true

  errors:
    missing_required_param: error
    missing_return: error
    invalid_annotation_target: ignore

formatter:
  page_width: 100

linter:
  rules:
    # Formatting & architecture
    - always_use_package_imports
    - require_trailing_commas
    - prefer_single_quotes
    - directives_ordering
    - avoid_multiple_declarations_per_line

    # Strict const rules
    - prefer_const_constructors
    - prefer_const_declarations
    - prefer_const_literals_to_create_immutables

    # Immutability & clean code
    - prefer_final_locals
    - avoid_redundant_argument_values

    # Safety & async best practices
    - avoid_dynamic_calls
    - cancel_subscriptions
    - close_sinks
    - unawaited_futures
```

## Required dev_dependencies

Run these commands to add at the latest versions — never hardcode version numbers in the skill:

```bash
flutter pub add dev:flutter_lints
flutter pub add dev:custom_lint      # required for freezed_lint (still uses custom_lint)
flutter pub add dev:freezed_lint     # Freezed-specific rules (via custom_lint)
flutter pub add dev:riverpod_lint    # Riverpod rules (uses analysis_server_plugin since 3.1.0)
# many_lints is auto-downloaded via the Dart 3.10+ plugin system — no pub add needed
```

> **Note — riverpod_lint 3.1+ (Dart >= 3.10 required)**
> `riverpod_lint` 3.1+ uses the new `analysis_server_plugin` system — no longer `custom_lint`.
> Configure it under `plugins: riverpod_lint:` in analysis_options.yaml, not under `custom_lint: rules:`.
> All riverpod rules are warnings (auto-enabled). Use `diagnostics:` to disable specific rules if needed.

## Key Rules Explained

| Rule | Why |
|------|-----|
| `always_use_package_imports` | No relative imports — consistent, no broken imports on refactor |
| `prefer_const_constructors` | Eliminates unnecessary widget rebuilds |
| `require_trailing_commas` | Enables `dart format` tall style (Dart 3.7+) |
| `avoid_dynamic_calls` | Catches untyped method calls at lint time |
| `unawaited_futures` | Missing `await` is a logic bug — caught at lint time |
| `prefer_final_locals` | Immutability enforcement at local scope |
| `strict-raw-types` | No unparameterized `List`, `Map`, etc. |
| `prefer_class_destructuring` | Enforces `case final` pattern destructuring (Dart 3.0+) |
| `riverpod_lint` warnings | All Riverpod rules auto-enabled (warnings by default in 3.1+) |
