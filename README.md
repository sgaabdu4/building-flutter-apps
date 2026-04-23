# Flutter Riverpod Clean Architecture Skill

> Flutter clean arch w/ Riverpod 3.x codegen, Freezed 3.x sealed, GoRouter, Hive CE persist.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Flutter](https://img.shields.io/badge/Flutter-3.x-02569B.svg)](https://flutter.dev)
[![Riverpod](https://img.shields.io/badge/Riverpod-3.x-00B4D8.svg)](https://riverpod.dev)

> **Disclaimer:** Unofficial. No affiliation w/ Google, Flutter team, Riverpod maintainers. "Flutter" trademark Google LLC. "Riverpod" by Remi Rousselet.

> **Opinionated by design:** Strict patterns over flexible style.

## Installation

```bash
npx skills add sgaabdu4/building-flutter-apps
```

Or clone to `~/.claude/skills/`:

```bash
git clone https://github.com/sgaabdu4/building-flutter-apps ~/.claude/skills/building-flutter-apps
```

## What's Included

Flutter dev guidance, modern best practices:

### Core Stack
| Package | Version | Purpose |
|---------|---------|---------|
| flutter_riverpod | 3.2.1+ | State mgmt |
| riverpod_annotation | 3.x | Codegen annotations |
| riverpod_generator | 3.x | Provider codegen |
| freezed | 3.2.5+ | Immutable classes, unions |
| go_router | 17.1.0+ | Declarative routing |
| hive_ce | 2.19.3+ | Binary local persist |

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
- **Enforcement** — every ref file has MUST/NEVER rules at top

## Reference Files

| Topic | File |
|-------|------|
| Architecture layers | [architecture.md](references/architecture.md) |
| Atomic design (tokens → pages) | [atomic-design.md](references/atomic-design.md) |
| Riverpod 3.x codegen | [riverpod-codegen.md](references/riverpod-codegen.md) |
| Freezed 3.x sealed classes | [freezed-sealed.md](references/freezed-sealed.md) |
| State management patterns | [state-management.md](references/state-management.md) |
| Testing with ProviderContainer.test | [testing.md](references/testing.md) |
| Pagination, search, forms | [common-patterns.md](references/common-patterns.md) |
| Performance optimization | [performance.md](references/performance.md) |
| Flutter optimizations | [flutter-optimizations.md](references/flutter-optimizations.md) |
| Extensions & utilities | [extensions-utilities.md](references/extensions-utilities.md) |
| Hive CE persistence, TypeAdapters | [hive-persistence.md](references/hive-persistence.md) |
| Showcase guided tours | [showcase-tours.md](references/showcase-tours.md) |

## Compatible Agents

- [Claude Code](https://code.claude.com/)
- [Cursor](https://cursor.sh/)
- [Windsurf](https://windsurf.ai/)
- Any agent w/ [Agent Skills](https://agentskills.io/) standard

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

```bash
# Watch mode (recommended during development)
dart run build_runner watch -d

# One-time build
dart run build_runner build -d

# Clean build (resolve conflicts)
dart run build_runner clean && dart run build_runner build -d
```

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