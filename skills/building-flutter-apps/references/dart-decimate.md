# Dart Decimate

## Read first

- Owner = `$deterministic-checks` Dart Decimate wrapper + reference.
- Package root = requested `pubspec.yaml`; Git root = diff attribution.
- Existing project → wrapper `--package <package-root> --base <base>`.
- New/no-base project → wrapper `--package <package-root> --full`.
- Nested package → Git-root execution + exact repo-relative workspace scope.
- Finding outside workspace → tooling-scope `FAIL`; never edit unrelated code.
- Dart Decimate + `dart analyze` = complementary required gates.
- Finding → inspect within same workspace → fix owner → rerun exact gate.
- Exit `1|2|8` = `FAIL`; auto-fix = preview until mutation approval.

## Git pre-push

- Template = [dart_decimate_pre_push.sh](../templates/flutter/tool/dart_decimate_pre_push.sh).
- Existing hook → preserve + invoke template with `"$@"`.
- Missing hook → install through current hook owner; preserve `core.hooksPath`.
