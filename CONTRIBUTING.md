# Contributing to Flutter Riverpod Skill

Thanks for interest. This doc = guidelines for contributing.

## How to Contribute

### Reporting Issues

- **Bug reports**: Open issue. Clear description, repro steps, expected vs actual.
- **Feature requests**: Open issue describing new pattern/feature wanted.
- **Documentation improvements**: PRs for typos, clarifications, new examples welcome.

### Pull Requests

1. **Fork** repo
2. **Create branch** (`git checkout -b feature/add-new-pattern`)
3. **Make changes** per guidelines below
4. **Test** with Claude Code, Cursor, or other agent
5. **Submit PR** with clear description

## Guidelines

### Documentation Style

- Clear, concise language
- **MUST/NEVER/ALWAYS** enforcement for rules — every reference file MUST have `## Rules — NEVER Violate` section at top
- Mermaid diagrams over prose where fit
- Include working Dart/Flutter examples
- Follow existing formatting
- Keep SKILL.md under 500 lines; detailed content goes in `references/`

### Code Examples

```dart
// Include language identifier
// Use Riverpod 3.x codegen syntax (@riverpod, @Riverpod)
// Use Freezed 3.x sealed class syntax
// Follow architecture guidelines (data/domain/repositories/presentation)
```

### Package Versions

Targets:
- `flutter_riverpod: 3.2.1+`
- `freezed: 3.2.5+`
- `go_router: 17.1.0+`

Examples must work with these versions.

### File Structure

- `SKILL.md` - Main skill file (overview, critical rules, quick reference)
- `references/` - Detailed topic docs
- `README.md` - GitHub-facing docs

### Commit Messages

- Present tense ("Add feature" not "Added feature")
- First line under 50 chars
- Reference issues when applicable (`Fixes #123`)

## Code of Conduct

Be respectful, inclusive, constructive. All here to improve AI-assisted dev.

## Questions?

Open issue or start discussion. Happy to help.