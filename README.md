# Flutter Riverpod Clean Architecture Skill

> Flutter clean arch w/ Riverpod 3.x codegen, Freezed 3.x sealed, GoRouter, Hive CE persist.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Flutter](https://img.shields.io/badge/Flutter-3.x-02569B.svg)](https://flutter.dev)
[![Riverpod](https://img.shields.io/badge/Riverpod-3.x-00B4D8.svg)](https://riverpod.dev)

> **Disclaimer:** Unofficial. No affiliation w/ Google, Flutter team, Riverpod maintainers. "Flutter" trademark Google LLC. "Riverpod" by Remi Rousselet.

> **Opinionated by design:** Strict patterns over flexible style.

## Installation

Install this as a plugin, not as a raw skill, when you want enforcement. Raw
Agent Skills installs only provide prompt guidance; they cannot register hooks
or run scanners.

### Claude Code

```bash
/plugin marketplace add sgaabdu4/building-flutter-apps
/plugin install building-flutter-apps@building-flutter-apps
```

Reads `.claude-plugin/marketplace.json` + `.claude-plugin/plugin.json`.
Auto-loads `hooks/hooks.json`:

- **PostToolUse** (`dart_gate.sh`) — grep + awk checks after every `Write|Edit|MultiEdit`; blocks turn with violation reason.
- **Stop** (`preflight_audit.sh`) — full repo audit + `dart analyze --fatal-infos` before turn ends.
- **UserPromptSubmit** (`skill_reminder.sh`) — top-5 rules reminder per turn in Flutter projects.

### Codex CLI

```bash
codex features enable hooks
codex features enable plugin_hooks
codex plugin marketplace add sgaabdu4/building-flutter-apps
codex
/plugins
```

In `/plugins`, choose the `building-flutter-apps` marketplace tab, open the
`building-flutter-apps` plugin, and select `Install plugin`.

Reads `.codex-plugin/plugin.json` from the installed plugin. Codex marketplaces
can be added from GitHub shorthand (`owner/repo`), Git URLs, SSH URLs, or local
marketplace roots; Codex also recognizes repo-local
`.claude-plugin/marketplace.json` entries. Auto-loads the manifest-declared
`hooks/hooks.json` — same `PostToolUse`/`Stop`/`UserPromptSubmit` events, same
scripts as Claude.

The `hooks` feature enables Codex lifecycle hooks. Current Codex builds also
require `plugin_hooks` for plugin-bundled lifecycle configs. If you edit
`~/.codex/config.toml` directly, use:

```toml
[features]
hooks = true
plugin_hooks = true
```

Public Codex docs may still show `codex_hooks` for the lifecycle hook gate.
Use the CLI commands above on current Codex builds; `codex features list`
shows the feature key your installed CLI accepts.

### Copilot CLI

```bash
copilot plugin marketplace add sgaabdu4/building-flutter-apps
copilot plugin install building-flutter-apps@building-flutter-apps
```

Reads `.github/plugin/marketplace.json` + root `plugin.json`. Auto-loads `hooks/hooks.copilot.json` (camelCase event names, `bash`/`powershell` fields per Copilot schema):

- **postToolUse** → `dart_gate.sh`
- **agentStop** → `preflight_audit.sh`
- **userPromptSubmitted** → `skill_reminder.sh`

All scripts no-op outside Flutter projects (gated on upward `pubspec.yaml` discovery).

### Enforcement model

Install-time script execution is not a safe assumption across agent runtimes.
The enforceable contract is:

1. **Plugin install wires hooks** for Claude Code, Codex CLI, and Copilot CLI.
2. **First Flutter prompt/edit/stop proves hooks are active** because the
   `UserPromptSubmit`, `PostToolUse`, and `Stop`/`agentStop` hooks fire from the
   installed plugin.
3. **Project CI remains the hard gate** through `dart analyze` with
   `flutter_skill_lints` and `riverpod_lint` in `analysis_options.yaml`.

If a user installs only `SKILL.md` or copies `~/.agents/skills/building-flutter-apps`,
none of the scanners run. Treat that as guidance-only mode.

### Project bootstrap (one-time per Flutter project)

```bash
cp <plugin-cache>/references/analysis_options.yaml ./analysis_options.yaml
dart pub get
dart analyze   # confirms wiring
```

`flutter_skill_lints` is an external analyzer plugin. List it ONLY under `plugins:` in `analysis_options.yaml` (NEVER in `pubspec.yaml`). The bundled `analysis_options.yaml` already wires it.

## How drift is prevented

The skill enforces rules across SKILL.md, the reference docs, and the bundled
analyzer config via a 3-tier mechanism:

| Tier | Mechanism | Covers |
|---|---|---|
| **AST** | `flutter_skill_lints` analyzer plugin running via `dart analyze` | private widget classes, `_buildXxx()`, `dynamic` (except `Map<String, dynamic>`), null-bang, `shrinkWrap: true`, legacy provider types, route-param throw, showcase key filtering, sync notifier state-read, typed-route navigation boundaries, raw route definitions, context.pop guard, `ref.mounted` / `context.mounted` after await, sealed Freezed, unawaited fire-and-forget |
| **Write-time grep** | `hooks/scripts/dart_gate.sh` (PostToolUse hook) + `hooks/scripts/preflight_audit.sh` (Stop hook) | hardcoded UI strings, inline `ValueKey('...')`, raw or named context/router page navigation, direct Navigator page pushes, snackbar dispatch from widget, `AppLocalizations.of(context)!`, gen-l10n path config, app-root text scale clamp |
| **Prompt** | SKILL.md `<gate>` + `<critical-always>` + `<trigger-map>` + tiered `<pre-flight>` + `<recap>`; each reference file has its own `<trigger>` + `<recap>` | semantic / architectural rules — `_ensureRepository` in mutations, sync notifier init order, source-of-truth refresh, observer+writer E2E, navigation sequencing, etc. |

Cross-tool: Claude Code, Codex CLI, and Copilot CLI all install hook manifests
via the plugin install commands above. All three fire the same three scripts in
`hooks/scripts/`. The AST tier (`dart analyze` + `flutter_skill_lints`) applies
wherever `dart analyze` runs. The prompt tier (SKILL.md + references) applies
on every Agent Skills tool, but it does not execute scanners by itself.

## What's Included

Flutter dev guidance, modern best practices:

### Core Stack

This is the canonical version table (SSOT). Update related setup snippets when
changing it.

| Package | Constraint | Purpose |
|---------|-----------|---------|
| flutter_riverpod | `^3.3.1` | State mgmt |
| riverpod_annotation | `^4.0.2` | Codegen annotations |
| riverpod_generator | `^4.0.3` | Provider codegen (dev_dependency) |
| freezed_annotation | `^3.1.0` | Sealed-union annotations |
| freezed | `^3.2.5` | Immutable classes (dev_dependency) — needs Dart SDK ≥ 3.8 |
| json_annotation | `^4.11.0` | JSON annotations |
| json_serializable | `6.13.0` | JSON codegen (**exact pin** — see note) |
| go_router | `^17.2.3` | Declarative routing |
| go_router_builder | `^4.3.0` | Typed route codegen (dev_dependency) |
| hive_ce | `^2.19.3` | Binary local persist |
| hive_ce_flutter | `^2.3.4` | Flutter glue for `hive_ce` |
| hive_ce_generator | `1.11.0` | Hive type adapters (**exact pin** — see note) |
| build_runner | `^2.15.0` | Codegen runner (dev_dependency) |
| showcaseview | `^5.0.2` | First-run guided tours |

**Pin note.** `json_serializable` and `hive_ce_generator` stay at exact pins
because they bind the analyzer version and the Riverpod generator stack
currently resolves on analyzer 9. Lift to caret ranges only after
`dart pub deps -s compact | rg analyzer` no longer shows analyzer 9.

### Architecture
4-layer clean arch:
```
lib/
├── core/           # Shared: theme, utils, widgets, navigation, services
├── features/       # Feature modules (auth, products, home, ...)
│   └── feature_x/
│       ├── data/           # Models, datasources
│       ├── domain/         # Entities (pure Dart)
│       ├── repositories/   # Data orchestration
│       └── presentation/   # Notifiers, screens, widgets
└── main.dart
```

### Key Patterns
- **Codegen-only providers** — no `StateProvider`, `StateNotifierProvider`, legacy
- **Sealed classes** — exhaustive match w/ Dart `switch`
- **Interface contracts** — `abstract interface class` per repo, datasource
- **No prop drilling** — children watch providers direct
- **Async safety** — `if (!ref.mounted) return;` after every `await`
- **Unified Ref** — single `Ref` (no `AutoDisposeRef`, `ExampleRef`)
- **Widget classes only** — no `_buildXxx` helpers
- **No `dynamic`** — use `Object?` or proper type
- **Data-layer networking** — widgets/notifiers never call HTTP directly
- **Navigation SSOT** — widgets/notifiers call generated typed GoRouter route helpers directly
- **Localized UI copy** — gen-l10n/ARB for user-facing strings
- **Preview-safe components** — Flutter Widget Previewer with provider fakes
- **Primary static analysis** — `flutter_skill_lints` + `riverpod_lint`

## Reference Files

| Topic | File |
|-------|------|
| Architecture layers | [architecture.md](references/architecture.md) |
| Canonical analyzer config | [analysis_options.yaml](references/analysis_options.yaml) |
| Atomic design (tokens → pages) | [atomic-design.md](references/atomic-design.md) |
| Widget previews | [widget-previews.md](references/widget-previews.md) |
| Riverpod 3.x codegen | [riverpod-codegen.md](references/riverpod-codegen.md) |
| Freezed 3.x sealed classes | [freezed-sealed.md](references/freezed-sealed.md) |
| State management patterns | [state-management.md](references/state-management.md) |
| Testing with ProviderContainer.test | [testing.md](references/testing.md) |
| HTTP/networking boundaries | [networking.md](references/networking.md) |
| Localization/gen-l10n | [localization.md](references/localization.md) |
| Deep linking/App Links/Universal Links | [deep-linking.md](references/deep-linking.md) |
| Pagination, search, forms | [common-patterns.md](references/common-patterns.md) |
| Layout diagnostics | [layout-diagnostics.md](references/layout-diagnostics.md) |
| Performance optimization | [performance.md](references/performance.md) |
| Flutter optimizations | [flutter-optimizations.md](references/flutter-optimizations.md) |
| Extensions & utilities | [extensions-utilities.md](references/extensions-utilities.md) |
| Hive CE persistence, TypeAdapters | [hive-persistence.md](references/hive-persistence.md) |
| Showcase guided tours | [showcase-tours.md](references/showcase-tours.md) |

## Compatible Agents

| Tool | Hooks | Install command |
|---|---|---|
| [Claude Code](https://code.claude.com/) | PostToolUse + Stop + UserPromptSubmit | `/plugin marketplace add sgaabdu4/building-flutter-apps` |
| [Codex CLI](https://developers.openai.com/codex/cli) | PostToolUse + Stop + UserPromptSubmit | `codex features enable hooks`, `codex features enable plugin_hooks`, `codex plugin marketplace add sgaabdu4/building-flutter-apps`, then `codex` → `/plugins` |
| [Copilot CLI](https://docs.github.com/en/copilot/concepts/agents/copilot-cli) | postToolUse + agentStop + userPromptSubmitted | `copilot plugin marketplace add sgaabdu4/building-flutter-apps`, then `copilot plugin install building-flutter-apps@building-flutter-apps` |
| Any other Agent Skills tool | Skill text only (no hooks) | Read SKILL.md directly |

## Usage

Auto-activates on:
- Build/review/refactor Flutter apps
- Riverpod state mgmt work
- Freezed data classes
- GoRouter nav setup

Or invoke direct:
```
/building-flutter-apps
```

## Code Generation

`-d` is shorthand for `--delete-conflicting-outputs` (used below).

```bash
# Watch mode (dev)
dart run build_runner watch -d   # --delete-conflicting-outputs

# One-time build
dart run build_runner build -d   # --delete-conflicting-outputs

# Clean build
dart run build_runner clean && dart run build_runner build -d   # --delete-conflicting-outputs
```

## Upstream Drift Check

This repo tracks the upstream `flutter/skills` Flutter skill set by commit and
per-skill hash in [flutter_skills.lock.json](tool/upstream/flutter_skills.lock.json).

```bash
# Flag when upstream Flutter skill content changed
ruby tool/check_upstream_flutter_skills.rb

# Refresh the lock after reviewing/adopting upstream changes
ruby tool/check_upstream_flutter_skills.rb --update
```

Default behavior exits non-zero only when upstream skill content changes. Use
`--strict-commit` if CI should also fail on upstream repo commits that do not
touch tracked Flutter skill files.

## Contributing

PRs welcome:

1. Fork repo
2. Create branch (`git checkout -b feature/add-pattern`)
3. Match existing doc style
4. Submit PR

### Guidelines
- SKILL.md <500 lines
- Detailed patterns → `references/` files
- Working code examples
- Test w/ Riverpod 3.x + Freezed 3.x
- Follow arch guidelines

## License

MIT — see [LICENSE](LICENSE)

## Resources

- [Riverpod Documentation](https://riverpod.dev)
- [Freezed Package](https://pub.dev/packages/freezed)
- [GoRouter Documentation](https://pub.dev/packages/go_router)
- [Flutter Documentation](https://flutter.dev/docs)
