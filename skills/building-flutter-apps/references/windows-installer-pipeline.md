# Windows Installer Pipeline

## Read first

1. Scope = Flutter Windows EXE + Inno Setup/`inno_bundle` + updater + GitHub Actions delivery.
2. Current contract = installed package/tool/action + primary docs/changelog + resolved runner paths; memory + cached/local success = no proof.
3. Entry = secret-free manual Windows diagnostic for one exact SHA; publish only that proven SHA with one release actor.
4. Copy scaffold = [windows-installer-workflow.yml](../assets/windows-installer-workflow.yml) + [`inno_bundle` pubspec fragment](../assets/inno-bundle-pubspec.yaml) + [Inno settlement sentinel](../assets/inno-uninstall-settlement-sentinel.ps1) + [Defender scanner](../assets/defender-installer-scan.ps1); replace repository-owned commands + audit every action/tool pin before first run.
5. Provider boundary = artifact store/index/pointer are interfaces; keep provider names, endpoints, project IDs, PII, and credentials outside this skill/package.
6. Audited scaffold baseline (2026-08-01) = `inno_bundle 0.11.2` + Inno Setup `7.0.2` + `actions/checkout 7.0.1` + `actions/upload-artifact 7.0.1` + `actions/download-artifact 8.0.1`; re-resolve primary releases before first dispatch and update pins + contracts together when newer.

## Contents

- [Flow](#flow)
- [Cross-app adaptation](#cross-app-adaptation)
- [Cost-aware proof ladder](#cost-aware-proof-ladder)
- [Clean runner](#clean-runner)
- [Windows native bundle](#windows-native-bundle)
- [`inno_bundle` setup](#inno_bundle-setup)
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
3. Cheap proof = local portable syntax/unit/static/crypto tests + one Linux provider preflight.
4. Diagnostic = exact SHA + same repository-owned Windows orchestration on a clean native x64 Windows VM or repository-scoped ephemeral/JIT x64 runner + no publisher secrets/writes.
5. Diagnostic artifact = upload installer + machine receipt only after every check passes; short retention; publication = `none`.
6. Publisher = one GitHub-hosted Windows run for diagnostic-proven SHA; quality/preparation may parallelize, native/external mutations remain sequential.
7. Delivery = immutable installer/manifest upload → independent download/readback → pointer/index update last → final remote receipt.

- Dispatch selector = branch/tag containing the workflow; exact 40-character candidate SHA = separate input.
- Dispatch input validation = a no-checkout job receives raw values only through environment variables, then rejects everything outside the typed grammar before any checkout-local action or release script: `mode` is `verify-windows | publish`; `revision` is exactly 40 lowercase hexadecimal characters and equals `github.sha`; `version` is `MAJOR.MINOR.PATCH` with each component `0` or a non-zero decimal integer of at most nine digits; `diagnostic_run_id` is empty for verification or 1-20 decimal digits for publication.
- Release command boundary = validated outputs enter Bash and PowerShell through environment variables; no workflow-dispatch input is interpolated into command source. Artifact names and paths use only the validated version or provider run ID.
- Dispatch admission = event SHA equals candidate SHA + remote tip/tag readback equals candidate SHA before any paid/native/external phase.
- `gh workflow run --ref <sha>` = `FAIL`; workflow-dispatch `ref` selects a branch/tag, while `actions/checkout` `ref` may consume the admitted SHA.
- YAML surface = minimum runner + permission + cache + handoff + artifact + external-write boundaries.
- Ordered internal phases = repository-owned orchestration script + phase receipts; avoid one YAML step per command.
- Compacting = move calls, never remove guards; contract-test each required guard call + its order before the single expensive build.
- Shared YAML = boundary topology only; orchestration branches own same-job codegen vs verified transfer + first-release vs upgrade lifecycle.
- Branch contract = every accepted internal branch retains common syntax/timeout/CRT/Inno guards + one native build + identity/security/lifecycle proof + publication ordering.
- Cross-app engine = one semantic release stage DAG; app identity + provider values = validated typed configuration/adapters.
- Second-app admission = stage-by-stage parity map against one proven reference + real execution of every adapted branch before publish.
- Copy-pasted app-specific release engine + foreign project/object IDs = `FAIL`; justified schema differences stay explicit at typed adapter boundaries.
- Publisher minimum = read-only Linux admission + one GitHub-hosted Windows build/publisher; target-native diagnostic runs locally or on repository-scoped ephemeral/JIT self-hosted Windows.
- Duplicate Windows build, repeated tool setup, and visible step count without a permission/runner/artifact boundary = `FAIL`.
- Verification permissions = `contents: read` + `actions: read` only when run/readback needs it.
- Verification exclusions = tags + releases + deployments + pointer/index writes + machine installation + signing/publisher secrets.
- Verification mode = skip Linux quality/preparation/publication jobs.
- Release actor = one per repository + target + environment + revision; concurrency cancels no in-flight publisher.
- Cache = acceleration only; delete/disable cache and retain correctness.

## Cross-app adaptation

- Canonical standard = one semantic stage DAG + one orchestration implementation; byte identity is required only for files declared universal.
- Ownership classes = universal engine bytes | validated typed app config | explicit capability adapter | app-owned product/runtime/preservation code.
- Literal-copy manifest = universal files only + exact source revision/hash; app-owned tests, native targets, storage probes, and product IDs are excluded.
- Adaptation = copy universal bytes once → render typed config/adapters → reject every undeclared byte delta and every copied foreign identity/namespace.
- Blind repository-wide byte equality = `FAIL`; it can import nonexistent targets, incompatible schemas, foreign cleanup markers, or production-only behavior.
- Capability matrix = each optional guard/target/path is `required | unsupported`; omission without an explicit capability result = `FAIL`.
- Clean-target inventory = every configured script/test/file/native target exists and is executable/reachable in a tracked-only checkout before hosted admission.
- Test-path contract = enumerate intended paths from the target repository; copied paths that exist only in the reference repository = `FAIL`.
- Namespace = app identity/config derives installer AppId + artifact/object IDs + fixture roots + registry/data markers + cleanup diagnostics.
- Reference-app names/literals outside config fixtures = `FAIL`; cleanup and error receipts never use a foreign app marker.
- Parity proof = render two controlled app configs through the same engine → universal bytes/call graph stay equal + only allowlisted typed outputs differ.
- Real branch proof = first release + upgrade + generated-source mode + every accepted capability/provider adapter; static hash/call-presence parity alone = insufficient.

## Cost-aware proof ladder

1. Portable local = macOS/Linux syntax + unit + static contracts + deterministic crypto/signature fixtures; no Windows-native or live-provider claim.
2. Provider preflight = cheap Linux + official SDK + harmless exact-candidate format/size/protocol/security policy → owned temporary create + public read/hash + bounded delete settlement.
3. Target-native = same checked-in `windows_installer.ps1 verify` on a clean native x64 Windows VM OR repository-scoped ephemeral/JIT x64 Windows runner → one native build + complete installer/lifecycle/security receipt.
4. Hosted release = only after step 3 passes for the exact SHA → one GitHub-hosted Windows publisher + one native build inside that run + immutable activation proof.

- Failure cancels later paid work; retry only the smallest failed rung after root-cause + adjacent-assumption proof.
- `act` = portable wiring aid only; its container images are Linux-oriented + intentionally incomplete, and Windows/macOS labels require opting out to an actual matching host. `act` on macOS/Linux is not Windows target-native proof.
- Self-hosted Actions usage = no GitHub-hosted Actions minute charge; machine + image + updates + isolation + cleanup + logs remain operator-owned.
- Self-hosted security = private repository only + repository scope + one exact revision/job + ephemeral/JIT clean environment + teardown after receipt. Persistent runners can retain compromise or secrets across jobs.
- Forbidden runner = public repository + organization-wide shared runner + persistent developer workstation + production machine holding sensitive user data, live credentials, signing keys, or access to sensitive services.
- Local Windows VM = dedicated disposable proof environment; never reinterpret a normal production workstation as clean.
- VM use = an explicit accepted proof rung only; a user-excluded VM/UI remains excluded and cannot be revived as a fallback.
- Windows 11 ARM64 VM = useful supplemental smoke for PowerShell + Inno compile/install/uninstall/lifecycle + x86/x64 user-mode EXE emulation.
- ARM64 boundary = not native x64 compiler/toolchain/CRT/driver/GitHub-runner proof; Windows emulation does not cover kernel drivers, which require native ARM64.
- Local entrypoint = exact checked-in `windows_installer.ps1 verify` + `publication=none`; no tag/release/pointer/provider mutation.
- Architecture receipt = host architecture + guest architecture + process/EXE architecture + emulation state + Windows build + resolved toolchain paths/versions.
- Runner registration = separate security + persistent-access boundary; direct local execution never authorizes persistent self-hosted registration.
- Compact contract = local VM + self-hosted verify + hosted publish call the same repository-owned orchestration; YAML owns boundaries only.
- Build count = exactly one Flutter/native compile per target-native orchestration invocation; setup, guards, Inno, Defender, lifecycle, readback, and publication never trigger a second compile in that invocation.

## Clean runner

- Bash entry script = `set -euo pipefail` + `script_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"` + separate `readonly script_root` before first path use.
- Entry ownership = each executable resolves its own directory; inherited caller CWD + undeclared/shared `script_root` = `FAIL`.
- Real-branch fixture = invoke the actual entry script under identical strict-mode flags + controlled command/PATH stubs → traverse each live branch into every delegated helper.
- Adjacent audit = definition-before-use for variables crossing branch/setup/helper boundaries; static YAML/text/source presence proves wiring only.
- Regression = missing `script_root` red under `set -u` + initialized real-helper branch green; testing a helper directly is insufficient.
- Every Windows consumer = `flutter pub get` → source-changing version materialization → `dart run build_runner build` → `flutter gen-l10n` when configured → analyze/test → `flutter build windows --release`.
- Generated output = tracked OR generated in consumer OR transferred as explicit hash/provenance-verified artifact.
- Ubuntu-generated ignored output without transfer = absent on Windows.
- `build_runner` command = installed help + official changelog; current supported build command has no conflict-output flag.
- Forbidden = `-d` + `--delete-conflicting-output` + `--delete-conflicting-outputs`.
- Version materialization = capture tracked paths immediately before/after + allow exact intended delta only.
- Whole-workspace-clean assertion after setup/codegen = invalid; caches + ignored generation are expected.
- Exact-tip read with `persist-credentials: false` = explicitly authenticate job-scoped read-only `github.token`.
- Private Git order = `github.token` → `GH_TOKEN` → `gh auth setup-git` → exact-tip fetch; token persistence/output = forbidden.
- Referenced-path gate = every workflow/script/test/native target from typed config exists in the tracked-only checkout before archive/build.
- Transferred generation = create destination parent → extract sealed archive → verify provenance + hash + path/cardinality before consumption.
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
- Floating runner label = record resolved image OS/version + `flutter doctor -v` + `vswhere` result + actual native build; old Visual Studio paths/generators are not current-run proof.
- Runner migration = research the current image manifest/announcement before pinning or retrying; choose an explicit older image only for a proven compatibility need + accepted support tradeoff.

## `inno_bundle` setup

1. Resolve current stable package + installed help + primary changelog; then run `dart pub add --dev inno_bundle`.
2. Merge [inno-bundle-pubspec.yaml](../assets/inno-bundle-pubspec.yaml) into `pubspec.yaml`.
3. Generate the AppId once with `dart run inno_bundle:id` or an accepted GUID owner → commit the stable value before first release.
4. Choose `admin` + `arch` from accepted install scope; do not silently change elevation/install-location behavior.
5. Keep `vc_redist: false` in this proven flow → stage app-local CRTs from `VCToolsRedistDir` + verify PE/hash independently.
6. Build once = `flutter build windows --release` → stage/prove CRT → `dart run inno_bundle --no-app`.
7. Inspect generated `build\windows\x64\installer\Release\*.iss` + resulting EXE before accepting package ownership.

- Current CLI = `dart run inno_bundle`; `dart run inno_bundle:build` is deprecated.
- Existing release output reuse = `dart run inno_bundle --no-app`; no second Flutter compile.
- Config owner = `pubspec.yaml` `inno_bundle:` or explicit audited config path; `dlls` is deprecated → use `files`.
- Required fields = stable `id`; name/description/version/publisher may inherit pubspec values, but release proof resolves their exact outputs.
- Output = locate produced installer from resolved CLI output/build tree → rename/copy only after identity proof to `<app>-windows-installer-v<version>.exe`.
- Package-generated `.iss` = candidate artifact; AppId + CRT source + version resources + file layout + upgrade semantics remain explicit gates.

## PowerShell

- Syntax gate = compatible Windows `pwsh` + `[System.Management.Automation.Language.Parser]::ParseFile(...)` over every owned `.ps1`; any parse error fails before tool install/build.
- Syntax scope = parser owner + cheap smokes + installer harness + every called helper; regex/static intent review is not a parser.
- Smoke integrity = syntax gate first → intentional timeout smoke second; a smoke with unparsed syntax proves nothing.
- Generated source = literal single-quoted content + dynamic paths/values as named arguments; nested expandable PowerShell source = forbidden.
- Generated proof = materialize → parse exact output → execute harmless readiness path under compatible `pwsh` with a bounded receipt before CI/build.
- Filename suffix = compute in one scope + pass as an argument; if interpolation is unavoidable, use `${childPidPath}.tmp` or `$($childPidPath).tmp`, never `$childPidPath.tmp`.
- Variable names = case-insensitive; `$matches` in every casing aliases automatic `$Matches` → never use it for owned paths/results/arrays.
- Regex state = scalar `-match`/`-notmatch` can overwrite or retain `$Matches`; consume captures inside the matching branch + copy only required values to descriptive variables.
- `$Matches` regression = strict-mode red fixture stores source results in forbidden casing → scalar regex validation → source consumption fails; green fixture keeps named `@(...)` source intact.
- Numeric conversion = validate range + multiply in a wide numeric type + bounds-check + explicit target cast; `[checked]` is not a PowerShell type accelerator.
- Command/pipeline/filter result read with `.Count`/index/exact-one = explicit `@(...)` at assignment; singleton object properties are not collection cardinality.
- Selected scalar = explicit `[string]` conversion before string APIs.
- Cardinality fixture = strict mode + zero/one/many; static contract rejects command/pipeline/filter owners read with `.Count` before array normalization.
- Native output = capture array + immediate `$LASTEXITCODE` + normalize to one string before regex.
- Process arguments = executable + token array; shell-concatenated command string = avoid.
- Native child launch = `.NET ProcessStartInfo.ArgumentList` or equivalent structured API; each token is added separately.
- `Start-Process -ArgumentList <array>` joins the array into one command-line string; it is forbidden for owned helper/installer arguments whose values can contain spaces or quotes.
- Argument regression = exact spaced path + empty value + quote-bearing value round-trip through the real helper parser; token count/order/value must match.
- Cleanup identity = typed app config, never copied marker text; capture/rethrow the primary phase error if cleanup also fails.
- Tool path = uniquely resolved absolute path; Program Files guess = forbidden.
- `GITHUB_ENV` write = subsequent workflow steps only; the writing step/current process cannot consume the new value.
- Same-step installer = return the resolved path or set `$env:ISCC_PATH` in the current PowerShell process + validate absolute existing `ISCC.exe`.
- Future-step handoff, when needed = also append `ISCC_PATH=<path>` to `$env:GITHUB_ENV`; this never substitutes for current-process assignment.
- Consumption contract = installer result → current `$env:ISCC_PATH`/typed parameter → identity/lifecycle guard; assert non-empty/existing path + call order before build.
- Ephemeral root = unique `RUNNER_TEMP` child + owner marker + exact-root cleanup guard.

## Inno ownership

- `inno_bundle` = candidate generator, not distribution proof.
- Audit installed version = generated `.iss` + AppId + upgrade behavior + file layout + DLL sources + compiler selection + version resources + signing hooks.
- Use package directly only when generated contract covers accepted requirements.
- Extend least surface; retain custom `.iss`/scripts when preservation, rollback, relaunch, publication, or identity requirements exceed package behavior.
- Stable AppId = immutable across releases + in-place install directory.
- Update = never delete application data, sibling user paths, credentials, or unknown files.
- Inno compiler = current stable version resolved from official release evidence, then exact-pinned + authenticated/hash-verified `ISCC.exe` + cheap distinct-version sentinel + compile exit `0`.
- Tiny identity sentinel = distinct numeric version + textual version; compile/read fields before expensive Flutter build.
- Tiny lifecycle sentinel = unique temp root + invocation-namespaced synthetic AppId stable through compile/install/uninstall → invoke uninstaller once → bounded settlement of exact install directory + AppId uninstall key; run before expensive Flutter build.

## Installer identity

- Filename = `<app>-windows-installer-v<version>.exe`.
- File = exact expected name + accepted size bounds + `MZ` + SHA-256.
- Product identity = ProductName + FileDescription + stable AppId.
- Install path = the pinned Inno source tag owns `InstallLocation`; audited 7.0.2 includes `AddBackslash(...)`, so canonicalize trailing separators on expected/actual paths before equality only.
- Numeric fields = `VersionInfoVersion` + `VersionInfoProductVersion`; compare four integer parts independently.
- Text field = `VersionInfoProductTextVersion`; trim only observed textual boundary padding before equality.
- Diagnostic = exact failed field + expected value + safe observed value/length/hash.
- Path canonicalization never weakens AppId/name/version/hash/signature assertions; opaque aggregate identity exception = forbidden.
- Signature required by accepted delivery policy = verify chain + subject/thumbprint policy + timestamp before publication.

## Install lifecycle

### First release

- Previous-release lookup = authoritative published index/pointer + immutable retrievable installer + signed manifest/hash.
- No authoritative prior release = do not synthesize, wait, rebuild old source, or use current-source/expired Actions artifacts.
- Resolver mode = `none`; old-installer path = absent.
- Receipt = `phase=prior-release result=skipped_no_prior_release`.
- Required proof = bounded clean install + forced-failure cleanup + relaunch + uninstall + no application/user-data deletion.
- Skipped prior release skips only the old-installer branch; synthetic state seeding/preservation + clean install/failure/relaunch/uninstall remain mandatory.
- Preservation fixture = invocation-namespaced synthetic AppData + registry/credential entries owned directly by the harness or a tiny fixture helper.
- Forbidden fixture = production app EXE/`main.dart` probe mode + real repository/provider/storage graph + real user data + live credentials.
- Fixture regression = production executable/provider wiring red + isolated synthetic seed/read/preserve/cleanup green.

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
- Settlement = bounded poll until exact install directory + exact AppId uninstall registry key + owned TEMP-clone process/file state are absent.
- Ownership = retain installation/cleanup state until settlement passes or times out; no second uninstaller fallback.
- Timeout receipt = unresolved directory/key condition + elapsed/deadline + safe process state; bounded owned cleanup only.
- Relaunch cleanup = stop only the exact process proven to be the newly relaunched app; name-wide/process-wide termination = forbidden.
- Error precedence = capture primary phase exception + stack → attempt bounded cleanup → attach cleanup failure → rethrow primary; cleanup never masks root cause.
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
- Cold Flutter build ceiling = `900s` default inner deadline from observed clean-run range `~161–555s`; evidence bound, not vendor SLA.
- Duration tuning = record image/toolchain + phase duration; tighter repo-owned evidence may reduce the ceiling, relaxation requires new receipts.

## Updater behavior

- Surface = small muted warning/error-color banner + Settings indicator.
- Actions = `Download and install` + `Later`.
- Reminder = once after 24 hours; no tight polling/nag loop.
- Mandatory = security-critical or explicitly owner-marked important only; normal release remains deferrable.
- Install = download → verify manifest signature + installer SHA/signature → flush local state → close app → bounded helper/installer → verify installed version → relaunch.
- Unsupported platform/storage = fail closed.
- Provider choice = project-owned; UI/domain depends on manifest/download interfaces, not vendor SDK.
- Gateway path contract = producer + consumer share one canonical component encoder/decoder; test literal reserved form + one uppercase/lowercase percent-encoded form + reject double/ambiguous encoding.
- Gateway authorization = normalize/validate route → authenticate → object lookup; missing/existing object identity never changes anonymous response.
- Anonymous preflight = non-redirecting HEAD + range-limited GET accepts only the configured auth challenge and records method/status/curl exit/redirect count/auth-header presence without URL/body/token/header leakage.
- Runtime user token = existing signed-in user mints it at runtime; CI creates no temporary user/password/session/JWT unless an accepted contract specifically requires authenticated end-to-end gateway proof.

## Security

- Bundle/log/artifact = no embedded API keys, credentials, private signing keys, publisher tokens, or PII.
- Client-visible telemetry destination, when accepted, follows [error-reporting.md](error-reporting.md); upload tokens remain build-only.
- Scan = current tracked tree + built bundle + extracted installer.
- Defender invocation = official `MpCmdRun.exe -Scan -ScanType 3 -File <installer> -DisableRemediation -ReturnHR`; legacy exit `2` is ambiguous detection/action/error evidence and cannot prove a clean scan.
- Defender success = exact HRESULT `0x00000000`; detection/action-required HRESULT + unknown HRESULT + timeout = fail closed.
- Defender retry = only exact `HRESULT_FROM_WIN32(ERROR_SHARING_VIOLATION)` = `0x80070020` + at most one bounded retry; every other nonzero result fails immediately.
- Defender diagnostics = named phase + attempt + HRESULT + bounded redacted output + full stdout/stderr hashes; raw unbounded scanner logs/path output = forbidden.
- Defender fixture = [copyable scanner](../assets/defender-installer-scan.ps1) self-test proves clean green + detection red + unknown red + one sharing-violation retry green without adding a workflow step.
- Credential-store behavior, when used = synthetic round-trip + unsupported-platform fail-closed proof.
- Verification lane = no signing/publisher secret environment or arguments.
- Logs/receipts = hashes + versions + safe field diagnostics; never secret values.

## Publication

- Version/tag materialization = after exact-tree gates + before consuming codegen/native build.
- Build/sign = installer + signed manifest bound to exact source SHA/version/hash/size/classification.
- Immutable upload = versioned installer + manifest; collision accepted only when downloaded bytes match.
- Readback = independent download + installer identity/hash/signature + manifest signature/payload.
- Pointer/index activation = last external mutation after every immutable object readback passes.
- Activation input inventory = exact endpoint/project/index/pointer/object/version/SHA/key names are validated in the activation step environment before invocation; prior-step environment presence is not proof.
- Final readback = active pointer/index + immutable objects + exact version/tag/SHA.
- Failure before activation = previous pointer unchanged.
- Actions artifact = short-lived evidence or same-run transport of an already verified publication object; never previous-release authority or independent publication/readback proof.
- Provider binding = deployed server/version + official SDK compatibility pin + endpoint/mode + storage security policy; tiny credential/API probes prove none of the release upload path.
- Provider preflight = official SDK + candidate-size/type object + same chunking/protocol + same bucket/security policy → upload + metadata/hash/readback + bounded delete settlement before release activation.
- Manifest fixture = same canonical builder/schema owner as publication; otherwise contract-test parity for every required identity field, including `platform`.
- Crypto round-trip = canonical manifest payload → real signer → real verifier; reduced ad hoc maps + weaker fixture validators = false-gate risk.
- Public-read settlement = after immutable create returns, use the unauthenticated/public consumer path + bounded typed polling until exact bytes/hash/signature/payload are readable.
- Retryable read = exact `storage_file_not_found` + HTTP `429` + `5xx` only → bounded exponential backoff + attempt/deadline/type/code receipt.
- Immediate failure = `401` + `403` + unexpected `4xx` + hash/signature/payload/size/identity mismatch.
- Ambiguous create/read recovery = same immutable object ID + same accepted bytes; reconcile/read only. Rebuild + version bump + delete + overwrite + duplicate ID/object = `FAIL`.
- Preflight cleanup and release recovery differ: delete the owned temporary preflight object after proof; never delete or replace an immutable release object while availability is settling.
- Object identity = allocate one deterministic release object ID before upload + reuse it across attempts.
- Failed upload = reconcile that exact ID; partial/incomplete object → delete + verify absent before retry. Fresh ID, orphaned chunks, or raw REST fallback = `FAIL`.
- Failure ownership = native build/installer proof and downstream storage publication are separate phases/receipts; a storage failure never invalidates passed native proof or authorizes rebuilding it.
- Security-policy workaround = disabling scan/security, changing bucket/provider, server upgrade/custom image, or alternate protocol → explicit external-write + security/risk approval boundary.
- Provider adapter = preflight candidate write/read/delete + idempotency + permissions + atomicity/ordering contract before release.
- Release engine stages = admit exact revision/config → prepare → build once → verify → publish immutable objects → settle readback → activate pointer last.
- Cross-app parity map = stage + branch + input/config + output/receipt + ordering + timeout/failure/cleanup invariant; omitted or reordered stage blocks adaptation.
- Typed app config = product identity + stable AppId + artifact names + schema-required manifest fields + provider adapter inputs; validate before mutation.
- Schema variance = preserve intentional fields such as `channel` or `platform` through typed config/adapter contracts; never flatten them or copy another app's IDs.
- Real parity proof = execute actual first-release + upgrade + provider branches with controlled adapters; copied text/static call presence alone = insufficient.
- Activation-only recovery = when immutable installer/manifest/tag already verify and pointer activation alone failed, reuse those exact identifiers/bytes → reverify → activate/read back; skip codegen/build/Inno/upload/manifest/tag/artifact creation.
- Recovery mode = explicit same version/tag/source revision/object IDs + unchanged publication target; classification/no-op paths cannot masquerade as completion.

## Proof

- Diagnostic receipt = source SHA + dispatch SHA/ref + resolved tools + generated-source proof + EXE/CRT identity + installer identity/hash/signature + secret/Defender scans + lifecycle branch/results + phase receipts + `publication=none`.
- Publisher receipt = diagnostic run/SHA + required jobs/steps + version/tag + immutable object IDs/hashes + downloaded verification + pointer/index readback + absent unintended release/deployment/install.
- Independent receipts = native build/installer | isolated lifecycle/state preservation | immutable publication/readback | pointer activation; later failure never invalidates an earlier receipt or authorizes rebuilding it.
- Remote PASS = exact required job + named step green; workflow-level green alone = insufficient.
- Active repair/retry = report nonterminal; never claim current workflow green before exact run receipt.

## Sources

- [Dart build_runner](https://dart.dev/tools/build_runner)
- [build_runner changelog](https://pub.dev/packages/build_runner/changelog)
- [Flutter Windows distribution](https://docs.flutter.dev/platform-integration/windows/building)
- [GitHub workflow syntax and permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [GitHub manual workflow dispatch](https://docs.github.com/actions/managing-workflow-runs/manually-running-a-workflow)
- [GitHub workflow-dispatch REST `ref`](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)
- [`actions/checkout` `ref` input](https://github.com/actions/checkout/blob/main/action.yml)
- [`actions/checkout` 7.0.1 release](https://github.com/actions/checkout/releases/tag/v7.0.1)
- [`actions/upload-artifact` 7.0.1 release](https://github.com/actions/upload-artifact/releases/tag/v7.0.1)
- [`actions/download-artifact` 8.0.1 release](https://github.com/actions/download-artifact/releases/tag/v8.0.1)
- [GitHub `windows-latest` Server 2025 + Visual Studio 2026 migration](https://github.com/actions/runner-images/issues/14017)
- [GitHub Actions environment files](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#setting-an-environment-variable)
- [GitHub token](https://docs.github.com/en/actions/concepts/security/github_token)
- [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [GitHub self-hosted runners](https://docs.github.com/en/actions/reference/runners/self-hosted-runners)
- [GitHub secure use](https://docs.github.com/en/actions/reference/security/secure-use)
- [GitHub private-repository runner recommendation](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners)
- [`act` runner images](https://nektosact.com/usage/runners.html)
- [`act` unsupported functionality](https://nektosact.com/not_supported.html)
- [Windows on Arm FAQ](https://learn.microsoft.com/en-us/windows/arm/faq)
- [Add Arm support to Windows apps](https://learn.microsoft.com/en-us/windows/arm/add-arm-support)
- [How x86 and x64 emulation works on Arm](https://learn.microsoft.com/en-us/windows/arm/apps-on-arm-x86-emulation)
- [PowerShell case sensitivity](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_case-sensitivity)
- [PowerShell automatic `$Matches`](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_automatic_variables)
- [PowerShell `-match`/`-notmatch`](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_comparison_operators)
- [PowerShell arrays + `@(...)`](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_arrays)
- [PowerShell Start-Process](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/start-process)
- [.NET `ProcessStartInfo.ArgumentList`](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.processstartinfo.argumentlist)
- [PowerShell Wait-Process](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/wait-process)
- [PowerShell `Parser.ParseFile`](https://learn.microsoft.com/en-us/dotnet/api/system.management.automation.language.parser.parsefile?view=powershellsdk-7.6.0)
- [PowerShell numeric literals + type accelerators](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_numeric_literals?view=powershell-7.5)
- [PowerShell quoting + expandable strings](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_quoting_rules?view=powershell-7.6)
- [Visual Studio `vswhere`](https://github.com/microsoft/vswhere)
- [Inno Setup AppId](https://jrsoftware.org/ishelp/topic_setup_appid.htm)
- [Inno Setup uninstaller exit codes](https://jrsoftware.org/ishelp/topic_uninstexitcodes.htm)
- [Inno Setup 7.0.2 revision history](https://jrsoftware.org/files/is7-whatsnew.htm)
- [Inno Setup 7.0.2 `InstallLocation` source](https://github.com/jrsoftware/issrc/blob/is-7_0_2/Projects/Src/Setup.Install.pas#L280)
- [Inno Setup event functions](https://jrsoftware.org/ishelp/topic_scriptevents.htm)
- [Inno Setup exit codes](https://jrsoftware.org/ishelp/topic_setupexitcodes.htm)
- [Inno Setup command-line parameters](https://jrsoftware.org/ishelp/topic_setupcmdline.htm)
- [Inno command-line compiler](https://jrsoftware.org/ishelp/topic_compilercmdline.htm)
- [Inno binary file version](https://jrsoftware.org/ishelp/topic_setup_versioninfoversion.htm)
- [Inno binary product version](https://jrsoftware.org/ishelp/topic_setup_versioninfoproductversion.htm)
- [Inno textual product version](https://jrsoftware.org/ishelp/topic_setup_versioninfoproducttextversion.htm)
- [`inno_bundle`](https://pub.dev/packages/inno_bundle)
- [WHATWG URL Standard](https://url.spec.whatwg.org/)
- [Win32 `CommandLineToArgvW`](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-commandlinetoargvw)
- [Win32 `WaitForSingleObject`](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject)
- [Microsoft Defender `MpCmdRun` + `-ReturnHR`](https://learn.microsoft.com/en-us/defender-endpoint/command-line-arguments-microsoft-defender-antivirus)
- [Microsoft Defender HRESULTs](https://learn.microsoft.com/en-us/defender-endpoint/troubleshoot-microsoft-defender-antivirus)
- [Win32 `ERROR_SHARING_VIOLATION`](https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--0-499-)
- [Win32 `HRESULT_FROM_WIN32`](https://learn.microsoft.com/en-us/windows/win32/api/winerror/nf-winerror-hresult_from_win32)
- [Storage permissions](https://appwrite.io/docs/products/storage/permissions)
- [Storage response codes](https://appwrite.io/docs/apis/response-codes)
- [Storage create/download API](https://appwrite.io/docs/references/cloud/server-rest/storage)
