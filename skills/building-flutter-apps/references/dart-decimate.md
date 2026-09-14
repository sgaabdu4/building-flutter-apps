# Dart Decimate

## Read first

- Runtime owner = the project; guidance owner = this reference.
- Package root = requested `pubspec.yaml`; run a standalone scan from its Git root.
- Hard Eng install → `python3 .hooks/hard-eng.py check`; its configured native check owns scope and report validation.
- Another project → use its established Dart Decimate check. If it has none, run `npx --yes dart-decimate@latest check . --threshold 0 --format json` from its Git root.
- The project workflow schedules its integrated check; reuse a valid same-scope result instead of launching another full runner after a focused edit check.
- Do not add a wrapper, dependency, binary copy, package-root `tool/` bundle, or global coordinator solely for this skill.
- Dart Decimate + `dart analyze` = complementary required gates.
- A finding or nonzero exit is a failure: inspect within the requested workspace, fix its owner, and rerun the exact gate. Auto-fix remains preview-only until mutation approval.

## Git pre-push

- Existing project hook or gate → preserve its owner and run its established check.
- This skill does not install, replace, or require a Git hook, and it does not change `core.hooksPath`.
- For a project without an established check, run the standalone native command above before push.
