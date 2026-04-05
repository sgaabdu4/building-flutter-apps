# Flutter Riverpod Clean Architecture Skill

> Flutter clean architecture patterns with Riverpod 3.x codegen, Freezed 3.x sealed classes, GoRouter, and Hive CE persistence.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Flutter](https://img.shields.io/badge/Flutter-3.x-02569B.svg)](https://flutter.dev)
[![Riverpod](https://img.shields.io/badge/Riverpod-3.x-00B4D8.svg)](https://riverpod.dev)

> **Disclaimer:** This is an unofficial community resource. It is not affiliated with, endorsed by, or sponsored by Google, the Flutter team, or the Riverpod maintainers. "Flutter" is a trademark of Google LLC. "Riverpod" is maintained by Remi Rousselet.

## Installation

```bash
npx skills add sgaabdu4/building-flutter-apps
```

Or manually clone into `~/.claude/skills/`:

```bash
git clone https://github.com/sgaabdu4/building-flutter-apps ~/.claude/skills/building-flutter-apps
```

## What's Included

This skill provides AI agents with comprehensive guidance for Flutter development using modern best practices:

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
- **Codegen-only providers** — No `StateProvider`, `StateNotifierProvider`, or legacy providers
- **Sealed classes** — Exhaustive pattern matching with Dart's native `switch`
- **Interface contracts** — `abstract interface class` for every repository and datasource
- **No prop drilling** — Child widgets watch providers directly
- **Async safety** — `if (!ref.mounted) return;` guards after every `await`
- **Unified Ref** — Single `Ref` type (no `AutoDisposeRef`, `ExampleRef`)
- **Widget classes only** — No helper methods (`_buildXxx`)
- **No `dynamic`** — Use `Object?` or a proper type
- **Enforcement** — Every reference file has MUST/NEVER rules at the top

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
- Any agent supporting the [Agent Skills](https://agentskills.io/) standard

## Usage

Once installed, the skill automatically activates when you:
- Build, review, or refactor Flutter apps
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

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/add-pattern`)
3. Follow existing documentation style
4. Submit a pull request

### Guidelines
- Keep SKILL.md under 500 lines
- Add detailed patterns to `references/` files
- Include working code examples
- Test with Riverpod 3.x and Freezed 3.x
- Follow the architecture guidelines

## License

MIT — see [LICENSE](LICENSE)

## Resources

- [Riverpod Documentation](https://riverpod.dev)
- [Freezed Package](https://pub.dev/packages/freezed)
- [GoRouter Documentation](https://pub.dev/packages/go_router)
- [Flutter Documentation](https://flutter.dev/docs)
