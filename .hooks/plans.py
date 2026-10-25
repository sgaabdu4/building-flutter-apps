"""Check plan declarations; evidence truth and authorization still need review."""

import re
import subprocess
from pathlib import Path, PurePosixPath

from gate_config import Group, changed_files, repository_files
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


def report_stage(failed: bool, stage: str | None, gates: list[str]) -> None:
    if failed:
        where = f" in {', '.join(sorted(gates))}" if gates else ""
        print(f"Hard Eng: verification failed{where}; the next stage is blocked.")
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
    legacy = status == "Complete" and not changed
    errors = readiness_errors(sections, status, legacy=legacy)
    if errors:
        raise ValueError("; ".join(errors))
    if not legacy:
        field(sections["Repository context"], "Same cause")
        acceptance_tests(sections)
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


def acceptance_tests(
    sections: dict[str, str],
) -> tuple[list[tuple[str, str]], set[str]]:
    """Each acceptance checkbox names its `path::test` or requirement ID, or N/A — reason."""
    references: list[tuple[str, str]] = []
    requirements: set[str] = set()
    for line in re.findall(
        r"(?m)^\s*(?:[-*+]|\d+[.)])\s+\[[^]\n]*\](.*)$",
        sections["Acceptance + steps"],
    ):
        found = re.findall(r"`([^`\s]+?)::(?:[^`\n]*::)?([^`\n]+)`", line)
        named = set(REQUIREMENT_ID.findall(line))
        if not found and not named and not re.search(r"\bN/A — \S", line):
            raise ValueError(
                "Acceptance + steps line needs a `path::test name` reference, "
                f"a requirement ID or N/A — reason:{line[:80]}"
            )
        references.extend((path, name.split("[", 1)[0]) for path, name in found)
        requirements |= named
    return references, requirements


def untested_requirements(root: Path, requirements: set[str]) -> list[str]:
    entries, _ = registry_entries(root)
    tests = requirement_tests(root)
    return sorted(
        requirement
        for requirement in requirements
        if entries.get(requirement, ("retired",))[0] == "retired"
        or requirement not in tests
    )


def missing_tests(root: Path, references: list[tuple[str, str]]) -> list[str]:
    missing = []
    for path, name in references:
        file = (root / path).resolve()
        definition = (
            rf"\bdef\s+{re.escape(name)}\s*\("
            if file.suffix == ".py"
            else rf"[\"'`]{re.escape(name)}[\"'`]"
        )
        if not (
            file.is_relative_to(root.resolve())
            and _is_test(PurePosixPath(path))
            and file.is_file()
            and re.search(definition, file.read_text())
        ):
            missing.append(f"{path}::{name}")
    return missing


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
        edited = str(path.relative_to(root)) in changed
        status = validate_plan(path, changed=edited)
        if status == "Complete" and edited:
            sections = plan_sections(path.read_text())
            references, requirements = acceptance_tests(sections)
            if missing := missing_tests(root, references):
                raise ValueError(
                    "acceptance names tests that do not exist: " + ", ".join(missing)
                )
            if untested := untested_requirements(root, requirements):
                raise ValueError(
                    "acceptance names unknown, retired or untested requirements: "
                    + ", ".join(untested)
                )
        _validate_shipping(root, path, status)
    except ValueError as error:
        raise ValueError(f"{path.relative_to(root)}: {error}") from error
    return status


TEST_DIRECTORIES = {"tests", "test", "__tests__"}


def _is_test(path: PurePosixPath) -> bool:
    name = path.name
    return (
        bool(TEST_DIRECTORIES.intersection(path.parts[:-1]))
        or name.startswith("test_")
        or name.endswith(("_test.py", "_test.dart", "Tests.swift"))
        or bool(re.search(r"\.(?:test|spec)\.", name))
    )


def _git_output(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL
    )


def release_references(root: Path) -> tuple[str, ...]:
    try:
        policy = load_policy(root, required=False)
    except ShippingError:
        policy = None
    if policy:
        return f"origin/{policy['base']}", policy["base"]
    try:
        local = _git_output(root, "config", "--get", "init.defaultBranch").strip()
    except (subprocess.CalledProcessError, OSError):
        local = "master"  # Git's own default when init.defaultBranch is unset.
    return "origin/main", "main", "origin/HEAD", local


def default_branch_point(root: Path) -> str | None:
    for reference in release_references(root):
        try:
            return _git_output(root, "merge-base", "HEAD", reference).strip()
        except (subprocess.CalledProcessError, OSError):
            continue
    return None


def applicable_plans(root: Path, paths: list[Path], changed: set[str]) -> list[Path]:
    applicable = [path for path in paths if str(path.relative_to(root)) in changed]
    return applicable or [
        path
        for path in paths
        if plan_status(path.read_text()) not in {None, "Complete"}
    ]


def _revision(root: Path, reference: str) -> str | None:
    try:
        return _git_output(
            root, "rev-parse", "--verify", "-q", f"{reference}^{{commit}}"
        )
    except (subprocess.CalledProcessError, OSError):
        return None


def released_plans(root: Path, base: str | None) -> set[str]:
    """Plans changed since the release base, so a feature check sees what the release checks."""
    tips = {_revision(root, reference) for reference in release_references(root)}
    point = default_branch_point(root)
    if point is None or _revision(root, base or "HEAD") in tips:
        return set()
    return {
        name for name in changed_files(root, point) or () if is_plan_path(Path(name))
    }


def plan_tests(root: Path, base: str | None) -> set[str]:
    """Test names that the active plans' acceptance lines depend on."""
    changed = (changed_files(root, base or "HEAD") or set()) | released_plans(
        root, base
    )
    paths = [
        path for path in repository_files(root) if is_plan_path(path.relative_to(root))
    ]
    names = set()
    for path in applicable_plans(root, paths, changed):
        content = path.read_text()
        if plan_status(content) in {"Ready", "Complete"}:
            sections = plan_sections(content, allow_placeholders=True)
            references, requirements = acceptance_tests(sections)
            names.update(name for _, name in references)
            tests = requirement_tests(root) if requirements else {}
            for requirement in requirements:
                names.update(name for _, _, name in tests.get(requirement, []))
    return names


def plan_skips(root: Path, base: str | None, groups: list[Group], since: float) -> bool:
    from reports import skipped_tests

    skipped = sorted(plan_tests(root, base) & skipped_tests(root, groups, since))
    if skipped:
        print("FAIL plan acceptance tests were skipped: " + ", ".join(skipped))
    return bool(skipped)


def validate_plans(
    root: Path, base: str | None = None, stage: str | None = None
) -> str:
    from change_size import plan_not_needed

    explicit_stage = stage is not None
    changed = changed_files(root, base or "HEAD")
    if changed is None:
        raise ValueError("Cannot verify plan scope; fetch or supply a valid Git --base")
    if stage is None:
        stage = "Draft" if planning_only(root, changed) else "Complete"
    if base is not None and not explicit_stage and changed:
        from change_size import update_written

        # Unrelated open plans must not block a verified Hard Eng update branch.
        if not changed - update_written(root, base):
            print(
                "Plan: only files the verified Hard Eng update wrote; no plan needed."
            )
            return stage
    changed |= released_plans(root, base)
    paths = [
        path for path in repository_files(root) if is_plan_path(path.relative_to(root))
    ]
    applicable = applicable_plans(root, paths, changed)
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
        raise ValueError(
            "HE-ADR-SCOPE: Decision records are out of date: " + "; ".join(found)
        )


def validate_attribution(root: Path, base: str | None = None) -> None:
    from agent_hooks import attribution_off, reject_attribution

    if (
        not attribution_off(root, "commit")
        or subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", "HEAD"],
            cwd=root,
            stdout=subprocess.DEVNULL,
            check=False,
        ).returncode
    ):
        return
    point = base or default_branch_point(root) or "HEAD"
    span = "HEAD" if re.fullmatch(r"0{40}|0{64}", point) else f"{point}..HEAD"
    try:
        log = _git_output(root, "log", "--format=%x1e%h%x1f%ae%x1f%ce%n%B", span)
    except subprocess.CalledProcessError as error:
        raise ValueError(
            "Cannot verify commit attribution; fetch or supply a valid Git --base"
        ) from error
    for entry in filter(None, log.split("\x1e")):
        header, _, text = entry.partition("\n")
        revision, *emails = header.split("\x1f")
        if any(CLAUDE_EMAIL.fullmatch(email) for email in emails):
            raise ValueError(f"Commit {revision} has a Claude author or committer")
        reject_attribution(root, "commit", text, f"Commit {revision}")


CLAUDE_EMAIL = re.compile(r"noreply@anthropic\.com", re.IGNORECASE)
REQUIREMENT_FILES = (
    ".agents/skills/he/references/requirements.md",
    "docs/requirements.md",
)
REQUIREMENT_ID = re.compile(r"\b(?:HE|REQ)-[A-Z0-9]+(?:-[A-Z0-9]+)+\b")
TEST_CALL = re.compile(r"""\b(?:test|it|testWidgets)\(\s*(['"])(.+?)\1""")
PYTHON_TEST = re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)")
Reference = tuple[str, int, str]


def registry_entries(root: Path) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """Requirement ID to its proof kind ('retired' when retired) and definition."""
    entries: dict[str, tuple[str, str]] = {}
    errors = []
    for name in REQUIREMENT_FILES:
        path = root / name
        chunks = f"\n{path.read_text()}".split("\n## ") if path.is_file() else []
        for chunk in chunks[1:]:
            heading, _, body = chunk.partition("\n")
            requirement = heading.split(" — ", 1)[0].strip()
            if not REQUIREMENT_ID.fullmatch(requirement):
                continue
            if requirement in entries:
                errors.append(f"{requirement} is defined more than once")
                continue
            if re.search(r"(?m)^Status: Retired\b", body):
                entries[requirement] = ("retired", "")
                continue
            proof = re.search(r"(?m)^Proof: (check|guidance) *$", body)
            definition = " ".join(
                line.strip()
                for line in body.splitlines()
                if line.strip() and not line.startswith(("Proof:", "Status:"))
            )
            if not proof or not definition:
                errors.append(
                    f"{requirement} needs a definition and a 'Proof: check' or "
                    "'Proof: guidance' line"
                )
            entries[requirement] = (proof[1] if proof else "", definition)
    return entries, errors


def requirement_references(root: Path) -> list[tuple[str, int, str]]:
    """Each tracked or new file line that names a requirement ID: path, line, text."""
    try:
        output = _git_output(
            root,
            "grep",
            "--untracked",
            "-I",
            "-n",
            "-z",
            "-E",
            r"(HE|REQ)-[A-Z0-9]+(-[A-Z0-9]+)+",
        )
    except subprocess.CalledProcessError as error:
        if error.returncode == 1:
            return []
        raise
    found = []
    for row in output.splitlines():
        path, line, text = row.split("\0", 2)
        heading = path in REQUIREMENT_FILES and text.startswith("## ")
        if not heading:
            found.append((path, int(line), text))
    return found


def covering_test(root: Path, path: str, line: int, text: str) -> str | None:
    """The test whose name, or Python docstring first line, holds the reference."""
    if not _is_test(PurePosixPath(path)):
        return None
    called = TEST_CALL.search(text)
    if called:
        return called[2]
    if not text.strip().startswith(('"""', 'r"""')):
        return None
    lines = (root / path).read_text(errors="replace").splitlines()
    for previous in reversed(lines[max(0, line - 6) : line - 1]):
        defined = PYTHON_TEST.match(previous)
        if defined:
            return defined[1]
    return None


def requirement_tests(root: Path) -> dict[str, list[Reference]]:
    """Requirement ID to each covering test: path, line, test name as reported."""
    tests: dict[str, list[Reference]] = {}
    for path, line, text in requirement_references(root):
        name = covering_test(root, path, line, text)
        if name is None:
            continue
        for requirement in REQUIREMENT_ID.findall(text):
            tests.setdefault(requirement, []).append((path, line, name))
    return tests


def unproven_requirements(
    root: Path, entries: dict[str, tuple[str, str]], references: list[Reference]
) -> list[str]:
    installed = (root / ".hooks/hard-eng-source.json").is_file() or not (
        root / "setup.py"
    ).is_file()
    tests = requirement_tests(root)
    enforced: set[str] = set()
    linked: set[str] = set()
    for path, _, text in references:
        named = set(REQUIREMENT_ID.findall(text))
        if path.endswith(".md"):
            skill = path.startswith(".agents/skills/") or path.endswith("AGENTS.md")
            linked |= named if skill else set()
        elif path not in REQUIREMENT_FILES and not _is_test(PurePosixPath(path)):
            enforced |= named
    errors = []
    for requirement, (proof, _) in entries.items():
        if installed and requirement.startswith("HE-"):
            continue
        if proof == "check" and requirement not in tests:
            errors.append(f"{requirement} has no test naming it")
        if proof == "check" and requirement not in enforced:
            errors.append(f"{requirement} has no enforcing source that names it")
        if proof == "guidance" and requirement not in linked:
            errors.append(f"{requirement} has no skill or AGENTS.md link")
    return errors


def normalized_words(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9%]+", text.lower()))


def copied_requirements(root: Path, entries: dict[str, tuple[str, str]]) -> list[str]:
    sentences = [
        (requirement, normalized_words(sentence))
        for requirement, (_, definition) in entries.items()
        for sentence in re.split(r"(?<=[.!?])\s+", definition)
        if len(sentence.split()) >= 8
    ]
    errors: list[str] = []
    for path in repository_files(root):
        name = path.relative_to(root).as_posix()
        if path.suffix.lower() != ".md" or name in REQUIREMENT_FILES:
            continue
        content = f" {normalized_words(path.read_text(errors='replace'))} "
        errors += [
            f"{name} copies {requirement}; link the ID instead"
            for requirement in sorted(
                {found for found, sentence in sentences if f" {sentence} " in content}
            )
        ]
    return errors


def validate_requirements(root: Path) -> None:
    entries, errors = registry_entries(root)
    if not entries and not errors:
        return
    references = requirement_references(root)
    for path, line, text in references:
        for requirement in REQUIREMENT_ID.findall(text):
            proof = entries.get(requirement, ("unknown", ""))[0]
            if proof in {"unknown", "retired"}:
                errors.append(f"{path}:{line} names {proof} {requirement}")
    errors += unproven_requirements(root, entries, references)
    errors += copied_requirements(root, entries)
    if errors:
        raise ValueError(
            "HE-REQUIREMENT-REGISTRY: Requirement registry is out of date: "
            + "; ".join(errors)
        )


def validate_records(root: Path, base: str | None) -> None:
    validate_decisions(root, base)
    validate_attribution(root, base)
    validate_requirements(root)
