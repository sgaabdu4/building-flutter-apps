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
- Keep `skills/building-flutter-apps/SKILL.md` under 500 lines; detailed content goes in its sibling `references/`
- Run analyzer with `skills/building-flutter-apps/references/analysis_options.yaml`
- For package/version reviews, verify the documented install path exactly. Analyzer plugins in top-level `plugins:` are not the same as `pubspec.yaml` dependencies.
- Run `ruby tool/check_upstream_flutter_skills.rb` before broad Flutter docs updates. If it flags upstream skill changes, review the changed upstream skill(s) before editing this repo. After adopting or intentionally ignoring those changes, refresh the lock with `ruby tool/check_upstream_flutter_skills.rb --update`.

### Code Examples

```dart
// Include language identifier
// Use Riverpod 3.x codegen syntax (@riverpod, @Riverpod)
// Use Freezed 3.x sealed class syntax
// Follow architecture guidelines (data/domain/repositories/presentation)
```

Run `ruby tool/verify_markdown_examples.rb` before PR. Dart code belongs in `dart` fences, including examples marked `// WRONG`.

Run `python3 tool/check_skill_routing.py` after changing `SKILL.md`, references, or routing evals. Every reference must be linked directly from `SKILL.md` and include `## Read first`.

### Package Versions

`skills/building-flutter-apps/references/core-stack.md` = **SSOT** for package
constraints. Per-reference setup blocks use placeholders and link to that file.
PRs with version pins elsewhere are rejected by the drift check.

Examples MUST work w/ constraints in `skills/building-flutter-apps/references/core-stack.md`. Don't upgrade
analyzer-bound generators (`json_serializable`, `hive_ce_generator`) alone.
Verify full solver: `dart pub deps -s compact | rg analyzer`.

### File Structure

- `skills/building-flutter-apps/SKILL.md` - Main skill file (overview, critical rules, quick reference)
- `skills/building-flutter-apps/references/` - Detailed topic docs
- `README.md` - GitHub-facing docs

### Commit Messages

- Present tense ("Add feature" not "Added feature")
- First line under 50 chars
- Reference issues when applicable (`Fixes #123`)

## Code of Conduct

Be respectful, inclusive, constructive. All here to improve AI-assisted dev.

## Questions?

Open issue or start discussion. Happy to help.
