# Windows Installer Pipeline

## Read first

1. Scope = Flutter Windows EXE + Inno Setup/`inno_bundle` + updater + GitHub Actions delivery.
2. Current contract = installed package/tool/action + primary docs/changelog + resolved runner paths; memory + cached/local success = no proof.
3. Entry = secret-free manual Windows diagnostic for one exact SHA; publish only that proven SHA with one release actor.
4. Copy scaffold = [windows-installer-workflow.yml](../assets/windows-installer-workflow.yml) + [Inno settlement sentinel](../assets/inno-uninstall-settlement-sentinel.ps1); replace repository-owned commands + audit every action/tool pin before first run.
5. Provider boundary = artifact store/index/pointer are interfaces; keep provider names, endpoints, project IDs, PII, and credentials outside this skill/package.

## Contents

- [Flow](#flow)
- [Clean runner](#clean-runner)
- [Windows native bundle](#windows-native-bundle)
- [Inno ownership](#inno-ownership)
- [Installer identity](#installer-identity)
- [Install lifecycle](#install-lifecycle)
- [Bounded processes](#bounded-processes)
- [Updater behavior](#updater-behavior)
- [Security](#security)
- [Publication](#publication)
- [Proof](#proof)
- [Sources](#sources)

## Flow

1. Research = resolve Flutter/Dart/Node/actions/Inno/`inno_bundle` versions + official source + hashes/signatures where supplied.
2. Contract = inventory last green step order + generated outputs + runtime DLLs + installer identity + data-preservation policy + publication interfaces.
3. Cheap proof = YAML/shell/PowerShell syntax + tool identity + CRT sentinel + tiny Inno identity/install/uninstall settlement sentinels + timeout regression fixtures.
4. Diagnostic = one `workflow_dispatch` + one `windows-latest` job + exact SHA + no publisher secrets/writes.
5. Diagnostic artifact = upload installer + machine receipt only after every check passes; short retention; publication = `none`.
6. Publisher = one full run for diagnostic-proven SHA; quality/preparation may parallelize, native/external mutations remain sequential.
7. Delivery = immutable installer/manifest upload → independent download/readback → pointer/index update last → final remote receipt.

- Verification permissions = `contents: read` + `actions: read` only when run/readback needs it.
- Verification exclusions = tags + releases + deployments + pointer/index writes + machine installation + signing/publisher secrets.
- Verification mode = skip Linux quality/preparation/publication jobs.
- Release actor = one per repository + target + environment + revision; concurrency cancels no in-flight publisher.
- Cache = acceleration only; delete/disable cache and retain correctness.

## Clean runner

- Every Windows consumer = `flutter pub get` → source-changing version materialization → `dart run build_runner build` → `flutter gen-l10n` when configured → analyze/test → `flutter build windows --release`.
- Generated output = tracked OR generated in consumer OR transferred as explicit hash/provenance-verified artifact.
- Ubuntu-generated ignored output without transfer = absent on Windows.
- `build_runner` command = installed help + official changelog; current supported build command has no conflict-output flag.
- Forbidden = `-d` + `--delete-conflicting-output` + `--delete-conflicting-outputs`.
- Version materialization = capture tracked paths immediately before/after + allow exact intended delta only.
- Whole-workspace-clean assertion after setup/codegen = invalid; caches + ignored generation are expected.
- Exact-tip read with `persist-credentials: false` = explicitly authenticate job-scoped read-only `github.token`.
- Paid retry = previous failure classified + adjacent assumptions audited + cheapest failing sentinel green first.

## Windows native bundle

- Build = `flutter build windows --release` on `windows-latest`.
- Resolve release directory + primary EXE from produced build graph; guessed legacy path = no proof.
- Bundle = EXE + Flutter/plugin DLLs + `data/` + accepted Visual C++ runtime strategy.
- App-local CRT source = Visual Studio installation resolved with `vswhere` + `VCToolsRedistDir`.
- Required x64 set = `msvcp140.dll` + `vcruntime140.dll` + `vcruntime140_1.dll`.
- Each CRT = exactly one source + PE `MZ`/`PE` + machine `0x8664` + copied destination + source/destination SHA-256 equality.
- Forbidden CRT proof = opportunistic System32 copy + optional/missing-tolerated file + compiler presence alone.
- Native API = include `<windows.h>` before `<shellapi.h>` for `CommandLineToArgvW`; link `Shell32.lib`.
- Native diagnosis = declaration/header order + include directories + link libraries + runtime bundle; one layer cannot prove another.

## PowerShell

- Syntax gate = compatible Windows `pwsh` + `[System.Management.Automation.Language.Parser]::ParseFile(...)` over every owned `.ps1`; any parse error fails before tool install/build.
- Syntax scope = parser owner + cheap smokes + installer harness + every called helper; regex/static intent review is not a parser.
- Smoke integrity = syntax gate first → intentional timeout smoke second; a smoke with unparsed syntax proves nothing.
- Generated source = literal single-quoted content + dynamic paths/values as named arguments; nested expandable PowerShell source = forbidden.
- Generated proof = materialize → parse exact output → execute harmless readiness path under compatible `pwsh` with a bounded receipt before CI/build.
- Filename suffix = compute in one scope + pass as an argument; if interpolation is unavoidable, use `${childPidPath}.tmp` or `$($childPidPath).tmp`, never `$childPidPath.tmp`.
- Numeric conversion = validate range + multiply in a wide numeric type + bounds-check + explicit target cast; `[checked]` is not a PowerShell type accelerator.
- Uncertain command/cmdlet/pipeline result = `@(...)` before `.Count`, `[0]`, exact-one, or comparison.
- Selected scalar = explicit `[string]` conversion before string APIs.
- Cardinality fixture = zero + one + many.
- Native output = capture array + immediate `$LASTEXITCODE` + normalize to one string before regex.
- Process arguments = executable + token array; shell-concatenated command string = avoid.
- Tool path = uniquely resolved absolute path; Program Files guess = forbidden.
- Ephemeral root = unique `RUNNER_TEMP` child + owner marker + exact-root cleanup guard.

## Inno ownership

- `inno_bundle` = candidate generator, not distribution proof.
- Audit installed version = generated `.iss` + AppId + upgrade behavior + file layout + DLL sources + compiler selection + version resources + signing hooks.
- Use package directly only when generated contract covers accepted requirements.
- Extend least surface; retain custom `.iss`/scripts when preservation, rollback, relaunch, publication, or identity requirements exceed package behavior.
- Stable AppId = immutable across releases + in-place install directory.
- Update = never delete application data, sibling user paths, credentials, or unknown files.
- Inno compiler = audited exact version + resolved `ISCC.exe` + cheap distinct-version sentinel + compile exit `0`.
- Tiny identity sentinel = distinct numeric version + textual version; compile/read fields before expensive Flutter build.
- Tiny lifecycle sentinel = unique temp root + synthetic stable test AppId → install → invoke uninstaller once → bounded settlement of exact install directory + AppId uninstall key; run before expensive Flutter build.

## Installer identity

- Filename = `<app>-windows-installer-v<version>.exe`.
- File = exact expected name + accepted size bounds + `MZ` + SHA-256.
- Product identity = ProductName + FileDescription + stable AppId.
- Numeric fields = `VersionInfoVersion` + `VersionInfoProductVersion`; compare four integer parts independently.
- Text field = `VersionInfoProductTextVersion`; trim only observed textual boundary padding before equality.
- Diagnostic = exact failed field + expected value + safe observed value/length/hash.
- Opaque aggregate identity exception = forbidden.
- Signature required by accepted delivery policy = verify chain + subject/thumbprint policy + timestamp before publication.

## Install lifecycle

### First release

- Previous-release lookup = authoritative published index/pointer + immutable retrievable installer + signed manifest/hash.
- No authoritative prior release = do not synthesize, wait, rebuild old source, or use current-source/expired Actions artifacts.
- Resolver mode = `none`; old-installer path = absent.
- Receipt = `phase=prior-release result=skipped_no_prior_release`.
- Required proof = bounded clean install + forced-failure cleanup + relaunch + uninstall + no application/user-data deletion.

### Upgrade release

- Release two onward = exact previous published installer/manifest is mandatory.
- Resolver mode = `managed`; old-installer path = exact verified publication object.
- Baseline identity = independently download + verify manifest signature + installer hash/signature/version before execution.
- Required proof = old install → seed accepted local state → failed new install restores old program/data → successful new install preserves state + relaunches → uninstall removes owned program/registration only.
- Previous artifact = immutable publication object or equivalent authoritative release asset; current build + locally rebuilt tag + expired diagnostic artifact = forbidden surrogate.
- Actions handoff = same-run transport only after authoritative verification; verify its digest again after download.
- Harness refuses pre-existing unrelated installation; fixture data/credentials = synthetic + namespaced.
- Cleanup = owned processes + owned install + owned registry + owned temp markers only.

### Forced-failure proof

- Test-only failure = establish owned backup/recovery state → `PrepareToInstall` returns a non-empty diagnostic.
- Expected installer result = exact exit code `7`; exit `0` = false failure proof + immediate stop.
- Cleanup/restore = `DeinitializeSetup`; it runs even when Setup exits before installation.
- Assert = installer exit + prior program bytes + accepted local state + no partial new version + owned cleanup.
- Forbidden = raise from `[Files]` `AfterInstall` + assume `/SUPPRESSMSGBOXES` makes the file error fatal/nonzero.
- Different Inno version/trigger = reverify official event + exit-code contract before use.

### Uninstall settlement

- Exit `0` = original uninstaller completed; its temporary cleanup clone may still be running.
- Invocation = launch the exact owned uninstaller once; after exit `0`, never invoke its vanishing path again.
- Settlement = bounded poll until both exact install directory + exact AppId uninstall registry key are absent in every declared root/view.
- Ownership = retain installation/cleanup state until settlement passes or times out; no second uninstaller fallback.
- Timeout receipt = unresolved directory/key condition + elapsed/deadline + safe process state; bounded owned cleanup only.
- Data contract = settlement targets installed program/registration only; accepted application/user data remains preserved.

## Bounded processes

- Whole-job timeout = outer failsafe only; every child phase owns a smaller explicit deadline.
- Phases = baseline install + forced-failure install + rollback observation + new install + updater launch + relaunch observation + uninstall process + uninstall settlement.
- Receipt = `phase=<name> result=started|completed|timeout|cleanup-timeout` + deadline/exit details.
- Start = emit phase + deadline + safe command identity + PID receipt.
- Wait = finite process wait; `Start-Process -Wait` + `WaitForSingleObject(..., INFINITE)` forbidden.
- Timeout = emit phase + elapsed + PID/alive/exit state → terminate exact owned process tree → bounded cleanup → fail immediately.
- PowerShell owner = `Start-Process -PassThru` + finite `WaitForExit(milliseconds)`/bounded polling + exact-tree termination on timeout or failed installer.
- Native owner = `WaitForSingleObject(handle, timeout_ms)` + separate parent/installer `WAIT_TIMEOUT` exits + closed handles.
- Regression sentinel = child intentionally exceeds deadline → gate exits within bound + names phase + kills descendant + leaves no owned artifact/process.
- Nested deadlines = child phase + cleanup headroom < job deadline.

## Updater behavior

- Surface = small muted warning/error-color banner + Settings indicator.
- Actions = `Download and install` + `Later`.
- Reminder = once after 24 hours; no tight polling/nag loop.
- Mandatory = security-critical or explicitly owner-marked important only; normal release remains deferrable.
- Install = download → verify manifest signature + installer SHA/signature → flush local state → close app → bounded helper/installer → verify installed version → relaunch.
- Unsupported platform/storage = fail closed.
- Provider choice = project-owned; UI/domain depends on manifest/download interfaces, not vendor SDK.

## Security

- Bundle/log/artifact = no embedded API keys, credentials, private signing keys, publisher tokens, or PII.
- Client-visible telemetry destination, when accepted, follows [error-reporting.md](error-reporting.md); upload tokens remain build-only.
- Scan = current tracked tree + built bundle + extracted installer.
- Defender = scan final installer + fail on matching detections.
- Credential-store behavior, when used = synthetic round-trip + unsupported-platform fail-closed proof.
- Verification lane = no signing/publisher secret environment or arguments.
- Logs/receipts = hashes + versions + safe field diagnostics; never secret values.

## Publication

- Version/tag materialization = after exact-tree gates + before consuming codegen/native build.
- Build/sign = installer + signed manifest bound to exact source SHA/version/hash/size/classification.
- Immutable upload = versioned installer + manifest; collision accepted only when downloaded bytes match.
- Readback = independent download + installer identity/hash/signature + manifest signature/payload.
- Pointer/index activation = last external mutation after every immutable object readback passes.
- Final readback = active pointer/index + immutable objects + exact version/tag/SHA.
- Failure before activation = previous pointer unchanged.
- Actions artifact = short-lived evidence or same-run transport of an already verified publication object; never previous-release authority or independent publication/readback proof.
- Provider adapter = preflight candidate write/read/delete + idempotency + permissions + atomicity/ordering contract before release.

## Proof

- Diagnostic receipt = source SHA + resolved tools + generated-source proof + EXE/CRT identity + installer identity/hash/signature + secret/Defender scans + lifecycle branch/results + phase receipts + `publication=none`.
- Publisher receipt = diagnostic run/SHA + required jobs/steps + version/tag + immutable object IDs/hashes + downloaded verification + pointer/index readback + absent unintended release/deployment/install.
- Remote PASS = exact required job + named step green; workflow-level green alone = insufficient.
- Active repair/retry = report nonterminal; never claim current workflow green before exact run receipt.

## Sources

- [Dart build_runner](https://dart.dev/tools/build_runner)
- [build_runner changelog](https://pub.dev/packages/build_runner/changelog)
- [Flutter Windows distribution](https://docs.flutter.dev/platform-integration/windows/building)
- [GitHub workflow syntax and permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [GitHub token](https://docs.github.com/en/actions/concepts/security/github_token)
- [PowerShell Start-Process](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/start-process)
- [PowerShell Wait-Process](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/wait-process)
- [PowerShell `Parser.ParseFile`](https://learn.microsoft.com/en-us/dotnet/api/system.management.automation.language.parser.parsefile?view=powershellsdk-7.6.0)
- [PowerShell numeric literals + type accelerators](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_numeric_literals?view=powershell-7.5)
- [PowerShell quoting + expandable strings](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_quoting_rules?view=powershell-7.6)
- [Visual Studio `vswhere`](https://github.com/microsoft/vswhere)
- [Inno Setup AppId](https://jrsoftware.org/ishelp/topic_setup_appid.htm)
- [Inno Setup uninstaller exit codes](https://jrsoftware.org/ishelp/topic_uninstexitcodes.htm)
- [Inno Setup event functions](https://jrsoftware.org/ishelp/topic_scriptevents.htm)
- [Inno Setup exit codes](https://jrsoftware.org/ishelp/topic_setupexitcodes.htm)
- [Inno Setup command-line parameters](https://jrsoftware.org/ishelp/topic_setupcmdline.htm)
- [Inno command-line compiler](https://jrsoftware.org/ishelp/topic_compilercmdline.htm)
- [Inno binary file version](https://jrsoftware.org/ishelp/topic_setup_versioninfoversion.htm)
- [Inno binary product version](https://jrsoftware.org/ishelp/topic_setup_versioninfoproductversion.htm)
- [Inno textual product version](https://jrsoftware.org/ishelp/topic_setup_versioninfoproducttextversion.htm)
- [`inno_bundle`](https://pub.dev/packages/inno_bundle)
- [Win32 `CommandLineToArgvW`](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-commandlinetoargvw)
- [Win32 `WaitForSingleObject`](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject)
