# Building Flutter Apps

> A strict Flutter architecture skill and plugin for teams that want Riverpod,
> Freezed, typed GoRouter, Hive CE, localization, tests, accessibility, and
> runtime proof enforced the same way every time.

<p align="center">
  <img src="docs/assets/readme-hero.png" alt="Dash reviewing Flutter architecture enforcement checks" width="100%">
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-blue.svg"></a>
  <a href="https://flutter.dev"><img alt="Flutter" src="https://img.shields.io/badge/Flutter-3.x-02569B.svg"></a>
  <a href="https://riverpod.dev"><img alt="Riverpod" src="https://img.shields.io/badge/Riverpod-3.x-00B4D8.svg"></a>
</p>

This is not a generic Flutter tips repo. It is an opinionated policy package for
building Flutter apps with one clear architecture and enough local enforcement
that an agent cannot quietly drift into weaker patterns.

It is unofficial. It is not affiliated with Google, Flutter, Dart, Riverpod, or
their maintainers.

## What It Enforces

The target app shape is simple:

```text
UI widgets
  -> generated Riverpod providers and notifiers
  -> repositories
  -> local or remote datasources
  -> APIs, Hive boxes, platform plugins

Domain entities stay pure Dart.
Navigation goes through typed GoRouter routes.
User-facing copy goes through gen-l10n.
Behavior is proven with tests, lints, hooks, evals, and E2E evidence.
```

The main rules:

- Providers are generated with `@riverpod` / `@Riverpod`; manual provider
  constructors are out.
- State and domain models use sealed Freezed classes; hand-written immutable
  patterns are out.
- Widgets render and dispatch only. Business logic, storage, networking, and
  policy live behind their owning provider, notifier, repository, datasource, or
  service.
- Async work is guarded with `ref.mounted` or `context.mounted`.
- Domain primitives with meaning become Value Objects.
- Route strings are owned by typed GoRouter definitions and generated helpers.
- Visible strings, tooltips, and semantic labels come from `AppLocalizations`.
- Shared/realtime flows need writer plus observer proof, not screenshots.

## Why This Is Opinionated

Flutter lets teams build the same feature many ways. That flexibility is useful
for experiments, but it is expensive when agents are writing production code:
each extra acceptable pattern becomes another place for drift, hidden state, weak
tests, or shallow wrappers.

This architecture chooses one path on purpose. It is better for this workflow
because it makes ownership obvious:

| Common drift | This architecture forces |
|---|---|
| Widgets reaching into storage, HTTP, or plugins. | Widgets render localized UI and dispatch user intent only. |
| Notifiers mixing state transitions with SDK details. | Notifiers own state; repositories and datasources own IO boundaries. |
| Domain models shaped by JSON, Hive, or Flutter widgets. | Domain stays pure Dart with explicit Value Objects and invariants. |
| Route strings copied through the app. | Typed GoRouter routes are the navigation source of truth. |
| "Looks fine" UI changes without proof. | Lints, hooks, tests, accessibility checks, evals, and E2E proof all matter. |

The tradeoff is deliberate: less framework freedom, more repeatability. The goal
is not to cover every valid Flutter style. The goal is to make one strict style
easy to review, easy to test, and hard for an agent to accidentally weaken.

## How Enforcement Works

Install it as a plugin when you want enforcement. A raw `SKILL.md` install is
guidance-only and cannot register runtime hooks.

| Layer | What it does | Source |
|---|---|---|
| Skill | Loads the rules, trigger map, and pre-flight checklist into the agent context. | [SKILL.md](SKILL.md) |
| Hooks | Blocks obvious drift after edits and before the agent stops. | [hooks/](hooks/) |
| Analyzer | Enforces AST-level Flutter/Riverpod rules through `dart analyze`. | [analysis_options.yaml](references/analysis_options.yaml) |
| Evals | Checks trigger behavior and answer quality with `gpt-5.4-mini`. | [evals/](evals/) |
| References | Holds detailed guidance so `SKILL.md` stays small and direct. | [references/](references/) |

The hard project gate is still package-root `dart analyze` with
`flutter_skill_lints` and `riverpod_lint` wired under top-level `plugins:` in
`analysis_options.yaml`.

## Architecture

```text
lib/
├── core/
│   ├── extensions/
│   ├── navigation/
│   ├── services/
│   ├── theme/
│   └── widgets/
├── features/
│   └── feature_x/
│       ├── data/           # DTOs, models, local/remote datasources
│       ├── domain/         # Pure Dart entities and value objects
│       ├── repositories/   # Orchestration and model/entity mapping
│       └── presentation/   # Notifiers, screens, atoms, widgets
└── main.dart
```

Ownership rules are the point:

| Owner | Belongs here | Does not belong here |
|---|---|---|
| Widget | Layout, localized rendering, user dispatch. | Storage, HTTP, mutation policy, provider-derived caches. |
| Notifier | State transitions, mutation flow, durable UI status. | Hive calls, plugin calls, raw HTTP, hidden dependency construction. |
| Repository | Domain-facing contract and orchestration. | UI state, BuildContext, widget concerns. |
| Datasource | API/Hive/platform details and wire models. | Domain policy or presentation decisions. |
| Domain | Pure entities, Value Objects, invariants. | Flutter imports, JSON, Hive annotations, UI copy. |

## Install

### Claude Code

```bash
/plugin marketplace add sgaabdu4/building-flutter-apps
/plugin install building-flutter-apps@building-flutter-apps
```

Claude reads `.claude-plugin/marketplace.json` and
`.claude-plugin/plugin.json`, then loads `hooks/hooks.json`.

### Codex CLI

```bash
codex features enable hooks
codex features enable plugin_hooks
codex plugin marketplace add sgaabdu4/building-flutter-apps
codex
/plugins
```

In `/plugins`, open the `building-flutter-apps` marketplace entry and install
the plugin. Codex reads `.codex-plugin/plugin.json` and loads
`hooks/hooks.json`.

### Copilot CLI

```bash
copilot plugin marketplace add sgaabdu4/building-flutter-apps
copilot plugin install building-flutter-apps@building-flutter-apps
```

Copilot reads `.github/plugin/marketplace.json` and root `plugin.json`, then
loads `hooks/hooks.copilot.json`.

## Bootstrap A Flutter Project

```bash
cp <plugin-cache>/references/analysis_options.yaml ./analysis_options.yaml
mkdir -p lib/core/extensions
cp <plugin-cache>/templates/flutter/lib/core/extensions/*.dart ./lib/core/extensions/
dart pub get
dart analyze
```

Notes:

- `flutter_skill_lints` is an analyzer plugin. Keep it only in
  `analysis_options.yaml` under `plugins:`; do not add it to `pubspec.yaml`.
- If `lib/core/extensions/` already exists, merge the template files instead of
  overwriting them.
- A healthy setup should prove that at least one `flutter_skill_lints`
  diagnostic and one `riverpod_lint` diagnostic can fire.

## What's Included

### Core Stack

This table is the version source of truth. Keep setup snippets and examples in
sync with it.

| Package | Constraint | Purpose |
|---|---:|---|
| `flutter_riverpod` | `^3.3.2` | State management |
| `riverpod_annotation` | `^4.0.3` | Codegen annotations |
| `riverpod_generator` | `^4.0.4` | Provider codegen |
| `freezed_annotation` | `^3.1.0` | Sealed-union annotations |
| `freezed` | `^3.2.5` | Immutable classes; needs Dart SDK >= 3.8 |
| `json_annotation` | `^4.12.0` | JSON annotations |
| `json_serializable` | `6.14.0` | JSON codegen; exact pin |
| `go_router` | `^17.3.0` | Declarative routing |
| `go_router_builder` | `^4.3.0` | Typed route codegen |
| `hive_ce` | `^2.19.3` | Binary local persistence |
| `hive_ce_flutter` | `^2.3.4` | Flutter glue for `hive_ce` |
| `hive_ce_generator` | `1.11.2` | Hive type adapters; exact pin |
| `build_runner` | `^2.15.0` | Codegen runner |

`json_serializable` and `hive_ce_generator` stay exact because code generators
bind analyzer constraints. Lift them only after a real project pub solve and
`dart analyze` prove the full Riverpod/Freezed/Hive generator stack is
compatible.

### Hook Events

| Runtime | Edit hook | Stop hook | Prompt hook |
|---|---|---|---|
| Claude Code | `PostToolUse` | `Stop` | `UserPromptSubmit` |
| Codex CLI | `PostToolUse` | `Stop` | `UserPromptSubmit` |
| Copilot CLI | `postToolUse` | `agentStop` | `userPromptSubmitted` |

The hook scripts no-op outside Flutter projects by walking upward for
`pubspec.yaml`.

### Reference Guide

| Topic | File |
|---|---|
| Architecture and layers | [references/architecture.md](references/architecture.md) |
| Analyzer setup | [references/analysis-options.md](references/analysis-options.md) |
| Atomic UI and accessibility | [references/atomic-design.md](references/atomic-design.md) |
| Riverpod codegen | [references/riverpod-codegen.md](references/riverpod-codegen.md) |
| Freezed and sealed state | [references/freezed-sealed.md](references/freezed-sealed.md) |
| State lifecycle | [references/state-management-lifecycle.md](references/state-management-lifecycle.md) |
| Testing | [references/testing.md](references/testing.md) |
| Networking boundaries | [references/networking.md](references/networking.md) |
| l10n and ARB files | [references/localization.md](references/localization.md) |
| Typed routing and deep links | [references/deep-linking.md](references/deep-linking.md) |
| Common patterns | [references/common-patterns.md](references/common-patterns.md) |
| Hive CE persistence | [references/hive-persistence.md](references/hive-persistence.md) |
| Widget previews | [references/widget-previews.md](references/widget-previews.md) |
| Runtime E2E proof | [references/dart-mcp-e2e-testing.md](references/dart-mcp-e2e-testing.md) |

## Evals And Proof

The eval harnesses are deliberately split:

| File | Purpose |
|---|---|
| [evals/trigger-eval.json](evals/trigger-eval.json) | Checks when the skill should and should not activate. |
| [evals/evals.json](evals/evals.json) | Checks whether answers follow the policy. |
| [evals/results/](evals/results/) | Stores compact `gpt-5.4-mini` proof artifacts. |
| [evals/gpt-5.4-mini-eval-decisions.md](evals/gpt-5.4-mini-eval-decisions.md) | Records eval decisions, tradeoffs, and proof. |

Run the local structural checks before publishing changes:

```bash
bash tool/check_drift.sh
bash tool/smoke_test.sh
ruby tool/verify_markdown_examples.rb
```

## Code Generation

Use the long flag in documentation and automation:

```bash
dart run build_runner watch --delete-conflicting-outputs
dart run build_runner build --delete-conflicting-outputs
dart run build_runner clean && dart run build_runner build --delete-conflicting-outputs
```

## Upstream Drift

This repo tracks the upstream `flutter/skills` Flutter skill set by commit and
per-skill hash in [tool/upstream/flutter_skills.lock.json](tool/upstream/flutter_skills.lock.json).

```bash
ruby tool/check_upstream_flutter_skills.rb
ruby tool/check_upstream_flutter_skills.rb --update
```

Use `--strict-commit` when CI should fail on upstream commits even if tracked
Flutter skill files did not change.

## Contributing

Keep changes small and enforceable:

- Put detailed guidance in `references/`, not in `SKILL.md`.
- Keep `README.md -> Core Stack` as the package-version SSOT.
- Add or update hook fixtures when changing scanner behavior.
- Add eval cases when changing trigger behavior or answer policy.
- Run drift, smoke, markdown-example, and relevant eval checks before release.

## License

MIT. See [LICENSE](LICENSE).
