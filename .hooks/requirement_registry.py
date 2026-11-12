"""Check the requirement registry and the tests that prove each requirement."""

import re
import subprocess
from pathlib import Path, PurePosixPath

from gate_config import SOURCE_FILE, repository_files
from plans import _git_output, _is_test

RETIRED_STATUS = re.compile(r"(?m)^Status: Retired\b")
PROOF_KIND = re.compile(r"(?m)^Proof: (check|guidance) *$")
LOWERCASE_TOKEN = re.compile(r"[a-z0-9%]+")
SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
REQUIREMENT_FILES = (
    ".agents/skills/he/references/requirements.md",
    "docs/requirements.md",
)
REQUIREMENT_ID = re.compile(
    r"\b(?:HE-[A-Z0-9]+(?:-[A-Z0-9]+)*|REQ-[A-Z0-9]+(?:-[A-Z0-9]+)+)\b"
)
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
                if requirement.startswith(("HE-", "REQ-")):
                    errors.append(
                        f"{name}: heading {requirement} is not a valid requirement ID; "
                        "see the ID format at the top of the Hard Eng requirements"
                    )
                continue
            if requirement in entries:
                errors.append(f"{requirement} is defined more than once")
                continue
            if RETIRED_STATUS.search(body):
                entries[requirement] = ("retired", "")
                continue
            proof = PROOF_KIND.search(body)
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
            r"(HE|REQ)-[A-Z0-9]",
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
    installed = (root / SOURCE_FILE).is_file() or not (root / "setup.py").is_file()
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
    return " ".join(LOWERCASE_TOKEN.findall(text.lower()))


def copied_requirements(root: Path, entries: dict[str, tuple[str, str]]) -> list[str]:
    sentences = [
        (requirement, normalized_words(sentence))
        for requirement, (_, definition) in entries.items()
        for sentence in SENTENCE_BOUNDARY.split(definition)
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
            # A one-part token such as a codec name is an ID only when the registry holds it.
            if proof == "retired" or proof == "unknown" and requirement.count("-") > 1:
                errors.append(f"{path}:{line} names {proof} {requirement}")
    errors += unproven_requirements(root, entries, references)
    errors += copied_requirements(root, entries)
    if errors:
        raise ValueError(
            "HE-REQUIREMENT-REGISTRY: Requirement registry is out of date: "
            + "; ".join(errors)
        )
