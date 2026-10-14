"""Check plan declarations; evidence truth and authorization still need review."""

import re
import subprocess
from pathlib import Path, PurePosixPath

from dependency_graph import owner_language
from gate_config import Group, changed_files, parse_config, repository_files
from shipping import ShippingError, load_policy

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


def plan_folders(root: Path) -> set[Path]:
    return {
        path.parent.relative_to(root)
        for path in repository_files(root)
        if is_plan_path(path.relative_to(root))
    } - {Path(".")}


def is_plan_capture(name: str, folders: set[Path]) -> bool:
    return Path(name).suffix.lower() in CAPTURES and bool(
        folders.intersection(Path(name).parents)
    )


def planning_only(root: Path, names: set[str]) -> bool:
    """Markdown and captures, such as screenshots, kept in a feature plan's folder."""
    folders = plan_folders(root)
    return all(
        Path(name).suffix.lower() == ".md" or is_plan_capture(name, folders)
        for name in names
    )


def is_documentation(path: Path, owner_language: str | None = None) -> bool:
    """Plans and Markdown, except nested Markdown a JavaScript site may build from."""
    markdown = path.suffix.lower() == ".md" and path.name != "AGENTS.md"
    site = owner_language == "javascript" and path.parent != Path(".")
    return is_plan_path(path) or (markdown and not site)


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
    return re.fullmatch(r"None(?:[.;:](?:\s.*)?|\s+[—–-]\s.*)?", text) is not None


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


MAX_SMALL_LINES = 20
MAX_SMALL_FILES = 3
PROTECTED_NAMES = {
    "pyproject.toml",
    "uv.lock",
    "poetry.lock",
    "package.json",
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "pubspec.yaml",
    "pubspec.lock",
    "hard-eng.gates.json",
    "AGENTS.md",
    "AGENTS.override.md",
    "schema.prisma",
    "appwrite.json",
    "appwrite.config.json",
}
PROTECTED_DIRECTORIES = {".github", ".hooks", ".agents", ".claude", "migrations"}
TEST_DIRECTORIES = {"tests", "test", "__tests__"}


def _is_protected(path: PurePosixPath) -> bool:
    return (
        path.name in PROTECTED_NAMES
        or (path.name.startswith("requirements") and path.suffix == ".txt")
        or path.name.startswith("bun.lock")
        or path.suffix == ".sql"
        or bool(PROTECTED_DIRECTORIES.intersection(path.parts[:-1]))
    )


def _is_test(path: PurePosixPath) -> bool:
    name = path.name
    return (
        bool(TEST_DIRECTORIES.intersection(path.parts[:-1]))
        or name.startswith("test_")
        or name.endswith(("_test.py", "_test.dart"))
        or bool(re.search(r"\.(?:test|spec)\.", name))
    )


def _git_output(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL
    )


def _file_reason(name: str, added: str, removed: str) -> str | None:
    path = PurePosixPath(name)
    if added == "-":
        return f"it changes the binary file {name}"
    if _is_protected(path):
        return f"it changes {name}, which always needs a plan"
    if _is_test(path) and int(removed):
        return f"it removes lines from the test file {name}"
    return None


def default_branch_point(root: Path) -> str | None:
    try:
        policy = load_policy(root, required=False)
    except ShippingError:
        policy = None
    name = policy["base"] if policy else "main"
    for reference in (f"origin/{name}", name):
        try:
            return _git_output(root, "merge-base", "HEAD", reference).strip()
        except (subprocess.CalledProcessError, OSError):
            continue
    return None


def _branch_change(root: Path, point: str) -> tuple[list[str], list[str], list[str]]:
    status = _git_output(
        root, "diff", "--name-status", "--no-renames", "-z", point, "--"
    ).split("\0")
    counts = _git_output(
        root, "diff", "--numstat", "--no-renames", "-z", point, "--"
    ).split("\0")
    untracked = _git_output(
        root, "ls-files", "--others", "--exclude-standard", "-z"
    ).split("\0")
    return status, counts, untracked


def _counted_lines(counts: list[str], names: set[str]) -> int | str:
    """Changed lines in the counted files, or the first reason one of them needs a plan."""
    total = 0
    for entry in filter(None, counts):
        added, removed, name = entry.split("\t", 2)
        if name not in names:
            continue
        if reason := _file_reason(name, added, removed):
            return reason
        total += int(added) + int(removed)
    return total


def configured_packages(root: Path) -> dict[str, Group]:
    try:
        config = parse_config(
            (root / "hard-eng.gates.json").read_text(), require_impact_review=False
        )
    except (OSError, ValueError, TypeError):
        return {}
    return {group["path"]: group for group in config["packages"]}


def size_verdict(root: Path) -> tuple[bool, str]:
    """Whether the whole branch change, not just this session's, is small, and the first reason."""
    point = default_branch_point(root)
    if point is None:
        return False, "the branch point with the default branch cannot be found"
    try:
        status, counts, untracked = _branch_change(root, point)
    except (subprocess.CalledProcessError, OSError):
        return False, "the change cannot be measured"
    names = {name for name in status[1::2] + untracked if name}
    packages = configured_packages(root)

    def documentation(name: str) -> bool:
        return is_documentation(Path(name), owner_language(packages, name))

    if all(documentation(name) for name in names):
        return True, "documentation only"

    names = {
        name
        for name in names
        if not documentation(name) or _is_protected(PurePosixPath(name))
    }
    if any(
        kind[:1] in {"A", "D", "T"} and name in names
        for kind, name in zip(status[0::2], status[1::2], strict=False)
    ) or any(name in names for name in untracked):
        return False, "it adds, deletes or renames a file"
    counted = _counted_lines(counts, names)
    if isinstance(counted, str):
        return False, counted
    total = counted
    if len(names) > MAX_SMALL_FILES:
        return False, f"it changes {len(names)} files, more than {MAX_SMALL_FILES}"
    if total > MAX_SMALL_LINES:
        return False, f"it changes {total} lines, more than {MAX_SMALL_LINES}"
    plural = "file" if len(names) == 1 else "files"
    return True, f"{len(names)} {plural}, {total} changed lines"


def plan_not_needed(root: Path) -> bool:
    small, reason = size_verdict(root)
    if small:
        print(f"Size: small ({reason}); no plan needed.")
    else:
        print(f"Size: big, because {reason}; a plan is needed.")
    return small


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
    if (
        (changed != set() or explicit_stage)
        and not applicable
        and (explicit_stage or not plan_not_needed(root))
    ):
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


ADR_NAME = re.compile(r"docs/adr/\d{4}-[^/]+\.md")
ADR_PREFIXES = re.compile(r"`(?!/)[^`\s]+`(?:, *`(?!/)[^`\s]+`)*")


def decision_field(content: str, name: str) -> str | None:
    found = re.search(rf"(?m)^{name}: *(.*?) *$", content.split("\n## ", 1)[0])
    return found[1] if found else None


def decision_prefixes(content: str) -> list[str]:
    line = decision_field(content, "Applies to") or ""
    return re.findall(r"`([^`]+)`", line) if ADR_PREFIXES.fullmatch(line) else []


def accepted_decisions(root: Path) -> list[tuple[str, str, list[str]]]:
    found = []
    for path in repository_files(root):
        name = path.relative_to(root).as_posix()
        if ADR_NAME.fullmatch(name):
            content = path.read_text(errors="replace")
            prefixes = decision_prefixes(content)
            if prefixes and decision_field(content, "Status") == "Accepted":
                found.append((name, content, prefixes))
    return found


def matched_decisions(root: Path, names: list[str]) -> dict[str, str]:
    """ADR path to its title and Decision text, for each Accepted ADR whose prefix a name starts with."""
    matched = {}
    for name, content, prefixes in accepted_decisions(root):
        if any(file.startswith(prefix) for file in names for prefix in prefixes):
            title = content.splitlines()[0].lstrip("# ")
            decision = re.search(r"(?ms)^## Decision\n(.*?)(?=^## |\Z)", content)
            matched[name] = (
                f"{title} ({name})\n{decision[1].strip() if decision else ''}"
            )
    return matched


def validate_decisions(root: Path, base: str | None = None) -> None:
    point = base or default_branch_point(root) or "HEAD"
    changed = changed_files(root, point)
    if changed is None:
        raise ValueError(
            "Cannot verify decision scope; fetch or supply a valid Git --base"
        )
    found = []
    for name in sorted(changed):
        path = root / name
        if ADR_NAME.fullmatch(name) and path.is_file():
            content = path.read_text(errors="replace")
            superseded = (decision_field(content, "Status") or "").startswith(
                "Superseded"
            )
            if not superseded and not decision_prefixes(content):
                found.append(
                    f"{name} needs an 'Applies to:' line under Status listing path "
                    "prefixes in backticks, such as Applies to: `src/payments/`"
                )
    before: list[str] = []
    try:
        before = _git_output(root, "ls-tree", "-r", "--name-only", "-z", point).split(
            "\0"
        )
    except (subprocess.CalledProcessError, OSError):
        pass
    now = [path.relative_to(root).as_posix() for path in repository_files(root)]
    for name, _, prefixes in accepted_decisions(root):
        found += [
            f"{name}: this change removes the last file under {prefix}; update the "
            "decision's 'Applies to:' line or mark it Superseded"
            for prefix in prefixes
            if any(file.startswith(prefix) for file in before)
            and not any(file.startswith(prefix) for file in now)
        ]
    if found:
        raise ValueError("Decision records are out of date: " + "; ".join(found))
