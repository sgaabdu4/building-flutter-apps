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

# New Dart 3.10+ Plugin System (auto-downloads)
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
      # prefer_class_destructuring is active — enforces case final patterns

analyzer:
  exclude:
    - "**/*.g.dart"
    - "**/*.freezed.dart"
    - "**/*.gr.dart"
    - "**/*.arb"

  # Legacy plugin system (required for custom_lint/riverpod_lint)
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

custom_lint:
  rules:
    riverpod_avoid_dynamic_provider: error
```

## Required dev_dependencies

```yaml
dev_dependencies:
  flutter_lints: ^5.0.0
  custom_lint: ^0.7.0
  riverpod_lint: ^3.0.0    # Riverpod-specific rules
  freezed_lint: ^1.0.0     # Freezed-specific rules
  # many_lints is auto-downloaded via the Dart 3.10+ plugin system
```

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
| `riverpod_avoid_dynamic_provider: error` | Enforces typed provider usage |
