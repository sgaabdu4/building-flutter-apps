# Build Reproducibility

## Read first

1. External contract = installed version + official primary docs; memory + cached runner state = no proof.
2. Build proof = tracked-only clean checkout on the target OS; developer cache + ignored outputs = no proof.
3. Workflow replacement = preserve every applicable step from the last green path + assert step presence/order per consuming lane.
4. Windows installer/updater work = read the directly routed `windows-installer-pipeline.md`; this reference owns cross-platform build reproducibility only.

## Generated source

- Discover owners = `pubspec.yaml` + lockfile + `build.yaml` + `l10n.yaml` + `part` directives + `.gitignore`.
- Classify each output = tracked | ignored | generated in lane; `git diff` cannot prove ignored output completeness.
- Clean proof = ephemeral clone/archive containing tracked files only.
- Required order per consuming lane:
  1. resolve pinned Flutter/Dart + dependencies;
  2. apply source-changing version materialization;
  3. `dart run build_runner build`;
  4. `flutter gen-l10n` when configured;
  5. package-root analyze/test;
  6. target-native build.
- Current command SSOT = [Core Stack](core-stack.md); active `-d` + `--delete-conflicting-output` + `--delete-conflicting-outputs` commands are forbidden.
- Codegen in another job = unavailable unless outputs are tracked or transferred as an explicit verified artifact.
- Regression proof = clean checkout starts without ignored outputs → generation materializes expected owners → analyze + target build pass.

## Workflow migration

- Before edit = inventory last green workflow: checkout/auth → toolchain → dependency restore → version materialization → codegen → native build → runtime bundle → installer → scans → preservation → artifact/publish.
- After edit = map every retained/replaced step to each diagnostic + production lane.
- Contract = fail when an applicable step is absent, duplicated, reordered across its dependency, or moved to a job without output transfer.
- Prerequisite failure = cancel downstream paid work; no concurrent duplicate retry.
- Independent cheap preparation/gates = parallel; dependent/native/external mutation = sequential.

## Apple boundary

- Toolchain identity = resolved `DEVELOPER_DIR`/`xcode-select` path + Xcode build + Flutter/Dart version before any native generation/build command.
- Flutter SwiftPM integration = generated package target + `Run Prepare Flutter Framework Script` pre-action + exact flavor scheme; project migration bytes are tracked, `ios/Flutter/ephemeral/` bytes are generated.
- Command that rewrites generated Apple package metadata = isolate + verify post-command package products; regenerate immediately before device build/run under the same resolved Xcode environment.
- Device proof = same flavor/entrypoint/toolchain that produced the native package graph; a prior IDE cache or different Xcode selection = no proof.
- Tracked Xcode project change vs generated build side effect = classify before restore; never restore/commit one as the other.

## Platform golden

- Platform golden = strict OS-specific baseline + actual-media review; tolerance relaxation cannot hide rasterization drift.

## Sources

- [Dart build_runner](https://dart.dev/tools/build_runner)
- [build_runner changelog](https://pub.dev/packages/build_runner/changelog)
- [Flutter Swift Package Manager](https://docs.flutter.dev/packages-and-plugins/swift-package-manager/for-app-developers)
- [Flutter iOS toolchain setup](https://docs.flutter.dev/platform-integration/ios/setup)
