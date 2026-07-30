# Build Reproducibility

## Read first

1. External contract = installed version + official primary docs; memory + cached runner state = no proof.
2. Build proof = tracked-only clean checkout on the target OS; developer cache + ignored outputs = no proof.
3. Workflow replacement = preserve every applicable step from the last green path + assert step presence/order per consuming lane.
4. Paid/mutating run = local syntax/contracts green + Windows-only nonpublishing diagnostic green first.

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
- Current command SSOT = [Core Stack](core-stack.md); `-d` + `--delete-conflicting-output` + `--delete-conflicting-outputs` forbidden.
- Codegen in another job = unavailable unless outputs are tracked or transferred as an explicit verified artifact.
- Regression proof = clean checkout starts without ignored outputs → generation materializes expected owners → analyze + target build pass.

## Workflow migration

- Before edit = inventory last green workflow: checkout/auth → toolchain → dependency restore → version materialization → codegen → native build → runtime bundle → installer → scans → preservation → artifact/publish.
- After edit = map every retained/replaced step to each diagnostic + production lane.
- Contract = fail when an applicable step is absent, duplicated, reordered across its dependency, or moved to a job without output transfer.
- Prerequisite failure = cancel downstream paid work; no concurrent duplicate retry.
- Independent cheap preparation/gates = parallel; dependent/native/external mutation = sequential.
- Windows build count = one per candidate; reuse only a provenance/hash/identity-verified rollback installer.

## Windows boundary

- Runner image/tool label = record resolved OS + architecture + Flutter/Dart + Visual Studio + Inno versions.
- Tool bootstrap = pinned source + hash/signature when supplied + unique `RUNNER_TEMP` root + resolved absolute executable path.
- Program Files/path guess = forbidden; spaces + quoting fixture required.
- PowerShell native command = executable + token array; capture immediate exit.
- GUI/bootstrap process = `Start-Process -Wait -PassThru`; gate `ExitCode`.
- Native output used as text = normalize first, for example `($lines -join "`n")`; array regex truthiness = forbidden.
- PowerShell cardinality = wrap uncertain pipeline/cmdlet output in `@(...)` before `.Count`, indexing, or exact-one checks; zero/one/many fixtures required.
- Private-repository read = job-scoped `github.token`/`GITHUB_TOKEN` + least `contents: read`; `persist-credentials: false` means later Git network reads need explicit authentication.
- Workspace invariant = compare immediate before/after tracked-path delta for the operation; post-setup whole-workspace-clean assertion = forbidden.

## Apple boundary

- Toolchain identity = resolved `DEVELOPER_DIR`/`xcode-select` path + Xcode build + Flutter/Dart version before any native generation/build command.
- Flutter SwiftPM integration = generated package target + `Run Prepare Flutter Framework Script` pre-action + exact flavor scheme; project migration bytes are tracked, `ios/Flutter/ephemeral/` bytes are generated.
- Command that rewrites generated Apple package metadata = isolate + verify post-command package products; regenerate immediately before device build/run under the same resolved Xcode environment.
- Device proof = same flavor/entrypoint/toolchain that produced the native package graph; a prior IDE cache or different Xcode selection = no proof.
- Tracked Xcode project change vs generated build side effect = classify before restore; never restore/commit one as the other.

## Native + installer

- C/C++ diagnosis = header declaration + include order + `target_include_directories` + `target_link_libraries` + runtime DLL bundle; one layer cannot prove another.
- Windows-native compile = required for runner/FFI/plugin changes; macOS/Linux analysis cannot replace it.
- Flutter release bundle = EXE + adjacent plugin/runtime DLLs + `data/` + chosen Visual C++ runtime strategy.
- Runtime staging = discover the resolved release output + assert exact DLL set beside the EXE; a compiler/runtime install does not prove packaged CRT availability.
- Inno compiler = exact version + official directive set + `ISCC.exe` exit `0` + expected output identity.
- Installer continuity = stable `AppId` + numeric executable version fields + display version kept separate.
- Installer verifier = field-by-field diagnostics; compare binary numeric versions separately from textual version fields; normalize documented/observed boundary whitespace before text equality.
- Opaque aggregate identity exception = forbidden; failure names exact field + expected identity + safe observed length/hash so the next retry has one proven cause.
- Upgrade/preservation fixture = pre-existing user paths allowed + namespaced owned markers + preimage hashes + cleanup only owned markers.
- Forced-failure proof = old install/data remains intact; normal upgrade + relaunch + uninstall behavior pass.

## Diagnostic + release

- Nonpublishing diagnostic = Windows target + no write permissions/secrets + no cache/artifact/release/deploy/upload + temporary local outputs only.
- Platform golden = strict OS-specific baseline + actual-media review; tolerance relaxation cannot hide rasterization drift.
- Publisher = one actor per repo + environment + revision; exact revision/readback required.
- Remote PASS = required job + named codegen/native/installer/preservation steps green for delivered SHA; workflow-level green alone = insufficient.

## Sources

- [Dart build_runner](https://dart.dev/tools/build_runner)
- [build_runner changelog](https://pub.dev/packages/build_runner/changelog)
- [Flutter Windows distribution](https://docs.flutter.dev/platform-integration/windows/building)
- [Flutter Swift Package Manager](https://docs.flutter.dev/packages-and-plugins/swift-package-manager/for-app-developers)
- [Flutter iOS toolchain setup](https://docs.flutter.dev/platform-integration/ios/setup)
- [PowerShell Start-Process](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/start-process)
- [GitHub GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token)
- [actions/checkout](https://github.com/actions/checkout)
- [Inno command-line compiler](https://jrsoftware.org/ishelp/topic_compilercmdline.htm)
- [Inno binary file version](https://jrsoftware.org/ishelp/topic_setup_versioninfoversion.htm)
- [Inno binary product version](https://jrsoftware.org/ishelp/topic_setup_versioninfoproductversion.htm)
- [Inno textual product version](https://jrsoftware.org/ishelp/topic_setup_versioninfoproducttextversion.htm)
- [Win32 CommandLineToArgvW](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-commandlinetoargvw)
