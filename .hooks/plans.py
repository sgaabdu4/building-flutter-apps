"""Check plan declarations; evidence truth and authorization still need review."""

import re
from pathlib import Path

from gate_config import changed_files, repository_files
from shipping import load_policy

SECTIONS = (
    "Outcome + scope",
    "Repository context",
    "Decisions + authorization",
    "Acceptance + steps",
    "Baseline + execution",
    "Risks + recovery",
    "ux_reference",
    "Verification",
)
STAGES = ("Draft", "Ready", "Complete")
HANDOFFS = ("Clarification", "Approval")
PLACEHOLDERS = r"(?im)\[TODO:|^\s*(?:#\s+|[\w +]+:\s*)?(?:TODO(?::[^\n]*)?|TBD|<(?!https?://)[^>\n]+>)\s*$"


def is_plan_path(path: Path) -> bool:
    return path.name.lower() == "plan.md" and (
        path.parent == Path(".") or path.parts[0] == "features"
    )


CAPTURES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".mp4", ".mov", ".webm"}


def planning_only(root: Path, names: set[str]) -> bool:
    """Markdown and captures, such as screenshots, kept in a feature plan's folder."""
    folders = {
        path.parent.relative_to(root)
        for path in repository_files(root)
        if is_plan_path(path.relative_to(root))
    } - {Path(".")}
    return all(
        Path(name).suffix.lower() == ".md"
        or (
            Path(name).suffix.lower() in CAPTURES
            and folders.intersection(Path(name).parents)
        )
        for name in names
    )


def is_documentation(path: Path) -> bool:
    """Plans and top-level Markdown, which only the secret scan reads."""
    top_level = path.parent == Path(".") and path.suffix.lower() == ".md"
    return is_plan_path(path) or (top_level and path.name != "AGENTS.md")


def report_stage(failed: bool, stage: str | None) -> None:
    if failed:
        print("Hard Eng: verification failed; the next stage is blocked.")
    elif stage == "Ready":
        print(
            "Hard Eng: planning checks passed — ready for build within the authorized scope."
        )
    elif stage == "Complete":
        print(
            "Hard Eng: build checks passed — ready for ship; remote delivery is not verified by this check."
        )


def field(content: str, name: str) -> str:
    values = re.findall(rf"(?m)^{re.escape(name)}: *(.*)$", content)
    if len(values) != 1:
        raise ValueError(f"plan needs one '{name}:' field, found {len(values)}")
    if not values[0].strip():
        raise ValueError(
            f"'{name}:' needs text on the label's line; a list may follow it"
        )
    return values[0].strip()


def header_status(content: str) -> str:
    """The plan's own Status sits above its first section; slices may carry theirs."""
    return field(content.split("\n## ", 1)[0], "Status")


def plan_status(content: str) -> str | None:
    """Plans written before the Status field are historical, not active."""
    try:
        return header_status(content)
    except ValueError:
        return None


def proof(content: str, allowed: set[str]) -> None:
    result = field(content, "Result")
    if result not in allowed:
        raise ValueError(f"plan Result {result!r} must be one of {sorted(allowed)}")
    evidence_field(content, "Evidence")


def evidence_field(content: str, name: str) -> str:
    value = field(content, name)
    if re.match(
        r"(?i)^(?:pending|none|blocked|n/a|unavailable|not (?:run|inspected|captured))\b",
        value,
    ):
        raise ValueError(
            f"plan {name} must describe actual proof, not a pending result"
        )
    return value


def plan_sections(content: str, *, allow_placeholders: bool = False) -> dict[str, str]:
    if not allow_placeholders and re.search(PLACEHOLDERS, content):
        raise ValueError("plan contains unfilled template placeholders")
    if not re.search(r"(?m)^# \S.+$", content):
        raise ValueError("plan needs a title")
    parts = re.split(r"(?m)^## +([^\n]+)\n", content + "\n")
    headings = [heading.strip() for heading in parts[1::2]]
    sections = dict(zip(headings, parts[2::2]))
    for heading in SECTIONS:
        if headings.count(heading) != 1 or not sections[heading].strip():
            raise ValueError(f"plan needs one filled '## {heading}' section")
    for line in content.splitlines():
        for marker in re.finditer(r"(?i)\bN/A\b", line):
            if not re.match(r"\s+—\s+\S", line[marker.end() :]):
                raise ValueError("plan N/A needs an inline reason: N/A — reason")
    return sections


def e2e_proof(verification: str, status: str, *, legacy: bool = False) -> None:
    if legacy and not re.search(r"(?m)^E2E:", verification):
        return
    e2e = field(verification, "E2E")
    match = re.fullmatch(r"(Required|Passed|Delivery|N/A) — (\S.*)", e2e)
    if match is None:
        raise ValueError(
            "plan E2E needs Required, Passed, Delivery or N/A — concrete journey/evidence or reason"
        )
    if status == "Complete" and match[1] == "Required":
        raise ValueError(
            "complete plan E2E is still Required; run the journey and record Passed evidence"
        )
    if match[1] == "Passed" and re.match(
        r"(?i)^(pending|none|blocked|n/a)\b", match[2]
    ):
        raise ValueError("plan E2E Passed needs actual runtime evidence")
    if match[1] == "Delivery" and not re.search(
        r"(?im)^\s*(?:[-*+]\s+)?Delivery target:\s*Deploy\s*$", verification
    ):
        raise ValueError(
            "delivery E2E requires Delivery target: Deploy and configured delivery checks"
        )


def ux_proof(content: str, *, legacy: bool = False) -> None:
    if re.fullmatch(r"N/A — [^\n]+", content.strip()):
        return
    proof(content, {"Passed"})
    image = r"!\[[^\]\n]*\]\((\S[^)\n]*)\)"
    if not re.search(image, content):
        raise ValueError(
            "UX evidence needs a Markdown image reference to the rendered proposal"
        )
    if legacy and not re.search(r"(?m)^Surface:", content):
        return
    surface = field(content, "Surface")
    if not re.fullmatch(r"(Existing|New|Mock) — \S.+", surface):
        raise ValueError(
            "UX Surface needs Existing, New or Mock — actual screen or design-system owner"
        )
    before = field(content, "Before")
    baseline = re.fullmatch(image, before)
    if baseline is None and not (
        surface.startswith(("New — ", "Mock — "))
        and re.fullmatch(r"N/A — \S.+", before)
    ):
        raise ValueError(
            "UX Before needs the actual baseline image; only a new app or design-system mock may explain its absence"
        )
    proposed = re.fullmatch(image, field(content, "Proposed"))
    if proposed is None:
        raise ValueError("UX Proposed needs a Markdown image of the rendered proposal")
    if baseline and baseline[1] == proposed[1]:
        raise ValueError(
            "A visible UX change needs distinct before and proposed image references"
        )
    for name in ("Capture", "Review"):
        evidence_field(content, name)


def readiness_errors(
    sections: dict[str, str], status: str = "Ready", *, legacy: bool = False
) -> list[str]:
    errors = []
    for name in ("Baseline + execution", "ux_reference", "Verification"):
        try:
            if name == "Baseline + execution":
                proof(sections[name], {"Passed"})
            elif name == "ux_reference":
                ux_proof(sections[name], legacy=legacy)
            else:
                e2e_proof(sections[name], status, legacy=legacy)
        except ValueError as error:
            errors.append(f"{name}: {error}")
    return errors


def no_blockers(text: str) -> bool:
    """'None', optionally followed by a note such as 'None. Scope was settled in chat.'"""
    return re.fullmatch(r"None(?:(?:[.;:]|\s+[—–-])\s.*)?", text) is not None


def draft_handoff(sections: dict[str, str]) -> tuple[str | None, str | None, list[str]]:
    """Validate the declared Draft pause without treating it as authorization."""
    decisions = sections["Decisions + authorization"]
    errors = []
    try:
        handoff = field(decisions, "Handoff")
        blockers = field(decisions, "Blockers")
    except ValueError as error:
        return None, None, [str(error)]
    question = not no_blockers(blockers) and re.search(PLACEHOLDERS, blockers) is None
    if handoff not in HANDOFFS:
        errors.append("Handoff must be Clarification or Approval")
    elif handoff == "Clarification" and not question:
        errors.append("Clarification needs concrete Blockers")
    elif handoff == "Approval" and not no_blockers(blockers) and not question:
        errors.append("Approval Blockers must be None or a concrete decision")
    return handoff, blockers, errors


def planning_feedback(root: Path, changed: set[str]) -> tuple[str, bool]:
    paths = [
        path for path in repository_files(root) if is_plan_path(path.relative_to(root))
    ]
    selected = [path for path in paths if str(path.relative_to(root)) in changed]
    messages = []
    unfinished = False
    for path in selected or paths:
        content = path.read_text()
        if plan_status(content) != "Draft":
            continue
        try:
            sections = plan_sections(content, allow_placeholders=True)
            handoff, blockers, errors = draft_handoff(sections)
            if handoff == "Approval":
                try:
                    plan_sections(content)
                except ValueError as error:
                    errors.append(str(error))
                errors.extend(readiness_errors(sections))
            if not errors and handoff == "Clarification":
                errors = [f"waiting for: {blockers}"]
            elif not errors and handoff == "Approval":
                errors = [
                    "approval handoff prepared; authorization remains outside this plan"
                ]
                if blockers and not no_blockers(blockers):
                    errors.append(f"decisions to resolve: {blockers}")
            else:
                unfinished = True
        except ValueError as error:
            errors = [str(error)]
            unfinished = True
        messages.append(f"{path.relative_to(root)}: " + "; ".join(errors))
    notice = (
        "Hard Eng: Planning incomplete — " + " | ".join(messages) if messages else ""
    )
    return notice, unfinished


def build_in_progress(root: Path, changed: set[str]) -> bool:
    """Ready plans with pending verification are mid-build, not finished."""
    paths = [
        path for path in repository_files(root) if is_plan_path(path.relative_to(root))
    ]
    selected = [path for path in paths if str(path.relative_to(root)) in changed]
    try:
        contents = [path.read_text() for path in selected or paths]
        # Complete plans are validated as usual; the unfinished ones decide.
        active = [
            text for text in contents if plan_status(text) not in {None, "Complete"}
        ]
        return bool(active) and all(
            header_status(text) == "Ready"
            and field(
                plan_sections(text, allow_placeholders=True)["Verification"], "Result"
            )
            == "Pending"
            for text in active
        )
    except (OSError, ValueError, KeyError):
        return False


def validate_plan(path: Path, *, changed: bool = True) -> str:
    """Unchanged Complete plans predate later rules such as the E2E field."""
    content = path.read_text()
    sections = plan_sections(content)
    status = header_status(content)
    if status not in STAGES:
        raise ValueError("plan Status must be Draft, Ready or Complete")
    verification = sections["Verification"]
    if status == "Draft":
        _, _, errors = draft_handoff(sections)
        if errors:
            raise ValueError("; ".join(errors))
        return status
    if not no_blockers(field(sections["Decisions + authorization"], "Blockers")):
        raise ValueError("ready/complete plan has unresolved Blockers")
    errors = readiness_errors(
        sections, status, legacy=status == "Complete" and not changed
    )
    if errors:
        raise ValueError("; ".join(errors))
    if status == "Complete":
        markers = re.findall(
            r"(?m)^\s*(?:[-*+]|\d+[.)])\s+\[([^]\n]*)\](?:\s|$)", content
        )
        if any(marker.lower() != "x" for marker in markers):
            raise ValueError("complete plan has unchecked requirements")
        try:
            proof(verification, {"Passed"})
        except ValueError as error:
            raise ValueError(f"Verification: {error}") from error
    return status


def _validate_shipping(root: Path, path: Path, status: str) -> None:
    content = path.read_text()
    if status in {"Ready", "Complete"} and re.search(
        r"(?im)^\s*(?:[-*+]\s+)?Delivery target:", content
    ):
        policy = load_policy(root)
        if (
            policy is not None
            and not policy["delivery"]
            and re.search(
                r"(?im)^\s*(?:[-*+]\s+)?Delivery target:\s*Deploy\s*$",
                plan_sections(content)["Verification"],
            )
        ):
            raise ValueError("Deploy target requires configured delivery checks")


def plan_stage(root: Path, path: Path, changed: set[str]) -> str:
    try:
        status = validate_plan(path, changed=str(path.relative_to(root)) in changed)
        _validate_shipping(root, path, status)
    except ValueError as error:
        raise ValueError(f"{path.relative_to(root)}: {error}") from error
    return status


def validate_plans(
    root: Path, base: str | None = None, stage: str | None = None
) -> str:
    explicit_stage = stage is not None
    changed = changed_files(root, base or "HEAD")
    if changed is None:
        raise ValueError("Cannot verify plan scope; fetch or supply a valid Git --base")
    if stage is None:
        stage = "Draft" if planning_only(root, changed) else "Complete"
    paths = [
        path for path in repository_files(root) if is_plan_path(path.relative_to(root))
    ]
    applicable = [path for path in paths if str(path.relative_to(root)) in changed]
    if not applicable:
        applicable = [
            path
            for path in paths
            if plan_status(path.read_text()) not in {None, "Complete"}
        ]
    if not applicable and explicit_stage:
        applicable = paths
    if (changed != set() or explicit_stage) and not applicable:
        raise ValueError(
            "repository changes need an applicable PLAN.md; use the HE Plan template"
        )
    statuses = {path: plan_stage(root, path, changed) for path in applicable}
    reached = any(
        STAGES.index(status) >= STAGES.index(stage) for status in statuses.values()
    )
    effective_stage = "Complete"
    for path, status in statuses.items():
        if STAGES.index(status) < STAGES.index(stage):
            # A Draft plan claims no implementation, so it may ride along with finished work.
            if status == "Draft" and reached:
                continue
            raise ValueError(
                f"{path.relative_to(root)}: plan is {status}; this check requires {stage}"
            )
        effective_stage = min(effective_stage, status, key=STAGES.index)
    return stage if explicit_stage or not applicable else effective_stage
