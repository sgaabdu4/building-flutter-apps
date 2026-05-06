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
- Use **MUST/NEVER/ALWAYS** only for enforceable rules
- Mermaid diagrams over prose where fit
- Include working Dart/Flutter examples
- Follow existing formatting
- Keep SKILL.md under 500 lines; detailed content goes in `references/`
- Run analyzer with `references/analysis_options.yaml`
- For package/version reviews, verify the documented install path exactly. Analyzer plugins in top-level `plugins:` are not the same as `pubspec.yaml` dependencies.

### Code Examples

```dart
// Include language identifier
// Use Riverpod 3.x codegen syntax (@riverpod, @Riverpod)
// Use Freezed 3.x sealed class syntax
// Follow architecture guidelines (data/domain/repositories/presentation)
```

Run `ruby tool/verify_markdown_examples.rb` before PR. Dart code belongs in `dart` fences, including examples marked `// WRONG`.

### Package Versions

Targets:
- `flutter_riverpod: 3.3.1+`
- `riverpod_annotation: 4.0.2+`
- `riverpod_generator: 4.0.3+`
- `freezed: 3.2.5+`
- `go_router: 17.2.3+`
- `go_router_builder: 4.3.0+`
- `json_annotation: ^4.11.0`
- `json_serializable: 6.13.0`
- `hive_ce_generator: 1.11.0`

Examples must work with these versions. Do not upgrade analyzer-bound generators independently; verify the full solver set first.

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
