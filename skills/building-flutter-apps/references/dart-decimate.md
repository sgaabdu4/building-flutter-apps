# Dart Decimate

## Read first

- Runtime owner = `deterministic-checks`; guidance owner = this reference.
- Package root = requested `pubspec.yaml`; Git root = scan owner.
- Every project → `npx --yes dart-decimate@latest json <git-root>`.
- Nested package → Git-root execution + exact repo-relative workspace scope.
- Affected Git root = one Dart Decimate process; per-package full-repository rescans forbidden.
- Project-local adapter/binary/copy under `tool/` = forbidden.
- Changed/base/baseline/audit modes + inherited finding exceptions = forbidden.
- Finding outside workspace → tooling-scope `FAIL`; never edit unrelated code.
- Dart Decimate + `dart analyze` = complementary required gates.
- Finding → inspect within same workspace → fix owner → rerun exact gate.
- Nonzero exit or any finding = `FAIL`; auto-fix = preview until mutation approval.

## Git pre-push

- Existing hook → preserve + invoke the canonical `deterministic-checks` project gate.
- Missing hook → install only the canonical dispatcher/delegation; preserve `core.hooksPath`.
- Hook Git calls → strip inherited `git rev-parse --local-env-vars`.
- Gate command → direct `npx --yes dart-decimate@latest`; no repository-local wrapper.
