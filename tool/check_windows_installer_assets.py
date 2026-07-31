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
CI = ROOT / ".github" / "workflows" / "windows-installer-sentinel.yml"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
reference_text = REFERENCE.read_text(encoding="utf-8")
workflow_text = WORKFLOW.read_text(encoding="utf-8")
inno_bundle_text = INNO_BUNDLE.read_text(encoding="utf-8")
sentinel_text = SENTINEL.read_text(encoding="utf-8")
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
):
    require(phrase in reference_text, f"Windows reference missing inno_bundle flow: {phrase}")
require(
    "Writing `GITHUB_ENV`" in workflow_text
    and "alone is only a handoff to a later workflow step" in workflow_text
    and "return/set `ISCC_PATH` in the current" in workflow_text,
    "compact workflow must distinguish current-process tool paths from next-step handoff",
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

for path in (
    ".github/workflows/windows-installer-sentinel.yml",
    "evals/evals.json",
    "skills/building-flutter-apps/SKILL.md",
    "skills/building-flutter-apps/assets/inno-bundle-pubspec.yaml",
    "skills/building-flutter-apps/assets/inno-uninstall-settlement-sentinel.ps1",
    "skills/building-flutter-apps/assets/windows-installer-workflow.yml",
    "skills/building-flutter-apps/references/windows-installer-pipeline.md",
    "tool/check_windows_installer_assets.py",
):
    require(path in ci_text, f"Windows CI path filter missing: {path}")
require("python tool/check_windows_installer_assets.py" in ci_text, "Windows CI must run integration checker")
require("runs-on: windows-latest" in ci_text, "Windows CI must use a compatible runner")
require("timeout-minutes: 10" in ci_text, "Windows CI must remain tightly bounded")
require("ParseFile(" in ci_text, "Windows CI must parse the exact PowerShell sentinel")

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

for text in (reference_text, workflow_text, inno_bundle_text, sentinel_text, ci_text):
    lowered = text.lower()
    for forbidden in ("appwrite", "jabal", "emr_", "project_id", "database_id"):
        require(forbidden not in lowered, f"provider/project data leaked: {forbidden}")

print("WINDOWS_INSTALLER_ASSETS_OK")
