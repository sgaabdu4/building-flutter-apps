# analysis_options.yaml


## Read first

1. `dart analyze` from package root. No path arg. Never `flutter analyze lib`.
2. Analyzer plugins live ONLY in `analysis_options.yaml` top-level `plugins:` — never `pubspec.yaml` deps.
3. Enable strict casts/inference/raw types. Exclude generated files.
4. Setup/fix answers must explicitly verify one `flutter_skill_lints` diagnostic and one `riverpod_lint` diagnostic can fire before calling setup complete.

## Trigger

Signals: analysis_options, dart analyze, flutter_skill_lints, riverpod_lint
Before code: output `Reading: analysis-options.md`


Copy `references/analysis_options.yaml` to every Flutter project root. For new Flutter apps,
also copy `templates/flutter/lib/core/extensions/` to `lib/core/extensions/`
so shared context primitives such as `context.isCurrentModalRoute` exist before
feature code needs them.

## Required

- `strict-casts`, `strict-inference`, `strict-raw-types`: true
- Async: `unawaited_futures`, `discarded_futures`, `avoid_void_async`
- Resources: `avoid_print`, `cancel_subscriptions`, `close_sinks`
- Effective Dart Design API shape: `always_declare_return_types`,
  `type_annotate_public_apis`, `avoid_positional_boolean_parameters`,
  `avoid_equals_and_hash_code_on_mutable_classes`,
  `avoid_null_checks_in_equality_operators`,
  `avoid_private_typedef_functions`, `avoid_returning_this`,
  `avoid_setters_without_getters`, `prefer_mixin`,
  `use_to_and_as_if_applicable`
- Effective Dart Design API safety plugin rules:
  `avoid_futureor_return_type`,
  `avoid_nullable_async_or_collection_return_type`,
  `avoid_public_late_final_without_initializer`
- `prefer_type_over_var` is forbidden in this profile: it conflicts with
  Effective Dart's preference for inferred initialized local variables.
- Do not enable `avoid_types_on_closure_parameters`: `strict-inference`
  sometimes requires explicit closure parameter types at weakly typed APIs
  such as `testWidgets`.
- Do not enable `avoid_classes_with_only_static_members` in Flutter app
  profiles: the skill uses `abstract final class` namespaces for tiny
  constants/platform facade APIs where a named owner improves discovery.
- Do not enable `one_member_abstracts` for architecture profiles:
  one-method repository/datasource/service contracts are valid dependency
  boundaries.
- Do not enable `omit_local_variable_types` until the project has removed
  explicit local types mechanically; this profile no longer enforces the
  opposite rule.
- Do not enable `use_setters_to_change_properties` for async persistence APIs:
  Dart setters cannot be `async`, and these mutation methods must remain
  awaitable.
- Codegen: `invalid_annotation_target: ignore`
- Exclude: `*.g.dart`, `*.freezed.dart`, `*.gr.dart`, `*.arb`

## Install

```bash
flutter pub add dev:flutter_lints
```

Plugin block:

```yaml
plugins:
  # Stable Riverpod lint pin verified for Riverpod 3.3-era lint coverage.
  riverpod_lint: 3.1.4
  flutter_skill_lints:
```

Match bundled [`references/analysis_options.yaml`](analysis_options.yaml)
exactly. Both pin `flutter_skill_lints` version OR neither — keep aligned.

New-project baseline:

```bash
cp <skill>/references/analysis_options.yaml ./analysis_options.yaml
mkdir -p lib/core/extensions
cp <skill>/templates/flutter/lib/core/extensions/*.dart ./lib/core/extensions/
```

If `lib/core/extensions/` already exists, merge the template files. Do not
overwrite project-specific extensions.

## Rules

- Plugins go top-level `plugins:`. Not under `analyzer:`. Not in `pubspec.yaml`.
- Use `flutter_skill_lints` + `riverpod_lint` as shown.
- No `git:`/`path:` under `plugins:` unless local checkout.

## Verify

1. `flutter pub get`
2. `dart analyze --verbose` (package root, no path arg)
3. Fail on `server.pluginError`
4. One `flutter_skill_lints` diagnostic
5. One `riverpod_lint` diagnostic

Do not omit steps 4-5 in analyzer setup answers; green analysis alone does not
prove both plugins are loaded.

Scope: `dart analyze` = analyzer/plugin gate. [Dart Decimate](dart-decimate.md) = complementary graph/code-health gate. Use `flutter pub get` + publish/dry-run for package validity.

## Use `dart analyze`, NOT `flutter analyze`

Run `dart analyze` from package root. No path arg. Avoid `flutter analyze` + `flutter analyze lib` + `dart analyze lib`.

CI/scripts: `dart analyze`. Never `flutter analyze lib`.
Tracking: https://github.com/flutter/flutter/issues/184190.

## Fix plugin crash

1. Remove analyzer plugins from `pubspec.yaml` deps: `riverpod_lint`, `custom_lint`, `custom_lint_builder`, `flutter_skill_lints`, any package listed under `plugins:`.
2. Keep analyzer plugins only in `analysis_options.yaml plugins:`.
3. Keep included lint packages as normal dev deps, e.g. `flutter_lints`.
4. Run `flutter pub get`.
5. Restart analysis server or rerun `dart analyze`.

## Fix stale `~/.dartServer`

```bash
mv ~/.dartServer ~/.dartServer.bak-$(date +%Y%m%d%H%M%S)
dart analyze
```

Use absolute `--cache=` paths only.
