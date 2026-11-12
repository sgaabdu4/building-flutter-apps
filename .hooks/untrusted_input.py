"""Make JavaScript/TypeScript packages validate untrusted JSON before use."""

import json
import os
import re
import subprocess
import sys
from itertools import takewhile
from pathlib import Path, PurePosixPath

from gate_config import (
    JSONC,
    Group,
    JsonObject,
    JsonValue,
    biome_formatters,
    json_file,
)

OPENING_BRACE = re.compile(r"\{(\s*)")
TRAILING_COMMA = re.compile(r",(\s*[}\]])")

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
        config = json.loads(TRAILING_COMMA.sub(r"\1", stripped))
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
        opening = OPENING_BRACE.search(text)
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


BIOME_IGNORES = ("!.hooks", "!.hard-eng", "!coverage")


def biome_entries(root: Path, changes: dict[str, str]) -> tuple[str, ...]:
    """The Hard Eng entries of files.includes: the hook folders and the report folder of each package."""
    try:
        gates = json.loads(
            changes.get("hard-eng.gates.json")
            or (root / "hard-eng.gates.json").read_text()
        )
        paths = [group["path"] for group in gates["packages"]]
    except (OSError, ValueError, TypeError, KeyError):
        return BIOME_IGNORES
    folders = (PurePosixPath(path).as_posix() for path in paths)
    reports = (f"!{folder}/coverage" for folder in folders if folder != ".")
    return tuple(dict.fromkeys((*BIOME_IGNORES, *reports)))


def closing(text: str, start: int) -> int:
    """Offset of the bracket that closes the object or list opening at start."""
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char == '"':
            index += 1
            while text[index] != '"':
                index += 2 if text[index] == "\\" else 1
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ValueError("unbalanced brackets")


def value_starts(text: str, start: int) -> dict[str, int]:
    """Offset of the value of each key that sits directly in the object opening at start."""
    found: dict[str, int] = {}
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char == '"':
            end = index + 1
            while text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            after = text[end + 1 :].lstrip()
            if depth == 1 and after.startswith(":"):
                found[text[index + 1 : end]] = len(text) - len(after[1:].lstrip())
            index = end
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
            if depth == 0:
                break
        index += 1
    return found


def biome_setting(layout: dict[str, int | str], key: str, default: int) -> int:
    """The formatter option as an integer, else the Biome default."""
    value = layout.get(key)
    return value if isinstance(value, int) else default


def add_member(text: str, masked: str, brace: int, member: str) -> str:
    """Put member before the first member of the object, with the gap the file already has."""
    first = brace + 1
    while masked[first] in " \t\r\n":
        first += 1
    gap = text[brace + 1 : first]
    if gap.strip():
        raise ValueError("a comment stands before the first member")
    if masked[first] == "}":
        return f"{text[:brace]}{{ {member} }}{text[first + 1 :]}"
    return f"{text[:first]}{member},{gap}{text[first:]}"


def add_line_entry(
    text: str, masked: str, end: int, close: int, added: list[str]
) -> str:
    """Add the entries as new lines below the last entry of a list written over several lines."""
    start = text.rfind("\n", 0, end) + 1
    stop = text.find("\n", end)
    line = text[start:end]
    if stop < 0 or stop > close or "[" in masked[start:end]:
        raise ValueError("the last entry shares its line")
    indent = line[: len(line) - len(line.lstrip())]
    comma = "" if masked[end - 1] == "," else ","
    entry = ",".join(f'\n{indent}"{name}"' for name in added)
    return f"{text[:end]}{comma}{text[end:stop]}{entry}{text[stop:]}"


def add_inline_entry(
    text: str,
    masked: str,
    layout: dict[str, int | str],
    span: tuple[int, int],
    added: list[str],
) -> str:
    """Add the entries to a one-line list; write the list over several lines when the line gets too long."""
    start, close = span
    end = len(masked[:close].rstrip())
    comma = "" if masked[end - 1] in ",[" else ","
    space = "" if masked[end - 1] == "[" else " "
    new = ", ".join(json.dumps(name) for name in added)
    rest = text[close:] if space == "" else text[end:]
    edited = f"{text[:end]}{comma}{space}{new}{rest}"
    first = edited.rfind("\n", 0, start) + 1
    last = edited.find("\n", start)
    line = edited[first : None if last < 0 else last]
    tab = " " * biome_setting(layout, "indentWidth", 2)
    if len(line.replace("\t", tab)) <= biome_setting(layout, "lineWidth", 80):
        return edited
    key = line[: line.index("[")]
    after = line[line.index("]") + 1 :]
    if not key.strip().startswith('"includes"') or after not in {"", ","}:
        raise ValueError("the list shares its line")
    if masked[start : close + 1] != text[start : close + 1]:
        raise ValueError("a comment stands in the list")
    indent = key[: len(key) - len(key.lstrip())]
    inner = indent + ("\t" if indent.startswith("\t") else tab)
    entries = [*json.loads(text[start : close + 1]), *added]
    body = ",\n".join(f"{inner}{json.dumps(entry)}" for entry in entries)
    return f"{text[:start]}[\n{body}\n{indent}]{text[close + 1 :]}"


def biome_list(includes: list[str] | None, entries: tuple[str, ...]) -> list[str]:
    """The files.includes list with the Hard Eng entries that it lacks at the end."""
    current = includes or ["**"]
    return [*current, *(name for name in entries if name not in current)]


def biome_includes(config: dict[str, object]) -> list[str] | None:
    """The files.includes list of the config, or None when it has none."""
    files = config.get("files")
    includes = files.get("includes") if isinstance(files, dict) else None
    return includes if isinstance(includes, list) else None


def biome_edit(
    text: str,
    config: dict[str, object],
    layout: dict[str, int | str],
    entries: tuple[str, ...],
) -> str | None:
    """The text with the Hard Eng entries in files.includes; None when they are there."""
    masked = JSONC.sub(lambda match: match[1] or " " * len(match[0]), text)
    top = value_starts(masked, masked.index("{"))
    files = config.get("files")
    includes = biome_includes(config)
    wanted = biome_list(includes, entries)
    if includes is not None:
        added = wanted[len(includes) :]
        if not added:
            return None
        start = value_starts(masked, top["files"])["includes"]
        close = closing(masked, start)
        end = len(masked[:close].rstrip())
        if not includes:
            if text[start + 1 : close].strip():
                raise ValueError("a comment stands in the empty list")
            return add_inline_entry(text, masked, layout, (start, close), added)
        if "\n" in text[start:close]:
            return add_line_entry(text, masked, end, close, added)
        return add_inline_entry(text, masked, layout, (start, close), added)
    if "extends" in config:
        raise ValueError("a local list replaces the inherited one")
    listed = f'"includes": {json.dumps(wanted)}'
    if isinstance(files, dict):
        return add_member(text, masked, top["files"], listed)
    if files is not None:
        raise ValueError("files is not an object")
    return add_member(text, masked, masked.index("{"), f'"files": {{ {listed} }}')


def biome_proof(
    before: dict[str, object], after: dict[str, object], entries: tuple[str, ...]
) -> bool:
    """True when only the files.includes list differs and it now ends with the Hard Eng entries."""

    def rest(config: dict[str, object]) -> dict[str, object]:
        others = {key: value for key, value in config.items() if key != "files"}
        files = config.get("files")
        if isinstance(files, dict):
            kept = {key: value for key, value in files.items() if key != "includes"}
            return {**others, "files": kept} if kept else others
        return others

    return biome_includes(after) == biome_list(
        biome_includes(before), entries
    ) and rest(before) == rest(after)


def biome_ignores_hooks(root: Path, changes: dict[str, str]) -> None:
    """Keep the project's Biome from judging the files that Hard Eng writes, such as .hooks, which holds any[] and {} on purpose."""
    name = next(
        (name for name in ("biome.json", "biome.jsonc") if (root / name).exists()),
        None,
    )
    if name is None:
        return
    text = changes.get(name) or (root / name).read_text()
    entries = biome_entries(root, changes)
    try:
        config = jsonc_config(name, text)
        formatter, own = biome_formatters(root / name, set())
        updated = biome_edit(text, config, {**formatter, **own}, entries)
        if updated is not None:
            after = jsonc_config(name, updated)
            if not biome_proof(config, after, entries):
                raise ValueError("the edit changed other settings")
    except (ValueError, TypeError, KeyError) as error:
        quoted = [f'"{entry}"' for entry in entries]
        entries = f"{', '.join(quoted[:-1])} and {quoted[-1]}"
        step = f"add {entries} as the last entries of files.includes"
        if "empty" in str(error):
            step = f'files.includes is empty: put "**" first, then add {entries} as the last entries'
        if "inherited" in str(error):
            step = (
                "it extends another configuration, and a local files.includes list "
                "replaces the inherited one. Copy the inherited list into "
                f'files.includes (use "**" when there is none) and add {entries} '
                "as its last entries"
            )
        print(
            f"{name}: {step}, so that your own Biome runs leave the Hard Eng files",
            file=sys.stderr,
        )
        return
    if updated is not None:
        changes[name] = updated


def package_tsconfig(directory: Path) -> list[Path]:
    """The config a package names in its package.json `tsconfig` field."""
    manifest = directory / "package.json"
    field = (
        json.loads(manifest.read_text()).get("tsconfig") if manifest.is_file() else None
    )
    return [directory / field] if isinstance(field, str) else []


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
                *package_tsconfig(base),
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


def next_route_types(directory: Path, timeout: float) -> None:
    """Write Next.js route types (`PageProps`, `LayoutProps`) that a clean checkout lacks."""
    path = directory / "package.json"
    manifest = json.loads(path.read_text()) if path.is_file() else {}
    declared = {
        **manifest.get("dependencies", {}),
        **manifest.get("devDependencies", {}),
    }
    cli = "node_modules/next/dist/cli/next-typegen.js"
    folders = (directory, *directory.parents)
    routes = ("app", "pages", "src/app", "src/pages")
    if (
        "next" not in declared
        or not any((directory / route).is_dir() for route in routes)
        or not any((f / cli).is_file() for f in folders)
    ):
        return
    result = subprocess.run(
        ["bun", "x", "next", "typegen"],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"next typegen failed: {result.stderr or result.stdout}")


def typescript_projects(
    root: Path, command: list[str], directory: Path
) -> list[list[str]]:
    """One `-p` per config the selected tsconfig builds; [[]] runs the command as is."""
    selected = explicit_project(command)
    target = directory / selected[1] if selected else directory / "tsconfig.json"
    target = target / "tsconfig.json" if target.is_dir() else target
    configs = project_configs(root, target) if target.is_file() else [target]
    if configs == [target]:
        return [[]]
    return [["-p", os.path.relpath(config, directory)] for config in configs]


def project_command(command: list[str], project: list[str]) -> list[str]:
    """The command with its own project selection replaced by `project`."""
    if not project:
        return command
    kept: list[str] = []
    skip = False
    for argument in command:
        name, _, value = argument.partition("=")
        if skip or name in {"-p", "--project"}:
            skip = not skip and name in {"-p", "--project"} and not value
            continue
        kept.append(argument)
    return [*kept, *project]


STRICT = (
    "noImplicitAny",
    "noImplicitThis",
    "strictNullChecks",
    "strictFunctionTypes",
    "strictBindCallApply",
    "strictPropertyInitialization",
    "strictBuiltinIteratorReturn",
    "useUnknownInCatchVariables",
    "alwaysStrict",
)


def shown_config(command: list[str], directory: Path, timeout: float) -> JsonObject:
    result = subprocess.run(
        [*command, "--showConfig"],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    config = json.loads(result.stdout)
    options = config.get("compilerOptions", {}) if isinstance(config, dict) else {}
    return {"files": config.get("files", []), **options}


def strict_options(options: JsonObject) -> bool:
    return options.get("strict") is True and all(
        options.get(name, True) is True for name in STRICT
    )


def explicit_project(command: list[str]) -> list[str]:
    for index, argument in enumerate(command):
        name, _, value = argument.partition("=")
        if name in {"-p", "--project"}:
            return ["-p", value or command[index + 1]]
    return []


def validate_typescript(
    root: Path, command: list[str], directory: Path, expected: set[Path], timeout: float
) -> None:
    compiler = list(takewhile(lambda argument: not argument.startswith("-"), command))
    selected = explicit_project(command)
    files: set[Path] = set()
    read: list[Path] = []
    for project in typescript_projects(root, command, directory):
        options = shown_config(project_command(command, project), directory, timeout)
        target = project or selected
        if (
            not strict_options(options)
            or options.get("checkJs") is not True
            or options.get("noCheck", False) is not False
        ):
            raise ValueError(
                "TypeScript requires all strict checks and JavaScript checking without noCheck"
            )
        config = directory / target[1] if target else directory / "tsconfig.json"
        config = config / "tsconfig.json" if config.is_dir() else config
        base = config.parent
        read.append(config)
        listed = options.get("files", [])
        names: list[JsonValue] = listed if isinstance(listed, list) else []
        resolved = {(base / str(name)).resolve() for name in names}
        if (root / DECLARATIONS).resolve() not in resolved:
            entry = os.path.relpath(root / DECLARATIONS, base)
            raise ValueError(
                f"HE-UNTRUSTED-JSON: {os.path.relpath(config, root)} omits {DECLARATIONS}; "
                f'add "{entry}" to its files list'
            )
        files |= resolved
    if omitted := sorted({(directory / name).resolve() for name in expected} - files):
        shown = [os.path.relpath(path, root.resolve()) for path in omitted]
        configs = ", ".join(os.path.relpath(path, root.resolve()) for path in read)
        several = f"the configuration that should compile it; the check read {configs}"
        where = configs if len(read) == 1 else several
        raise ValueError(
            "TypeScript configuration omits declared production files: "
            + ", ".join(shown[:3])
            + (f" and {len(shown) - 3} more" if len(shown) > 3 else "")
            + f". Add the folder of each file to the `include` list of {where}, and remove any `exclude` entry that matches the file"
        )
    build_composites(root, compiler, selected, directory, timeout)


def build_composites(
    root: Path,
    compiler: list[str],
    selected: list[str],
    directory: Path,
    timeout: float,
) -> None:
    """Write the declarations dependent --noEmit checks read; `tsc -b` ignores the gate's flags."""
    graph = directory / selected[1] if selected else directory / "tsconfig.json"
    graph = graph / "tsconfig.json" if graph.is_dir() else graph
    if not graph.is_file():
        return
    configs = project_configs(root, graph)
    read = {
        reached
        for config in configs
        for target in referenced(config)
        for reached in project_configs(root, target)
    }
    composites: list[str] = []
    for config in [config for config in configs if config in read]:
        name = os.path.relpath(config, directory)
        own = shown_config([*compiler, "-p", name], directory, timeout)
        if own.get("composite") is True:
            composites.append(name)
        loose = (
            not strict_options(own)
            or own.get("noCheck", False) is not False
            or (own.get("allowJs") is True and own.get("checkJs") is not True)
        )
        if own.get("composite") is True and loose:
            raise ValueError(
                f"{name}: a composite tsconfig must set strict (and checkJs with allowJs) itself "
                "without noCheck, because `tsc -b` ignores the gate's flags"
            )
        listed = own.get("files")
        names: list[JsonValue] = listed if isinstance(listed, list) else []
        resolved = {(config.parent / str(item)).resolve() for item in names}
        if (
            own.get("composite") is True
            and (root / DECLARATIONS).resolve() not in resolved
        ):
            raise ValueError(
                f"{name}: a composite tsconfig must include {DECLARATIONS}, "
                "because its built declarations are what dependent projects check"
            )
    if not composites:
        return
    build = subprocess.run(
        [*compiler, "-b", *composites],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if build.returncode != 0:
        raise ValueError(f"tsc -b failed: {build.stdout or build.stderr}")


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


def effective_lists(
    path: Path, seen: frozenset[Path] = frozenset()
) -> dict[str, object] | None:
    """A tsconfig's `files` and `include` after `extends`; None when a base is missing."""
    config = jsonc_config(str(path), path.read_text())
    lists: dict[str, object] = {}
    if "extends" in config:
        bases = extended(path.parent, config["extends"])
        if bases is None or path in seen:
            return None
        for base in bases:
            inherited = effective_lists(base, seen | {path})
            if inherited is None:
                return None
            lists.update(inherited)
    lists.update({key: config[key] for key in ("files", "include") if key in config})
    return lists


def referenced(path: Path) -> list[Path]:
    """The tsconfigs a config's `references` name."""
    config = jsonc_config(str(path), path.read_text())
    listed = config.get("references")
    targets: list[Path] = []
    for reference in listed if isinstance(listed, list) else []:
        named = reference.get("path") if isinstance(reference, dict) else None
        target = Path(os.path.normpath(path.parent / str(named)))
        target = target / "tsconfig.json" if target.is_dir() else target
        if not isinstance(named, str) or not target.is_file():
            raise ValueError(f"{path.name}: referenced config {named!r} is missing")
        targets.append(target)
    return targets


def project_configs(
    root: Path, path: Path, seen: frozenset[Path] = frozenset()
) -> list[Path]:
    """The tsconfigs that compile sources: this one unless it is a solution, plus its references."""
    if path in seen:
        return []
    config = jsonc_config(str(path), path.read_text())
    declarations = Path(os.path.relpath(root / DECLARATIONS, path.parent)).as_posix()
    listed_references = config.get("references")
    references: list[object] = (
        listed_references if isinstance(listed_references, list) else []
    )
    local = {key: config[key] for key in ("files", "include") if key in config}
    effective = effective_lists(path)
    own = {
        name for listed in local.values() if isinstance(listed, list) for name in listed
    }
    if effective is None and references and len(local) < 2 and own <= {declarations}:
        raise ValueError(
            f"{path.name}: setup cannot resolve the config it extends; set both files and "
            "include in it, or add the untrusted-input declaration to each referenced config"
        )
    lists: list[object] = list((local if effective is None else effective).values())
    names = [name for listed in lists if isinstance(listed, list) for name in listed]
    solution = (
        bool(references and lists)
        and all(isinstance(listed, list) for listed in lists)
        and set(names) <= {declarations}
    )
    found: list[Path] = [] if solution else [path]
    for target in referenced(path):
        found += project_configs(root, target, seen | {path})
    return list(dict.fromkeys(found))


def declared_config(root: Path, target: Path, changes: dict[str, str]) -> None:
    name = str(target.relative_to(root))
    declarations = Path(os.path.relpath(root / DECLARATIONS, target.parent)).as_posix()
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


def typescript_config(
    root: Path, directory: Path, sources: list[str], changes: dict[str, str]
) -> None:
    """Write or extend the package tsconfig so it compiles the untrusted-input declarations."""
    target = directory / "tsconfig.json"
    name = str(target.relative_to(root))
    declarations = Path(os.path.relpath(root / DECLARATIONS, directory)).as_posix()
    if target.exists():
        configs = project_configs(root, target)
        text = target.read_text()
        listed = jsonc_config(name, text)
        if target not in configs and (listed.get("files") or listed.get("include")):
            # An earlier setup listed the file here, which breaks `tsc -b`.
            repaired = jsonc_config(name, text.replace(f'"{declarations}"', "", 1))
            if repaired.get("files") or repaired.get("include"):
                raise ValueError(f"{name}: remove {declarations!r} from its file list")
            changes[name] = text.replace(f'"{declarations}"', "", 1)
        for config in configs:
            declared_config(root, config, changes)
    else:
        options = {"strict": True, "allowJs": True, "checkJs": True, "noEmit": True}
        include = [*sources, "test", "tests", declarations]
        config = {"compilerOptions": options, "include": include}
        changes[name] = json_file(root, config)
    if directory == root:
        fallow_ignores_hooks(root, changes)
