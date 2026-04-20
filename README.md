# Flutter Riverpod Clean Architecture Skill

> Flutter clean architecture with Riverpod 3.x codegen, Freezed 3.x sealed classes, GoRouter, Hive CE persistence.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Flutter](https://img.shields.io/badge/Flutter-3.x-02569B.svg)](https://flutter.dev)
[![Riverpod](https://img.shields.io/badge/Riverpod-3.x-00B4D8.svg)](https://riverpod.dev)

> **Disclaimer:** Unofficial community resource. Not affiliated with, endorsed by, or sponsored by Google, Flutter team, or Riverpod maintainers. "Flutter" trademark of Google LLC. "Riverpod" maintained by Remi Rousselet.

> **Opinionated by design:** Strict consistent patterns over flexible style.

## Installation

```bash
npx skills add sgaabdu4/building-flutter-apps
```

Or clone into `~/.claude/skills/`:

```bash
git clone https://github.com/sgaabdu4/building-flutter-apps ~/.claude/skills/building-flutter-apps
```

## What's Included

Guidance for Flutter dev with modern best practices:

### Core Stack
| Package | Version | Purpose |
|---------|---------|---------|
| flutter_riverpod | 3.2.1+ | State management |
| riverpod_annotation | 3.x | Codegen annotations |
| riverpod_generator | 3.x | Provider code generation |
| freezed | 3.2.5+ | Immutable data classes, unions |
| go_router | 17.1.0+ | Declarative routing |
| hive_ce | 2.19.3+ | Binary local persistence |

### Architecture
Four-layer clean architecture:
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
- **Codegen-only providers** — no `StateProvider`, `StateNotifierProvider`, legacy providers
- **Sealed classes** — exhaustive pattern matching with Dart native `switch`
- **Interface contracts** — `abstract interface class` for every repository, datasource
- **No prop drilling** — child widgets watch providers directly
- **Async safety** — `if (!ref.mounted) return;` after every `await`
- **Unified Ref** — single `Ref` type (no `AutoDisposeRef`, `ExampleRef`)
- **Widget classes only** — no helper methods (`_buildXxx`)
- **No `dynamic`** — use `Object?` or proper type
- **Enforcement** — every reference file has MUST/NEVER rules at top

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
- Any agent supporting [Agent Skills](https://agentskills.io/) standard

## Usage

Skill auto-activates when you:
- Build, review, refactor Flutter apps
- Work with Riverpod state management
- Implement Freezed data classes
- Set up GoRouter navigation

Or invoke directly:
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

Contributions welcome:

1. Fork repo
2. Create feature branch (`git checkout -b feature/add-pattern`)
3. Follow existing doc style
4. Submit PR

### Guidelines
- Keep SKILL.md under 500 lines
- Add detailed patterns to `references/` files
- Include working code examples
- Test with Riverpod 3.x and Freezed 3.x
- Follow architecture guidelines

## License

MIT — see [LICENSE](LICENSE)

## Resources

- [Riverpod Documentation](https://riverpod.dev)
- [Freezed Package](https://pub.dev/packages/freezed)
- [GoRouter Documentation](https://pub.dev/packages/go_router)
- [Flutter Documentation](https://flutter.dev/docs)