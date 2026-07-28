# Dart Decimate

## Read first

- Owner = bundled Dart Decimate adapter + this reference.
- Package root = requested `pubspec.yaml`; Git root = diff attribution.
- Existing project → wrapper `--package <package-root> --base <base>`.
- New/no-base project → wrapper `--package <package-root> --full`.
- Nested package → Git-root execution + exact repo-relative workspace scope.
- Finding outside workspace → tooling-scope `FAIL`; never edit unrelated code.
- Dart Decimate + `dart analyze` = complementary required gates.
- Finding → inspect within same workspace → fix owner → rerun exact gate.
- Exit `1|2|8` = `FAIL`; auto-fix = preview until mutation approval.

## Git pre-push

- Bundle = [dart_decimate_pre_push.sh](../templates/flutter/tool/dart_decimate_pre_push.sh) + sibling `dart_decimate_gate.py` + `git_env.py`.
- Existing hook → preserve + invoke template with `"$@"`.
- Missing hook → copy the complete bundle into package-root `tool/` + install through current hook owner; preserve `core.hooksPath`.
