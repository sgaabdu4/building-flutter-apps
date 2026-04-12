# analysis_options.yaml

Copy verbatim into every project root. No exceptions.

## Rules

| Rule | Constraint |
|------|-----------|
| `strict-casts/inference/raw-types` | NEVER disable |
| `avoid_dynamic_calls` | NEVER disable |
| `unawaited_futures` | NEVER disable — missing await is a logic bug |
| `cancel_subscriptions` / `close_sinks` | NEVER disable — resource leaks |
| `invalid_annotation_target: ignore` | NEVER remove — required by Freezed + Riverpod codegen |
| Generated files excluded | NEVER analyse `*.g.dart`, `*.freezed.dart` |

## analysis_options.yaml

```yaml
include: package:flutter_lints/flutter.yaml

# Dart 3.10+ plugin system (requires Dart >= 3.10 / Flutter >= 3.38)
plugins:
  many_lints:
    diagnostics:
      prefer_overriding_parent_equality: false  # conflicts with Freezed
      use_bloc_suffix: false                    # BLoC rules — project uses Riverpod
      prefer_immutable_bloc_state: false
      prefer_multi_bloc_provider: false
      prefer_bloc_extensions: false
      avoid_bloc_public_methods: false
      avoid_passing_bloc_to_bloc: false
      avoid_passing_build_context_to_blocs: false
      use_gap: false                            # dot-shorthand enforcement
      prefer_shorthands_with_enums: false
      prefer_shorthands_with_constructors: false
      prefer_returning_shorthands: false
      prefer_switch_expression: false
      prefer_shorthands_with_static_fields: false
      prefer_class_destructuring: true          # opt-in: lints are off by default

  riverpod_lint:  # 3.1+ uses analysis_server_plugin; all rules are warnings (auto-enabled)

analyzer:
  exclude:
    - "**/*.g.dart"
    - "**/*.freezed.dart"
    - "**/*.gr.dart"
    - "**/*.arb"
  plugins:
    - custom_lint  # legacy system — for freezed_lint only
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
    - always_use_package_imports
    - require_trailing_commas
    - prefer_single_quotes
    - directives_ordering
    - avoid_multiple_declarations_per_line
    - prefer_const_constructors
    - prefer_const_declarations
    - prefer_const_literals_to_create_immutables
    - prefer_final_locals
    - avoid_redundant_argument_values
    - avoid_dynamic_calls
    - cancel_subscriptions
    - close_sinks
    - unawaited_futures
```

## Install

```bash
flutter pub add dev:flutter_lints
flutter pub add dev:custom_lint    # for freezed_lint
flutter pub add dev:freezed_lint   # via custom_lint
flutter pub add dev:riverpod_lint  # 3.1+ uses analysis_server_plugin (not custom_lint)
# many_lints: auto-downloaded by the Dart 3.10+ plugin system
```
