#!/usr/bin/env python3
"""Check the provider-neutral Windows installer assets and their CI wiring."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "building-flutter-apps"
REFERENCE = SKILL / "references" / "windows-installer-pipeline.md"
WORKFLOW = SKILL / "assets" / "windows-installer-workflow.yml"
INNO_BUNDLE = SKILL / "assets" / "inno-bundle-pubspec.yaml"
SENTINEL = SKILL / "assets" / "inno-uninstall-settlement-sentinel.ps1"
DEFENDER_SCANNER = SKILL / "assets" / "defender-installer-scan.ps1"
CI = ROOT / ".github" / "workflows" / "windows-installer-sentinel.yml"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
reference_text = REFERENCE.read_text(encoding="utf-8")
workflow_text = WORKFLOW.read_text(encoding="utf-8")
inno_bundle_text = INNO_BUNDLE.read_text(encoding="utf-8")
sentinel_text = SENTINEL.read_text(encoding="utf-8")
defender_scanner_text = DEFENDER_SCANNER.read_text(encoding="utf-8")
ci_text = CI.read_text(encoding="utf-8")
answer_evals = json.loads(
    (ROOT / "evals" / "evals.json").read_text(encoding="utf-8")
)["evals"]

require(
    "assets/inno-uninstall-settlement-sentinel.ps1" in skill_text,
    "SKILL.md must link the Inno settlement sentinel directly",
)
require(
    "../assets/inno-uninstall-settlement-sentinel.ps1" in reference_text,
    "Windows reference must link the copyable sentinel",
)
require(
    "assets/defender-installer-scan.ps1" in skill_text
    and "../assets/defender-installer-scan.ps1" in reference_text,
    "skill and Windows reference must link the Defender scanner directly",
)
require(
    "assets/inno-bundle-pubspec.yaml" in skill_text
    and "../assets/inno-bundle-pubspec.yaml" in reference_text,
    "skill and Windows reference must link the inno_bundle pubspec scaffold",
)

verify_job = workflow_text.split("  verify_windows:", 1)[1].split("  admission:", 1)[0]
publish_job = workflow_text.split("  publish:", 1)[1]
for name, job, command, max_steps in (
    ("diagnostic", verify_job, "windows_installer.ps1 verify", 4),
    ("publisher", publish_job, "windows_installer.ps1 publish", 5),
):
    require(
        command in job,
        f"{name} must delegate complete execution to one orchestration command",
    )
    require(
        job.count("- name:") <= max_steps,
        f"{name} YAML must retain only boundary steps",
    )
require(
    "parse-powershell -> timeout smoke -> CRT smoke -> Inno identity smoke ->"
    in workflow_text
    and "Contract-test call presence and order" in workflow_text,
    "compact workflow must preserve and order internal pre-build guards",
)
require(
    "windows_installer.ps1 parse-powershell" not in workflow_text,
    "PowerShell parsing must stay inside compact orchestration, not a YAML step",
)
require(
    "dart run inno_bundle --no-app" in workflow_text
    and "activates the provider-neutral pointer last" in workflow_text,
    "compact scaffold must retain the full build-once and publication contract",
)
require(
    "flutter build windows --release" not in workflow_text,
    "Flutter compilation belongs inside the single orchestration command",
)
require(
    "secrets." not in verify_job and "contents: write" not in verify_job,
    "diagnostic job must remain secret-free and read-only",
)
require(
    "runs-on: [self-hosted, windows, x64, windows-installer-proof]" in verify_job
    and "runs-on: windows-latest" in publish_job,
    "target-native verify must be self-hosted and publisher must be the sole GitHub-hosted Windows job",
)
require(
    "needs:" in publish_job
    and "- admission" in publish_job
    and "contents: write" in publish_job,
    "publisher must consume read-only admission before write authority",
)

for phrase in (
    "id: REPLACE_WITH_STABLE_GUID",
    "name: REPLACE_WITH_PRODUCT_NAME",
    "publisher: REPLACE_WITH_PUBLISHER",
    "admin: false",
    "arch: x64",
    "vc_redist: false",
    "files: []",
):
    require(phrase in inno_bundle_text, f"inno_bundle pubspec scaffold missing: {phrase}")
for forbidden in ("dlls:", "token", "secret", "project_id", "database_id"):
    require(
        forbidden not in inno_bundle_text.lower(),
        f"inno_bundle pubspec scaffold contains forbidden field: {forbidden}",
    )
for phrase in (
    "dart pub add --dev inno_bundle",
    "dart run inno_bundle --no-app",
    "dlls` is deprecated",
    "no second Flutter compile",
    "`GITHUB_ENV` write = subsequent workflow steps only",
    "set `$env:ISCC_PATH` in the current PowerShell process",
    "Consumption contract = installer result",
    "tiny credential/API probes prove none of the release upload path",
    "candidate-size/type object + same chunking/protocol",
    "partial/incomplete object → delete + verify absent before retry",
    "native build/installer proof and downstream storage publication are separate phases/receipts",
    "old Visual Studio paths/generators are not current-run proof",
    "`$matches` in every casing aliases automatic `$Matches`",
    "scalar `-match`/`-notmatch` can overwrite or retain `$Matches`",
    "Command/pipeline/filter result read with `.Count`/index/exact-one = explicit `@(...)`",
    "Inno 6.7.3 `InstallLocation` includes `AddBackslash(...)`",
    "cleanup never masks root cause",
    "Cold Flutter build ceiling = `900s`",
    "official `MpCmdRun.exe -Scan -ScanType 3 -File <installer> -DisableRemediation -ReturnHR`",
    "legacy exit `2` is ambiguous",
    "`HRESULT_FROM_WIN32(ERROR_SHARING_VIOLATION)` = `0x80070020`",
    "bounded redacted output + full stdout/stderr hashes",
    "## Cost-aware proof ladder",
    "Self-hosted Actions usage = no GitHub-hosted Actions minute charge",
    "private repository only + repository scope",
    "clinic production PC",
    "`act` = portable wiring aid only",
    "intentionally incomplete",
    "same checked-in `windows_installer.ps1 verify`",
    "Provider preflight = cheap Linux",
    "Public-read settlement = after immutable create returns",
    "exact `storage_file_not_found` + HTTP `429` + `5xx` only",
    "Immediate failure = `401` + `403`",
    "same immutable object ID + same accepted bytes",
    "Rebuild + version bump + delete + overwrite + duplicate ID/object = `FAIL`",
    "Manifest fixture = same canonical builder/schema owner as publication",
    "including `platform`",
    "Crypto round-trip = canonical manifest payload → real signer → real verifier",
    "reduced ad hoc maps + weaker fixture validators = false-gate risk",
    "Bash entry script = `set -euo pipefail`",
    'script_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"',
    "Real-branch fixture = invoke the actual entry script",
    "definition-before-use for variables crossing branch/setup/helper boundaries",
    "missing `script_root` red under `set -u`",
    "Cross-app engine = one semantic release stage DAG",
    "Second-app admission = stage-by-stage parity map against one proven reference",
    "Copy-pasted app-specific release engine + foreign project/object IDs = `FAIL`",
    "Schema variance = preserve intentional fields such as `channel` or `platform`",
    "Windows 11 ARM64 VM = useful supplemental smoke",
    "ARM64 boundary = not native x64 compiler/toolchain/CRT/driver/GitHub-runner proof",
    "kernel drivers, which require native ARM64",
    "exact checked-in `windows_installer.ps1 verify` + `publication=none`",
    "Architecture receipt = host architecture + guest architecture",
    "Runner registration = separate security + persistent-access boundary",
):
    require(phrase in reference_text, f"Windows reference missing inno_bundle flow: {phrase}")
require(
    "Writing `GITHUB_ENV`" in workflow_text
    and "alone is only a handoff to a later workflow step" in workflow_text
    and "return/set `ISCC_PATH` in the current" in workflow_text,
    "compact workflow must distinguish current-process tool paths from next-step handoff",
)
require(
    "`defender-installer-scan.ps1`" in workflow_text
    and "official `-ReturnHR`" in workflow_text
    and "sharing violation `0x80070020` once" in workflow_text,
    "compact workflow must retain the Defender HRESULT contract internally",
)
require(
    "repository-scoped ephemeral/JIT self-hosted Windows" in workflow_text
    and "`act` is wiring-only" in workflow_text
    and "sole GitHub-hosted Windows publisher" in workflow_text
    and "storage_file_not_found" in workflow_text
    and "Recovery never rebuilds" in workflow_text,
    "compact workflow must retain the cost ladder and immutable public-read settlement",
)
require(
    "publication schema owner (including `platform`)" in workflow_text
    and "real signer and verifier" in workflow_text
    and "reduced" in workflow_text
    and "weaker validator" in workflow_text,
    "compact workflow must retain manifest schema and crypto parity inside provider preflight",
)
require(
    "one semantic release stage DAG across apps" in workflow_text
    and "validated typed configuration or adapters" in workflow_text
    and "never fork a copied publisher" in workflow_text
    and "execute the real adapted branches" in workflow_text,
    "compact workflow must retain shared cross-app release-engine parity",
)
require(
    "Every Bash entrypoint sets strict mode" in workflow_text
    and "from BASH_SOURCE before path use" in workflow_text
    and "real provider/helper" in workflow_text
    and "branches with controlled stubs" in workflow_text
    and "Static source presence is not execution proof" in workflow_text,
    "compact workflow must retain strict Bash entrypoint execution proof",
)

require(
    '$appId = "{$appGuid}"' in sentinel_text,
    "sentinel AppId must be a conventional invocation GUID",
)
require(
    "AppId={{SENTINEL_APP_ID}" in sentinel_text
    and ".Replace('SENTINEL_APP_ID', $appGuid)" in sentinel_text,
    "compiled Inno fixture must consume the invocation GUID through a literal template",
)
require(
    sentinel_text.count("-Phase 'sentinel-uninstall-process'") == 1,
    "sentinel must invoke the owned uninstaller exactly once",
)
for phrase in (
    "Wait-UninstallSettlement",
    "directory=absent registry=absent",
    "original_process=completed cleanup_clone=unknown",
    "deadline_utc=",
    "elapsed_ms=",
    "$rootOwned = (Get-Content -LiteralPath $ownerMarker -Raw) -eq $appId",
):
    require(phrase in sentinel_text, f"sentinel missing contract: {phrase}")
for forbidden in (
    "Start-Process -Wait",
    "WaitForSingleObject(",
    "AppId=BuildingFlutterApps.UninstallSettlementSentinel",
):
    require(forbidden not in sentinel_text, f"sentinel contains forbidden contract: {forbidden}")

for phrase in (
    "'-ReturnHR'",
    "'-DisableRemediation'",
    "'0x00000000'",
    "'0x80070020'",
    "AllowedSharingViolationRetries = 1",
    "detection-or-action-required",
    "unknown-hresult",
    "stdout_sha256=",
    "stderr_sha256=",
    "DEFENDER_SCAN_FIXTURES_OK",
    "detection=red",
    "unknown=red",
    "sharing_violation_retry=green",
):
    require(phrase in defender_scanner_text, f"Defender scanner missing contract: {phrase}")
for forbidden in (
    "Start-Process -Wait",
    "WaitForSingleObject(",
    "AllowedSharingViolationRetries = 2",
):
    require(
        forbidden not in defender_scanner_text,
        f"Defender scanner contains forbidden contract: {forbidden}",
    )

for path in (
    ".github/workflows/windows-installer-sentinel.yml",
    "evals/evals.json",
    "skills/building-flutter-apps/SKILL.md",
    "skills/building-flutter-apps/assets/defender-installer-scan.ps1",
    "skills/building-flutter-apps/assets/inno-bundle-pubspec.yaml",
    "skills/building-flutter-apps/assets/inno-uninstall-settlement-sentinel.ps1",
    "skills/building-flutter-apps/assets/windows-installer-workflow.yml",
    "skills/building-flutter-apps/references/windows-installer-pipeline.md",
    "tool/check_windows_installer_assets.py",
):
    require(path in ci_text, f"Windows CI path filter missing: {path}")
require("python tool/check_windows_installer_assets.py" in ci_text, "Windows CI must run integration checker")
require(
    "$scannerPath -SelfTest" in ci_text,
    "Windows CI must execute Defender red/green fixtures",
)
require(
    ci_text.index("[System.Management.Automation.Language.Parser]::ParseFile(")
    < ci_text.index("$scannerPath -SelfTest"),
    "Windows CI must parse the Defender scanner before executing its fixtures",
)
require("runs-on: windows-latest" in ci_text, "Windows CI must use a compatible runner")
require("timeout-minutes: 10" in ci_text, "Windows CI must remain tightly bounded")
require("ParseFile(" in ci_text, "Windows CI must parse the exact PowerShell sentinel")
require(
    "'${{ github.workspace }}\\skills\\building-flutter-apps\\assets\\defender-installer-scan.ps1'"
    in ci_text,
    "Windows CI must parse the exact Defender scanner",
)

require(
    any(
        "disappearing uninstaller again" in case["prompt"]
        and all("30573789878" not in item for item in case["expectations"])
        for case in answer_evals
    ),
    "answer eval must be durable and exclude a transient run ID",
)
require(
    any(
        "compacted a Flutter Windows publisher" in case["prompt"]
        and any("same Actions step count" in item for item in case["expectations"])
        and any("before the single Flutter build" in item for item in case["expectations"])
        for case in answer_evals
    ),
    "answer eval must reject dead internal guards after YAML compaction",
)
require(
    any(
        "set up inno_bundle" in case["prompt"].lower()
        and any("pubspec.yaml" in item for item in case["expectations"])
        and any("--no-app" in item for item in case["expectations"])
        for case in answer_evals
    ),
    "answer eval must cover complete inno_bundle setup and build-once flow",
)
require(
    any(
        "appends `ISCC_PATH=...`" in case["prompt"]
        and any("subsequent workflow steps" in item for item in case["expectations"])
        and any("current PowerShell process" in item for item in case["expectations"])
        and any("GITHUB_ENV-only" in item for item in case["expectations"])
        for case in answer_evals
    ),
    "answer eval must reject GITHUB_ENV-only same-step tool propagation",
)
require(
    any(
        "chunksUploaded=3/chunksTotal=4" in case["prompt"]
        and any("official server-SDK compatibility table" in item for item in case["expectations"])
        and any("same-size/type object" in item for item in case["expectations"])
        and any("deletes it, and verifies absence" in item for item in case["expectations"])
        and any("Rejects raw REST" in item for item in case["expectations"])
        and any("explicit external-write and security/risk approval boundary" in item for item in case["expectations"])
        and any("flutter doctor -v" in item for item in case["expectations"])
        for case in answer_evals
    ),
    "answer eval must cover downstream chunked-storage and runner-image regressions",
)
require(
    any(
        "assigns filtered source paths to `$matches`" in case["prompt"]
        and any("case-insensitive" in item for item in case["expectations"])
        and any("zero, one, and many" in item for item in case["expectations"])
        and any("strict-mode red fixture" in item for item in case["expectations"])
        and any("explicit array normalization" in item for item in case["expectations"])
        for case in answer_evals
    ),
    "answer eval must cover Matches collision and cardinality fixtures",
)
require(
    any(
        "InstallLocation ending in a backslash" in case["prompt"]
        and any("AddBackslash" in item for item in case["expectations"])
        and any("rethrows the primary error" in item for item in case["expectations"])
        and any("same-job codegen and verified-transfer" in item for item in case["expectations"])
        and any("900-second" in item for item in case["expectations"])
        for case in answer_evals
    ),
    "answer eval must cover Inno path, settlement, branch, and timeout contracts",
)
require(
    any(
        "MpCmdRun returns legacy exit 2" in case["prompt"]
        and any("official -ReturnHR" in item for item in case["expectations"])
        and any("exact 0x80070020" in item for item in case["expectations"])
        and any("bounded redacted diagnostic output" in item for item in case["expectations"])
        and any("real PowerShell" in item for item in case["expectations"])
        and any("topology" in item for item in case["expectations"])
        for case in answer_evals
    ),
    "answer eval must cover Defender HRESULT classification and bounded retry fixtures",
)
require(
    any(
        "burning paid windows-latest minutes" in case["prompt"]
        and any("ephemeral or JIT self-hosted Windows runner" in item for item in case["expectations"])
        and any("clinic production machines" in item for item in case["expectations"])
        and any("wiring-only" in item for item in case["expectations"])
        and any("storage_file_not_found" in item for item in case["expectations"])
        and any("same immutable object ID" in item for item in case["expectations"])
        and any("compact YAML boundary steps unchanged" in item for item in case["expectations"])
        for case in answer_evals
    ),
    "answer eval must cover the cost ladder, self-hosted safety, and public-read settlement",
)
require(
    any(
        "Windows 11 ARM64 VMware Fusion VM" in case["prompt"]
        and any("user-mode applications" in item for item in case["expectations"])
        and any("kernel drivers" in item for item in case["expectations"])
        and any("native x64 compiler" in item for item in case["expectations"])
        and any("publication=none" in item for item in case["expectations"])
        and any("host architecture" in item for item in case["expectations"])
        and any("persistent-access boundary" in item for item in case["expectations"])
        and any("compact YAML" in item for item in case["expectations"])
        for case in answer_evals
    ),
    "answer eval must distinguish ARM64 emulation smoke from native x64 proof and runner registration",
)
require(
    any(
        "omits platform" in case["prompt"]
        and any("false-gate risk" in item for item in case["expectations"])
        and any("manifest builder or schema owner" in item for item in case["expectations"])
        and any("every required identity field" in item for item in case["expectations"])
        and any("real signer" in item and "real production verifier" in item for item in case["expectations"])
        and any("red fixture omitting platform" in item for item in case["expectations"])
        and any("compact YAML topology" in item for item in case["expectations"])
        for case in answer_evals
    ),
    "answer eval must reject reduced preflight manifests and require canonical signer/verifier parity",
)
require(
    any(
        "never initialized" in case["prompt"]
        and any("BASH_SOURCE" in item for item in case["expectations"])
        and any("two-step assignment" in item for item in case["expectations"])
        and any("actual admission entry script" in item for item in case["expectations"])
        and any("definition-before-use" in item for item in case["expectations"])
        and any("missing script_root" in item for item in case["expectations"])
        and any("compact YAML" in item for item in case["expectations"])
        for case in answer_evals
    ),
    "answer eval must cover strict Bash directory ownership and real-branch admission",
)
require(
    any(
        "copied another app's publisher" in case["prompt"]
        and any("one shared semantic release engine" in item for item in case["expectations"])
        and any("stage-by-stage parity map" in item for item in case["expectations"])
        and any("channel versus platform" in item for item in case["expectations"])
        and any("foreign project" in item for item in case["expectations"])
        and any("real first-release, upgrade, and provider branches" in item for item in case["expectations"])
        and any("compact two-job YAML" in item for item in case["expectations"])
        for case in answer_evals
    ),
    "answer eval must cover one cross-app release engine, typed variance, and real-branch parity",
)

for text in (
    reference_text,
    workflow_text,
    inno_bundle_text,
    sentinel_text,
    defender_scanner_text,
    ci_text,
):
    lowered = text.lower().replace("https://appwrite.io/docs/", "")
    for forbidden in ("appwrite", "jabal", "emr_", "project_id", "database_id"):
        require(forbidden not in lowered, f"provider/project data leaked: {forbidden}")

print("WINDOWS_INSTALLER_ASSETS_OK")
