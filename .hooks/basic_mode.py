"""Basic mode for projects whose language has no built-in package template."""

import json
from pathlib import Path

from gate_config import Gate, GateConfig, repository_files

MANIFEST_LABELS = {
    "go.mod": "Go",
    "Cargo.toml": "Rust",
    "pom.xml": "Java/Kotlin",
    "build.gradle": "Java/Kotlin",
    "build.gradle.kts": "Java/Kotlin",
    "Gemfile": "Ruby",
    "composer.json": "PHP",
    "Package.swift": "Swift",
    "CMakeLists.txt": "C/C++",
    "Makefile": "C/C++",
}
SUFFIX_LABELS = {
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java/Kotlin",
    ".kt": "Java/Kotlin",
    ".kts": "Java/Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".csproj": ".NET",
    ".sln": ".NET",
    ".cs": ".NET",
    ".swift": "Swift",
    ".c": "C/C++",
    ".cc": "C/C++",
    ".cpp": "C/C++",
    ".h": "C/C++",
    ".hpp": "C/C++",
}
TRIVIAL_NAMES = {".gitignore", ".gitattributes", ".editorconfig"}
OSV_LOCKFILES = {
    "go.mod",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "packages.lock.json",
    "Package.resolved",
    "gradle.lockfile",
}
GENERATED_DIRECTORIES = {".agents", ".hooks", ".claude", ".codex", ".husky"}
FALLBACK_LABEL = "this language"


def trivial(path: Path) -> bool:
    name = path.name.upper()
    return (
        path.name in TRIVIAL_NAMES
        or path.suffix.lower() == ".md"
        or name.startswith(("README", "LICENSE"))
    )


def project_files(root: Path, files: list[Path]) -> list[Path]:
    return [
        path
        for path in files
        if not GENERATED_DIRECTORIES & set(path.relative_to(root).parts)
        and not trivial(path)
    ]


def language_label(root: Path, files: list[Path]) -> str | None:
    """None when the repository holds no project files; the fallback when unrecognised."""
    found = project_files(root, files)
    if not found:
        return None
    labels = [
        MANIFEST_LABELS[path.name] for path in found if path.name in MANIFEST_LABELS
    ]
    labels += [
        SUFFIX_LABELS[path.suffix] for path in found if path.suffix in SUFFIX_LABELS
    ]
    names = {path.name for path in found}
    for name, label in MANIFEST_LABELS.items():
        if name in names and label in labels:
            return label
    return labels[0] if labels else FALLBACK_LABEL


def basic_config(source: Path, root: Path, files: list[Path]) -> GateConfig | None:
    if language_label(root, files) is None:
        return None
    template = json.loads(
        (source / ".agents/skills/he/templates/hard-eng.python.json").read_text()
    )
    shared: list[Gate] = [
        gate
        for gate in template["shared"]
        if gate["role"] in {"secrets-files", "secrets-history"}
    ]
    shared.append(
        {
            "name": "security",
            "role": "security",
            "parallel": True,
            "command": [
                "semgrep",
                "scan",
                "--config",
                "p/default",
                "--exclude=.agents",
                "--exclude=.hooks",
                "--jobs",
                "2",
                "--error",
                "--strict",
                "--time",
                "--json",
                "--output",
                "coverage/semgrep.json",
                ".",
            ],
            "report": {"type": "semgrep", "path": "coverage/semgrep.json"},
        }
    )
    lockfiles = sorted(
        path.relative_to(root).as_posix()
        for path in files
        if path.name in OSV_LOCKFILES
        and ".agents" not in path.relative_to(root).parts
        and (path.name != "go.mod" or "require" in path.read_text())
    )
    if lockfiles:
        shared.append(
            {
                "name": "vulnerabilities",
                "role": "vulnerabilities",
                "parallel": True,
                "command": [
                    "osv-scanner",
                    "scan",
                    "source",
                    *(f"--lockfile={name}" for name in lockfiles),
                    "--all-packages",
                    "--format=json",
                    "--output-file=coverage/osv.json",
                ],
                "report": {"type": "osv", "path": "coverage/osv.json"},
            }
        )
    return {"version": 1, "packages": [], "shared": shared}


def announce(root: Path, config: GateConfig) -> None:
    label = None if config["packages"] else language_label(root, repository_files(root))
    if label is not None:
        print(
            f"Basic mode for {label}: rules, skills, secret scans and security scan installed; no built-in checks for {label}.\n"
            f"Gap: No built-in checks for {label}\n"
            f'File it, without asking: python3 .hooks/hard-eng.py gap-issue "No built-in checks for {label}"'
        )
