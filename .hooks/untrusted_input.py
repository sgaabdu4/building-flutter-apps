"""Make JavaScript/TypeScript packages validate untrusted JSON before use."""

import json
import os
import re
from pathlib import Path

from gate_config import JSONC, Group, json_file

DECLARATIONS = Path(".hooks/untrusted-input.d.ts")
CAST_RULE = "--only=nursery/noUnsafeTypeAssertion"


def strict_typing_rules(package: Group) -> None:
    """Give an older Biome typing-style gate the rules the template now requires."""
    for gate in package["checks"]:
        command = gate["command"]
        rules = [n for n, value in enumerate(command) if value.startswith("--only=")]
        typing = gate.get("role") == "typing-style" and "biome" in command
        if typing and rules and CAST_RULE not in command:
            command.insert(rules[-1] + 1, CAST_RULE)


def jsonc_config(name: str, text: str) -> dict[str, object]:
    stripped = JSONC.sub(lambda match: match[1] or "", text)
    try:
        config = json.loads(re.sub(r",(\s*[}\]])", r"\1", stripped))
    except json.JSONDecodeError as error:
        raise ValueError(f"{name} is not valid JSON: {error}") from error
    if not isinstance(config, dict):
        raise TypeError(f"{name} must hold a JSON object")
    return config


def json_listed(
    name: str, text: str, key: str, value: str, default: list[str]
) -> str | None:
    """Add value to a top-level list in JSON(C) text, keeping comments and layout; None when present."""
    config = jsonc_config(name, text)
    advice = f"{name}: add {value!r} to {key}, then rerun setup"
    current = config.get(key, default)
    if not isinstance(current, list):
        raise TypeError(advice)
    if value in current:
        return None
    if key in config:
        opening = re.search(rf'"{key}"\s*:\s*\[(\s*)', text)
        insert = (
            f'"{value}",{opening[1] or " "}' if opening and current else f'"{value}"'
        )
    else:
        opening = re.search(r"\{(\s*)", text)
        listed = json.dumps([*current, value])
        insert = (
            f'"{key}": {listed}{"," if config else ""}{opening[1] if opening else ""}'
        )
    if opening is None:
        raise ValueError(advice)
    updated = text[: opening.end()] + insert + text[opening.end() :]
    after = jsonc_config(name, updated).get(key)
    if not isinstance(after, list) or value not in after:
        raise ValueError(advice)
    return updated


def fallow_ignores_hooks(root: Path, changes: dict[str, str]) -> None:
    """Keep Fallow from reporting Hard Eng's hidden .hooks declarations as unanalyzed source."""
    pattern = ".hooks/**"
    names = (".fallowrc.json", ".fallowrc.jsonc", "fallow.toml", ".fallow.toml")
    name = next((name for name in names if (root / name).exists()), None)
    if name is None:
        changes[".fallowrc.json"] = json_file(root, {"ignorePatterns": [pattern]})
        return
    text = changes.get(name) or (root / name).read_text()
    advice = f"{name}: add {pattern!r} to ignorePatterns, then rerun setup"
    if name.endswith(".toml"):
        if pattern not in text:
            raise ValueError(advice)
        return
    config = jsonc_config(name, text)
    if "extends" in config and "ignorePatterns" not in config:
        raise ValueError(f"{advice}; a local list replaces the inherited one")
    updated = json_listed(name, text, "ignorePatterns", pattern, [])
    if updated is not None:
        changes[name] = updated


def extended(directory: Path, value: object) -> list[Path] | None:
    """The config files a tsconfig extends, or None when one is missing."""
    found: list[Path] = []
    for name in value if isinstance(value, list) else [value]:
        if not isinstance(name, str):
            return None
        bases = (
            [directory / name]
            if name.startswith((".", "/"))
            else [
                folder / "node_modules" / name
                for folder in (directory, *directory.parents)
            ]
        )
        candidates = [
            path
            for base in bases
            for path in (
                base,
                base.with_name(base.name + ".json"),
                base / "tsconfig.json",
            )
        ]
        match = next((path for path in candidates if path.is_file()), None)
        if match is None:
            return None
        found.append(match)
    return found


def inherited_lists(path: Path, seen: frozenset[Path] = frozenset()) -> set[str] | None:
    """The file-list keys a tsconfig's extends chain defines, or None when unresolvable."""
    config = jsonc_config(str(path), path.read_text())
    none: list[Path] = []
    bases = extended(path.parent, config["extends"]) if "extends" in config else none
    if bases is None or path in seen:
        return None
    keys: set[str] = set()
    for base in bases:
        inherited = inherited_lists(base, seen | {path})
        if inherited is None:
            return None
        base_config = jsonc_config(str(base), base.read_text())
        keys |= inherited | {"include", "files"} & base_config.keys()
    return keys


JSDOC_CAST = re.compile(
    r"/\*\*(?:(?!\*/).)*?@type\s*\{((?:(?!\*/).)*?)\}(?:(?!\*/).)*?\*/\s*\(", re.DOTALL
)


def reject_jsdoc_casts(directory: Path, files: list[str]) -> None:
    """Fail JavaScript `/** @type {T} */ (value)` assertions, which Biome's cast rule cannot see."""
    found = [
        f"{name}:{text.count(chr(10), 0, match.start()) + 1}"
        for name in files
        if Path(name).suffix in {".js", ".jsx", ".mjs", ".cjs"}
        for text in [(directory / name).read_text(errors="replace")]
        for match in JSDOC_CAST.finditer(text)
        if match[1].strip() != "const"
    ]
    if found:
        raise ValueError(
            "JSDoc type assertions skip validation; parse with a schema or narrow with a type guard: "
            + ", ".join(found)
        )


def typescript_config(
    root: Path, directory: Path, sources: list[str], changes: dict[str, str]
) -> None:
    """Write or extend the package tsconfig so it compiles the untrusted-input declarations."""
    target = directory / "tsconfig.json"
    name = str(target.relative_to(root))
    declarations = Path(os.path.relpath(root / DECLARATIONS, directory)).as_posix()
    if target.exists():
        text = changes.get(name) or target.read_text()
        config = jsonc_config(name, text)
        key = "files" if "files" in config and "include" not in config else "include"
        if "extends" in config and not {"include", "files"} & config.keys():
            inherited = inherited_lists(target)
            if inherited is None or "files" in inherited:
                raise ValueError(
                    f"{name} inherits a file list setup cannot extend; add {declarations!r} beside it"
                )
            key = "files" if inherited else "include"
        default = ["**/*"] if key == "include" else []
        updated = json_listed(name, text, key, declarations, default)
        if updated is not None:
            changes[name] = updated
    else:
        options = {"strict": True, "allowJs": True, "checkJs": True, "noEmit": True}
        include = [*sources, "test", "tests", declarations]
        config = {"compilerOptions": options, "include": include}
        changes[name] = json_file(root, config)
    if directory == root:
        fallow_ignores_hooks(root, changes)
