"""Check plan declarations; evidence truth and authorization still need review."""

import re
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path, PurePosixPath

from gate_config import (
    ALL_ZERO_OBJECT_ID,
    SOURCE_FILE,
    TEST_FOLDERS,
    changed_files,
    repository_files,
)
from project_files import keep

BACKTICKED_TEXT = re.compile(r"`([^`]+)`")
SMALL_SIZE = "Size: small ("
QUICK_PASS = (
    "Hard Eng: quick checks passed; the full check runs the tests and the other gates."
)
LABEL_FILLER = str.maketrans("", "", "_+/ ")
NOT_APPLICABLE_PROOF = re.compile(r"\bN/A — \S")
NOT_APPLICABLE_WORD = re.compile(r"(?i)\bN/A\b")
TITLE_LINE = re.compile(r"(?m)^# \S.+$")
DOCUMENT_TITLE = re.compile(r"(?m)^# \S[^\n]*$")
SURFACE_FIELD = re.compile(r"(?m)^Surface:")
UX_REFERENCE = ".agents/skills/he-plan/references/ux.md"
E2E_FIELD = re.compile(r"(?m)^E2E:")
NOT_APPLICABLE_WITH_TEXT = re.compile(r"N/A — \S.+")
TEST_FILE_SUFFIX = re.compile(r"\.(?:test|spec)\.")
NOT_APPLICABLE_REASON_SEPARATOR = re.compile(r"\s+—\s+\S")
SECTION_HEADING = re.compile(r"(?m)^## +([^\n]+)\n")
DOCUMENT_SECTION = re.compile(r"(?m)^##[ \t]+([^\n]+)\n")
NOT_APPLICABLE_WITH_REASON = re.compile(r"N/A — [^\n]+")
SURFACE_VALUE = re.compile(r"(Existing|New|Mock) — \S.+")
TEST_REFERENCE = re.compile(r"`([^`\s]+?)::(?:[^`\n]*::)?([^`\n]+)`")
DECISION_SECTION = re.compile(r"(?ms)^## Decision\n(.*?)(?=^## |\Z)")
E2E_STATUS_LINE = re.compile(r"(Required|Passed|Delivery|N/A) — (\S.*)")
NONE_VALUE = re.compile(r"(?i:none)(?:[.;:](?:\s.*)?|\s+[—–-]\s.*)?")
DELIVERY_TARGET_FIELD = re.compile(r"(?im)^\s*(?:[-*+]\s+)?Delivery target:")
DEPLOY_DELIVERY_TARGET = re.compile(
    r"(?im)^\s*(?:[-*+]\s+)?Delivery target:\s*Deploy\s*$"
)
BLOCKED_STATUS = re.compile(r"(?i)^(pending|none|blocked|n/a)\b")
CHECKBOX_LABEL = re.compile(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+\[([^]\n]*)\](?:\s|$)")
CHECKBOX_REST = re.compile(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+\[[^]\n]*\](.*)$")
PLACEHOLDER_STATUS = re.compile(
    r"(?i)^(?:pending|none|blocked|n/a|unavailable|not (?:run|inspected|captured))\b"
)

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
BUILD_STEP = "During the build, run this check with --plan-stage Ready"
DRAFT_STEP = f"; files other than plans changed, so get approval for the plan and set its Status to Ready before you build. {BUILD_STEP}"
OTHER_PLAN = ". If that plan is for another task, add a plan for this change."
HANDOFFS = ("Clarification", "Approval")
PLACEHOLDERS = re.compile(
    r"(?im)\[TODO:|^\s*(?:#\s+|[\w +]+:\s*)?(?:TODO(?::[^\n]*)?|TBD|<(?!https?://)[^>\n]+>)\s*$"
)


def is_plan_path(path: Path) -> bool:
    return path.name.lower() == "plan.md" and (
        path.parent == Path(".") or path.parts[0] == "features"
    )


CAPTURES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".mp4", ".mov", ".webm"}


def plan_files(root: Path) -> list[Path]:
    return list(keep("listings", ("plan_files", str(root)), lambda: _plan_files(root)))


def _plan_files(root: Path) -> list[Path]:
    names = subprocess.check_output(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            ":(icase)plan.md",
            ":(icase,glob)features/**/plan.md",
        ],
        cwd=root,
        text=True,
    )
    return [
        root / name
        for name in sorted(set(names.split("\0")) - {""})
        if is_plan_path(Path(name))
        and (root / name).is_file()
        and not (root / name).is_symlink()
    ]


def plan_folders(root: Path) -> set[Path]:
    return {path.parent.relative_to(root) for path in plan_files(root)} - {Path(".")}


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


def report_stage(
    failed: bool, stage: str | None, gates: list[str], quick: bool = False
) -> None:
    if failed:
        where = f" in {', '.join(sorted(gates))}" if gates else ""
        print(f"Hard Eng: verification failed{where}; the next stage is blocked.")
    elif stage == "Ready":
        print(
            "Hard Eng: planning checks passed — ready for build within the authorized scope."
        )
    elif stage == "Complete" and quick:
        print(QUICK_PASS)
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
    if PLACEHOLDER_STATUS.match(value):
        raise ValueError(
            f"plan {name} must describe actual proof, not a pending result"
        )
    return value


def plan_sections(content: str, *, allow_placeholders: bool = False) -> dict[str, str]:
    if not allow_placeholders and PLACEHOLDERS.search(content):
        raise ValueError("plan contains unfilled template placeholders")
    if not TITLE_LINE.search(content):
        raise ValueError("plan needs a title")
    parts = SECTION_HEADING.split(content + "\n")
    headings = [heading.strip() for heading in parts[1::2]]
    sections = dict(zip(headings, parts[2::2]))
    for heading in SECTIONS:
        if headings.count(heading) != 1 or not sections[heading].strip():
            raise ValueError(f"plan needs one filled '## {heading}' section")
    bare = [
        f"line {number}: {line.strip()[:60]}"
        for number, line in enumerate(content.splitlines(), 1)
        if any(
            not NOT_APPLICABLE_REASON_SEPARATOR.match(line[marker.end() :])
            for marker in NOT_APPLICABLE_WORD.finditer(line)
        )
    ]
    if bare:
        raise ValueError(
            f"plan N/A needs an inline reason: N/A — reason; {'; '.join(bare)}; add the reason after each N/A"
        )
    return sections


def e2e_proof(verification: str, status: str, *, legacy: bool = False) -> None:
    if legacy and not E2E_FIELD.search(verification):
        return
    e2e = field(verification, "E2E")
    match = E2E_STATUS_LINE.fullmatch(e2e)
    if match is None:
        raise ValueError(
            "plan E2E needs Required, Passed, Delivery or N/A — concrete journey/evidence or reason"
        )
    if status == "Complete" and match[1] == "Required":
        raise ValueError(
            "complete plan E2E is still Required; run the journey and record Passed evidence"
        )
    if match[1] == "Passed" and BLOCKED_STATUS.match(match[2]):
        raise ValueError("plan E2E Passed needs actual runtime evidence")
    if match[1] == "Delivery" and not DEPLOY_DELIVERY_TARGET.search(verification):
        raise ValueError(
            "delivery E2E requires Delivery target: Deploy and configured delivery checks"
        )


def usability_rules() -> list[tuple[str, list[str]]]:
    """The Usability rule names of the UX reference, each with the unit words its Pass line counts."""
    reference = Path(__file__).resolve().parents[1] / UX_REFERENCE
    try:
        lines = reference.read_text().splitlines()
    except OSError as error:
        raise ValueError(
            f"UX Rules cannot read {UX_REFERENCE}: {error}; restore it with `git checkout HEAD -- {UX_REFERENCE}`"
        ) from error
    start = [n for n, line in enumerate(lines) if line.startswith("- Usability =")]
    rules = []
    for line in lines[start[0] + 1 :] if start else []:
        if not line.startswith("  - "):
            break
        name, marker, rest = line[4:].partition(" (count: ")
        if marker:
            units = rest.partition("):")[0].split(", ")
        else:
            name, units = name.partition(":")[0], list[str]()
        rules.append((name, units))
    if not rules:
        raise ValueError(f"{UX_REFERENCE} has no '- Usability =' list")
    return rules


def rule_lines(content: str) -> list[str]:
    """The rule lines below the `Rules:` label: `-` or `*` bullets, a wrapped line joins the one above, a blank line or a field label ends them."""
    found: list[str] = []
    below = False
    for raw in content.split("\n"):
        line = raw.strip()
        if below and not line and found:
            break
        if below and line[:2] in {"- ", "* "}:
            found.append(line[2:].strip())
        elif below and line:
            head = raw.partition(":")[0]
            if not found or (raw[:1].isupper() and head.replace(" ", "").isalnum()):
                break
            found[-1] += " " + line
        below = below or raw.startswith("Rules:")
    return found


def split_rule_line(line: str) -> tuple[str, str, str, str]:
    """The rule name without its marker, then the verdict, the text and the problem, if any."""
    head, marked, tail = line.partition("): ")
    before = head.partition(" (count")[0]
    if marked and "(count" in head and ": " not in before:
        label, rest = before, tail
    else:
        label, _, rest = line.partition(": ")
    verdict, _, after = rest.partition(" ")
    dash = after.strip()[:1] in {"—", "–", "-"}
    text = after.strip()[1:].strip() if dash else ""
    if verdict not in {"Pass", "Fail", "N/A"}:
        return label, verdict, text, "needs Pass, Fail or N/A"
    problem = "" if text else "needs text after the dash"
    return label, verdict, text, problem if dash else "needs a dash after the verdict"


def ux_rules(content: str) -> None:
    """Each Usability rule gets one Pass, Fail or N/A line; a Fail cannot be a Passed record."""
    if NOT_APPLICABLE_WITH_REASON.fullmatch(content.strip()):
        return
    labels = f"\n{content}".count("\nRules:")
    if labels != 1:
        raise ValueError(
            f"UX Rules is missing; judge the inspected image against each Usability rule of {UX_REFERENCE} and add one line per rule; the field is a line that starts with `Rules:`"
            if not labels
            else f"plan needs one 'Rules:' field, found {labels}"
        )
    rules = dict(usability_rules())
    given: dict[str, list[tuple[str, str]]] = {}
    bad = []
    for line in rule_lines(content):
        label, verdict, text, problem = split_rule_line(line)
        if problem:
            bad.append(f"{label or line[:40]} {problem}")
        given.setdefault(label, []).append((verdict, text))
    wrong = [
        f"{reason}: {', '.join(names)}"
        for reason, names in (
            ("not a rule", [label for label in given if label not in rules]),
            ("no line", [label for label in rules if label not in given]),
            ("two lines", [label for label, lines in given.items() if len(lines) > 1]),
            ("bad line", bad),
        )
        if names
    ]
    if wrong:
        raise ValueError(
            "UX Rules needs one `- <rule>: Pass|Fail|N/A — text` line for each Usability rule; "
            + "; ".join(wrong)
            + f"; add a line for each rule of {UX_REFERENCE}"
            + (
                "; the rule lines stand in one block below `Rules:` with no empty line between them"
                if any(w.startswith("no line") for w in wrong)
                else ""
            )
        )
    for label, ((verdict, text),) in given.items():
        if verdict == "Fail":
            raise ValueError(
                f"UX Rules: {label} is Fail; fix the design, inspect it again and judge it again before it is shown"
            )
        if verdict == "Pass" and (absent := uncounted(text, rules[label])):
            example = ", ".join(f"3 {unit}" for unit in rules[label])
            raise ValueError(
                f"UX Rules: {label} needs a number before the word {', '.join(absent)}; write the line like `- {label}: Pass — {example}`"
            )


def uncounted(text: str, units: list[str]) -> list[str]:
    """The unit words that have no number directly before them in the Pass text."""
    words = [word.strip(",.;:()") for word in text.lower().split()]
    return [
        unit
        for unit in units
        if not any(
            word in {unit, unit.removesuffix("s")} and words[n - 1].isdigit()
            for n, word in enumerate(words)
            if n
        )
    ]


def judged_rules(content: str, age: Callable[[], bool] | None) -> None:
    """A Complete plan untouched since the last Hard Eng update may predate the Rules field."""
    try:
        ux_rules(content)
    except ValueError:
        if "\nRules:" in f"\n{content}" or age is None or age():
            raise


def ux_proof(
    content: str, *, legacy: bool = False, age: Callable[[], bool] | None = None
) -> None:
    if NOT_APPLICABLE_WITH_REASON.fullmatch(content.strip()):
        return
    proof(content, {"Passed"})
    image = r"!\[[^\]\n]*\]\((\S[^)\n]*)\)"
    if not re.search(image, content):
        raise ValueError(
            "UX evidence needs a Markdown image reference to the rendered proposal"
        )
    if legacy and not SURFACE_FIELD.search(content):
        return
    surface = field(content, "Surface")
    if not SURFACE_VALUE.fullmatch(surface):
        raise ValueError(
            "UX Surface needs Existing, New or Mock — actual screen or design-system owner"
        )
    before = field(content, "Before")
    baseline = re.fullmatch(image, before)
    if baseline is None and not (
        surface.startswith(("New — ", "Mock — "))
        and NOT_APPLICABLE_WITH_TEXT.fullmatch(before)
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
    if not legacy:
        judged_rules(content, age)


def readiness_errors(
    sections: dict[str, str],
    status: str = "Ready",
    *,
    legacy: bool = False,
    age: Callable[[], bool] | None = None,
) -> list[str]:
    errors = []
    for name in ("Baseline + execution", "ux_reference", "Verification"):
        try:
            if name == "Baseline + execution":
                proof(sections[name], {"Passed"})
            elif name == "ux_reference":
                ux_proof(sections[name], legacy=legacy, age=age)
            else:
                e2e_proof(sections[name], status, legacy=legacy)
        except ValueError as error:
            errors.append(f"{name}: {error}")
    return errors


def no_blockers(text: str) -> bool:
    """'None', optionally followed by a note such as 'None. Scope was settled in chat.'"""
    return NONE_VALUE.fullmatch(text) is not None


def draft_handoff(sections: dict[str, str]) -> tuple[str | None, str | None, list[str]]:
    """Validate the declared Draft pause without treating it as authorization."""
    decisions = sections["Decisions + authorization"]
    errors = []
    try:
        handoff = field(decisions, "Handoff")
        blockers = field(decisions, "Blockers")
    except ValueError as error:
        return None, None, [str(error)]
    question = not no_blockers(blockers) and PLACEHOLDERS.search(blockers) is None
    if handoff not in HANDOFFS:
        errors.append("Handoff must be Clarification or Approval")
    elif handoff == "Clarification" and not question:
        errors.append("Clarification needs concrete Blockers")
    elif handoff == "Approval" and not no_blockers(blockers) and not question:
        errors.append("Approval Blockers must be None or a concrete decision")
    return handoff, blockers, errors


def _draft_errors(content: str) -> tuple[list[str], bool]:
    """What stops a Draft plan, and whether that leaves it unfinished."""
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
            return [f"waiting for: {blockers}"], False
        if errors:
            return errors, True
        errors = ["approval handoff prepared; authorization remains outside this plan"]
        if blockers and not no_blockers(blockers):
            errors.append(f"decisions to resolve: {blockers}")
        return errors, False
    except ValueError as error:
        return [str(error)], True


def planning_feedback(root: Path, changed: set[str]) -> tuple[str, bool]:
    paths = plan_files(root)
    selected = [path for path in paths if str(path.relative_to(root)) in changed]
    messages = []
    unfinished = False
    for path in selected or paths:
        content = path.read_text()
        if plan_status(content) != "Draft":
            continue
        errors, stuck = _draft_errors(content)
        if stuck and not selected:
            from change_size import held_by_base

            if held_by_base(root, path):
                continue
        unfinished |= stuck
        messages.append(f"{path.relative_to(root)}: " + "; ".join(errors))
    notice = (
        "Hard Eng: Planning incomplete — " + " | ".join(messages) if messages else ""
    )
    return notice, unfinished


def build_in_progress(root: Path, changed: set[str]) -> bool:
    """Ready plans with pending verification are mid-build, not finished."""
    paths = plan_files(root)
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


def touched_since_update(path: Path) -> bool:
    """A long-lived branch differs from its base in every plan; only edits after the last Hard Eng update count."""
    root = path.parent
    try:
        if _git_output(root, "status", "--porcelain", "--", path.name).strip():
            return True
        updated = _git_output(
            root, "log", "-1", "--format=%cI", "--", f":/{SOURCE_FILE}"
        ).strip()
        written = _git_output(
            root, "log", "-1", "--format=%aI", "--", path.name
        ).strip()
    except (subprocess.CalledProcessError, OSError):
        return True
    return (
        not updated
        or not written
        or datetime.fromisoformat(written) > datetime.fromisoformat(updated)
    )


def reasoned(value: str, name: str) -> None:
    lowered = value.lower()
    if lowered.startswith("none") and not lowered[4:].strip(" \t—–-.:,;"):
        raise ValueError(f"'{name}:' needs a reason; write `None — <reason>`")


def claimed_tests(sections: dict[str, str]) -> dict[str, list[tuple[str, str]]]:
    """The `path::test` names of test files in each Same cause and Retro value, by field."""
    found: dict[str, list[tuple[str, str]]] = {}
    for text in (sections["Repository context"], sections["Verification"]):
        name = ""
        for line in text.split("\n"):
            label = line.partition(":")[0]
            titled = "A" <= label[:1] <= "Z" and label.translate(LABEL_FILLER).isalnum()
            if line[:1] == "#" or (titled and label != line):
                name = label if label in {"Same cause", "Retro"} else ""
            if name:
                found.setdefault(name, []).extend(
                    (path, test.split("[", 1)[0])
                    for path, test in TEST_REFERENCE.findall(line)
                    if _is_test(PurePosixPath(path))
                )
    return found


def newer_fields(
    sections: dict[str, str],
    status: str,
    *,
    legacy: bool,
    changed: bool,
    age: Callable[[], bool] | None,
) -> None:
    """Old Complete plans skip Same cause; Single source and Retro bind only edited plans."""
    if not legacy:
        reasoned(field(sections["Repository context"], "Same cause"), "Same cause")
        acceptance_tests(sections)
    if not changed:
        return
    try:
        field(sections["Repository context"], "Single source")
        if status == "Complete":
            reasoned(field(sections["Verification"], "Retro"), "Retro")
    except ValueError:
        if age is None or age():
            raise


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
    asked: list[bool] = []

    def age() -> bool:
        asked[:] = asked or [touched_since_update(path)]
        return asked[0]

    soft = age if status == "Complete" else None
    errors = readiness_errors(sections, status, legacy=legacy, age=soft)
    if errors:
        raise ValueError("; ".join(errors))
    newer_fields(sections, status, legacy=legacy, changed=changed, age=soft)
    if status == "Complete":
        markers = CHECKBOX_LABEL.findall(content)
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
    from requirement_registry import REQUIREMENT_ID

    references: list[tuple[str, str]] = []
    requirements: set[str] = set()
    for line in CHECKBOX_REST.findall(sections["Acceptance + steps"]):
        found = TEST_REFERENCE.findall(line)
        named = set(REQUIREMENT_ID.findall(line))
        if not found and not named and not NOT_APPLICABLE_PROOF.search(line):
            raise ValueError(
                "Acceptance + steps line needs a `path::test name` reference, "
                f"a requirement ID or N/A — reason:{line[:80]}"
            )
        references.extend((path, name.split("[", 1)[0]) for path, name in found)
        requirements |= named
    return references, requirements


def untested_requirements(root: Path, requirements: set[str]) -> list[str]:
    from requirement_registry import registry_entries, requirement_tests

    entries, _ = registry_entries(root)
    tests = requirement_tests(root)
    return sorted(
        requirement
        for requirement in requirements
        if entries.get(requirement, ("retired",))[0] == "retired"
        or requirement not in tests
    )


HASH_COMMENT_SUFFIXES = {".py", ".rb", ".sh", ".bash", ".zsh", ".pl", ".ex", ".exs"}


def uncommented(file: Path) -> str:
    """The file's text without whole-line comments, which cannot define a test."""
    marker = "#" if file.suffix in HASH_COMMENT_SUFFIXES else "//"
    return "\n".join(
        line
        for line in file.read_text().splitlines()
        if not line.lstrip().startswith(marker)
    )


def missing_tests(root: Path, references: list[tuple[str, str]]) -> list[str]:
    missing = []
    for path, name in references:
        file = (root / path).resolve()
        quoted = rf"[\"'`]{re.escape(name)}[\"'`]"
        definition = {
            ".py": rf"\bdef\s+{re.escape(name)}\s*\(",
            ".swift": rf"\bfunc\s+{re.escape(name)}\s*\(|{quoted}",
        }.get(file.suffix, quoted)
        if not (
            file.is_relative_to(root.resolve())
            and _is_test(PurePosixPath(path))
            and file.is_file()
            and re.search(definition, uncommented(file))
        ):
            missing.append(f"{path}::{name}")
    return missing


def _validate_shipping(root: Path, path: Path, status: str) -> None:
    content = path.read_text()
    if status in {"Ready", "Complete"} and DELIVERY_TARGET_FIELD.search(content):
        from shipping import plan_target_problem

        verification = plan_sections(content)["Verification"]
        if problem := plan_target_problem(root, verification):
            raise ValueError(problem)


def plan_stage(root: Path, path: Path, changed: set[str]) -> str:
    try:
        edited = str(path.relative_to(root)) in changed
        status = validate_plan(path, changed=edited)
        if status == "Complete" and edited:
            sections = plan_sections(path.read_text())
            references, requirements = acceptance_tests(sections)
            named = {"acceptance": references, **claimed_tests(sections)}
            for line, found in named.items():
                if missing := missing_tests(root, found):
                    raise ValueError(
                        f"{line} names tests that do not exist: " + ", ".join(missing)
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


def _is_test(path: PurePosixPath) -> bool:
    name = path.name
    return (
        bool(TEST_FOLDERS.intersection(path.parts[:-1]))
        or name.startswith("test_")
        or name.endswith(("_test.py", "_test.dart", "Tests.swift"))
        or bool(TEST_FILE_SUFFIX.search(name))
    )


def _git_output(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL
    )


def release_references(root: Path) -> tuple[str, ...]:
    return keep(
        "references", ("release_references", str(root)), lambda: _references(root)
    )


def _references(root: Path) -> tuple[str, ...]:
    from shipping import ShippingError, load_policy

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
    return keep("references", ("branch_point", str(root)), lambda: _point(root))


def _point(root: Path) -> str | None:
    for reference in release_references(root):
        try:
            return _git_output(root, "merge-base", "HEAD", reference).strip()
        except (subprocess.CalledProcessError, OSError):
            continue
    return None


def validate_plans(
    root: Path, base: str | None = None, stage: str | None = None
) -> str:
    from change_size import (
        judged_plans,
        judged_point,
        plan_not_needed,
        update_only,
    )

    explicit_stage = stage is not None
    typed = base is None
    base = base or judged_point(root)
    changed = changed_files(root, base or "HEAD")
    if changed is None:
        raise ValueError("Cannot verify plan scope; fetch or supply a valid Git --base")
    if stage is None:
        stage = "Draft" if planning_only(root, changed) else "Complete"
    # Unrelated open plans must not block a verified Hard Eng update branch.
    if (
        base is not None
        and not explicit_stage
        and changed
        and update_only(root, base, changed)
    ):
        print("Plan: only files the verified Hard Eng update wrote; no plan needed.")
        return stage
    changed, paths, applicable = judged_plans(root, base, changed)
    asks_size = bool(changed) and not any(
        str(path.relative_to(root)) in changed for path in paths
    )
    if asks_size and plan_not_needed(root):
        return stage
    if not applicable and explicit_stage and not changed:
        applicable = paths
    if (
        (changed != set() or explicit_stage)
        and not applicable
        and (asks_size or not plan_not_needed(root))
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
            steps = {"Draft": DRAFT_STEP, "Ready": f". {BUILD_STEP}" * typed}
            step = steps[status] if stage == "Complete" and not explicit_stage else ""
            raise ValueError(
                f"{path.relative_to(root)}: plan is {status}; this check requires {stage}{step}{OTHER_PLAN * asks_size}"
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
    return BACKTICKED_TEXT.findall(line) if ADR_PREFIXES.fullmatch(line) else []


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
            decision = DECISION_SECTION.search(content)
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
    span = "HEAD" if ALL_ZERO_OBJECT_ID.fullmatch(point) else f"{point}..HEAD"
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


def validate_records(root: Path, base: str | None) -> None:
    validate_decisions(root, base)
    validate_attribution(root, base)
    from requirement_registry import validate_requirements

    validate_requirements(root)


def validate_documents(root: Path) -> None:
    for name, required in (
        ("PRODUCT.md", ("Users", "Problem", "Product Purpose", "Boundaries")),
        ("DESIGN.md", ("Overview", "Components", "Do's and Don'ts")),
    ):
        path = root / name
        if not path.is_file():
            raise ValueError(f"{name} is required; fill it from the actual project")
        content = path.read_text().strip()
        if not content:
            raise ValueError(f"{name} is empty; fill it from the actual project")
        if "[todo:" in content.lower():
            raise ValueError(f"{name} contains unfilled template prompts")
        if not DOCUMENT_TITLE.search(content):
            raise ValueError(f"{name} needs a document title using '# Title'")
        parts = DOCUMENT_SECTION.split(content + "\n")
        sections = dict(zip((heading.strip() for heading in parts[1::2]), parts[2::2]))
        for heading in required:
            if not sections.get(heading, "").strip():
                raise ValueError(f"{name} needs a filled '## {heading}' section")
        order = [
            heading.strip() for heading in parts[1::2] if heading.strip() in required
        ]
        if order != list(required):
            raise ValueError(
                f"{name} sections must follow the template order without duplicates"
            )
