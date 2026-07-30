#!/usr/bin/env python3
"""Check the provider-neutral Windows installer assets and their CI wiring."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "building-flutter-apps"
REFERENCE = SKILL / "references" / "windows-installer-pipeline.md"
WORKFLOW = SKILL / "assets" / "windows-installer-workflow.yml"
SENTINEL = SKILL / "assets" / "inno-uninstall-settlement-sentinel.ps1"
CI = ROOT / ".github" / "workflows" / "windows-installer-sentinel.yml"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
reference_text = REFERENCE.read_text(encoding="utf-8")
workflow_text = WORKFLOW.read_text(encoding="utf-8")
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
    workflow_text.count(r".\.github\scripts\inno-uninstall-settlement-sentinel.ps1") == 2,
    "diagnostic and publisher must each execute the settlement sentinel",
)

verify_job = workflow_text.split("  verify_windows:", 1)[1].split("  quality:", 1)[0]
publish_job = workflow_text.split("  publish:", 1)[1]
for name, job in (("diagnostic", verify_job), ("publisher", publish_job)):
    require(
        job.index("inno-uninstall-settlement-sentinel.ps1")
        < job.index("flutter build windows --release"),
        f"{name} settlement sentinel must run before Flutter compilation",
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

for text in (reference_text, workflow_text, sentinel_text, ci_text):
    lowered = text.lower()
    for forbidden in ("appwrite", "jabal", "emr_", "project_id", "database_id"):
        require(forbidden not in lowered, f"provider/project data leaked: {forbidden}")

print("WINDOWS_INSTALLER_ASSETS_OK")
