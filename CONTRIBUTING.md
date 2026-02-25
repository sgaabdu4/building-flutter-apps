# Contributing to Flutter Riverpod Skill

Thank you for your interest in contributing! This document provides guidelines for contributing to this skill.

## How to Contribute

### Reporting Issues

- **Bug reports**: Open an issue with a clear description, steps to reproduce, and expected vs actual behavior
- **Feature requests**: Open an issue describing the new pattern or feature you'd like to see
- **Documentation improvements**: PRs for typos, clarifications, or new examples are always welcome

### Pull Requests

1. **Fork** the repository
2. **Create a branch** for your changes (`git checkout -b feature/add-new-pattern`)
3. **Make your changes** following the guidelines below
4. **Test** your changes work with Claude Code, Cursor, or another agent
5. **Submit a PR** with a clear description of your changes

## Guidelines

### Documentation Style

- Use clear, concise language
- Include working Dart/Flutter code examples
- Follow existing formatting patterns
- Keep SKILL.md under 500 lines; add detailed content to `references/`

### Code Examples

```dart
// Include language identifier
// Use Riverpod 3.x codegen syntax (@riverpod, @Riverpod)
// Use Freezed 3.x sealed class syntax
// Follow architecture guidelines (data/domain/repositories/presentation)
```

### Package Versions

This skill targets:
- `flutter_riverpod: 3.2.1+`
- `freezed: 3.2.5+`
- `go_router: 17.1.0+`

Ensure examples are compatible with these versions.

### File Structure

- `SKILL.md` - Main skill file (overview, critical rules, quick reference)
- `references/` - Detailed documentation on specific topics
- `README.md` - GitHub-facing documentation

### Commit Messages

- Use present tense ("Add feature" not "Added feature")
- Keep first line under 50 characters
- Reference issues when applicable (`Fixes #123`)

## Code of Conduct

Be respectful, inclusive, and constructive. We're all here to improve AI-assisted development.

## Questions?

Open an issue or start a discussion. We're happy to help!
