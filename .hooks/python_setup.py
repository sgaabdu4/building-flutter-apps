"""Adapt and check a Python package's test, import and source settings."""

import configparser
import json
import os
import re
import shlex
import tomllib
from collections.abc import Mapping
from itertools import pairwise
from pathlib import Path

from dependency_graph import child_groups
from gate_config import Gate, Group, require_roles
from project_files import parse_project_text
from project_setup import dependency_command

PYREFLY_REFUSED = (
    "ignore-missing-imports",
    "permissive-ignores",
    "replace-imports-with-any",
    "replace-untyped-imports-with-any",
    "sub-config",
)


def parallel_pytest(package: Group) -> None:
    """Run a generated pytest gate on every core; `-n 0` keeps a suite serial."""
    for gate in package["checks"]:
        command = gate["command"]
        runners = [
            index
            for index, argument in enumerate(command)
            if argument == "pytest"
            and command[index - 1] not in {"--with", "--upgrade-package"}
        ]
        if gate.get("role") != "tests" or not runners or "--with" not in command:
            continue
        options = command[runners[0] + 1 :]
        if "no:xdist" in options or any(
            option.startswith(("-n", "--numprocesses", "--dist")) for option in options
        ):
            continue
        xdist = ["--with", "pytest-xdist", "--upgrade-package", "pytest-xdist"]
        gate["command"] = [
            *command[: runners[0]],
            *([] if "pytest-xdist" in command else xdist),
            "pytest",
            "-n",
            "auto",
            *options,
        ]


POETRY_PREFIX = ["poetry", "run", "uv", "run", "--active", "--no-sync"]
RETIRED_POETRY_PREFIX = ["poetry", "run", "uv", "run", "--no-project", "--active"]


def current_poetry_prefix(package: Group) -> None:
    """`--no-project` lets an interpreter path pinned for uv replace Poetry's environment."""
    for gate in package["checks"]:
        if gate["command"][:6] == RETIRED_POETRY_PREFIX:
            gate["command"] = [*POETRY_PREFIX, *gate["command"][6:]]


def python_gate_command(command: list[str], manager: str) -> list[str]:
    packages = {
        "pytest": ["pytest", "pytest-cov"],
        "deptry": ["deptry"],
        "lint-imports": ["import-linter"],
        "mutmut": ["pytest", "mutmut"],
    }[command[0]]
    prefix = ["uv", "run", "--no-sync"]
    if manager == "poetry":
        prefix = [*POETRY_PREFIX]
    for package in packages:
        prefix.extend(["--with", package, "--upgrade-package", package])
    return [*prefix, *command]


def leave_out_children(
    root: Path, command: list[str], group: Group, gate: Gate
) -> list[str]:
    """Keep a Python parent's test and dependency commands out of the folders of its child groups, and the dependency gate out of a Sphinx docs folder."""
    role = gate.get("role")
    if group.get("language") != "python" or role not in {"tests", "dependencies"}:
        return command
    from change_size import configured_packages

    below = Path(group["path"])
    children = [
        Path(child["path"]).relative_to(below)
        for child in child_groups(group, role, list(configured_packages(root).values()))
    ]
    if role == "dependencies":
        sphinx = any(
            (root / below / f"docs/{place}conf.py").is_file()
            for place in ("", "source/")
        ) and not any(
            Path(source).parts[:1] == ("docs",) for source in group.get("sources", [])
        )
        return [
            *command,
            *(
                argument
                for child in [*children, *([Path("docs")] if sphinx else [])]
                for argument in ("--extend-exclude", f"^{re.escape(str(child))}(/|$)")
            ),
        ]
    if "pytest" not in command:
        return command
    runner = len(command) - 1 - command[::-1].index("pytest")
    ignores = [f"--ignore={root / below / child}" for child in children]
    return [*command[: runner + 1], *ignores, *command[runner + 1 :]]


def src_children(src: Path) -> list[tuple[str, Path]]:
    """Name and path of each package or module directly under `src`."""
    children = []
    for child in sorted(src.iterdir()):
        name = child.name if child.is_dir() else child.stem
        if name.isidentifier() and (
            (child / "__init__.py").exists()
            if child.is_dir()
            else child.suffix == ".py"
        ):
            children.append((name, child))
    return children


def is_src(source: str) -> bool:
    return os.path.normpath(source) == "src"


def python_roots(directory: Path, package: Group) -> list[str]:
    """Packages with a submodule; Import Linter rejects a `root.**` that matches nothing."""
    roots = set()
    for name in package["sources"]:
        path = directory / name
        if not path.is_dir():
            continue
        candidates = src_children(path) if is_src(name) else [(path.name, path)]
        roots.update(
            root
            for root, child in candidates
            if child.is_dir()
            and root.isidentifier()
            and (child / "__init__.py").exists()
            and any(file != child / "__init__.py" for file in child.rglob("*.py"))
        )
    return sorted(roots)


def known_first_party(directory: Path, package: Group) -> None:
    """A `src` layout package imports itself, and deptry cannot tell it from a dependency."""
    src = directory / "src"
    if not any(map(is_src, package["sources"])) or not src.is_dir():
        return
    option = "--known-first-party"
    for gate in package["checks"]:
        command = gate["command"]
        if ["deptry", "."] not in [command[i : i + 2] for i in range(len(command))]:
            continue
        named = {name for flag, name in pairwise(command) if flag == option}
        new = [name for name, _ in src_children(src) if name not in named]
        gate["command"] = [*command, *(arg for name in new for arg in (option, name))]


def import_linter_owner(
    directory: Path,
) -> tuple[Path, configparser.ConfigParser] | None:
    for name in ("setup.cfg", ".importlinter"):
        owner = directory / name
        if not owner.is_file():
            continue
        parser = configparser.ConfigParser()
        parser.read(owner)
        if parser.has_section("importlinter"):
            return owner, parser
    return None


def listed_roots(parser: configparser.ConfigParser) -> tuple[list[str], bool]:
    """The roots that the settings list, and whether the one-root option lists them."""
    one_root = not parser.has_option("importlinter", "root_packages")
    option = "root_package" if one_root else "root_packages"
    text = parser.get("importlinter", option, fallback="")
    roots = [value.strip() for value in text.splitlines() if value.strip()]
    return roots, one_root and bool(roots)


def has_recursive_import_contract(
    parser: configparser.ConfigParser, roots: list[str]
) -> bool:
    if not set(roots).issubset(listed_roots(parser)[0]):
        return False
    contracts = [
        parser[section]
        for section in parser.sections()
        if section.startswith("importlinter:")
    ]
    ancestors = set()
    for contract in contracts:
        if (
            contract.get("name", "").strip()
            and contract.get("type", "").strip() == "acyclic_siblings"
            and contract.get("depth", "").strip() == "0"
        ):
            ancestors.update(
                value.strip()
                for value in contract.get("ancestors", "").splitlines()
                if value.strip()
            )
    return all({root, root + ".**"} <= ancestors for root in roots)


def toml_import_linter(table: object) -> configparser.ConfigParser:
    """The `[tool.importlinter]` table in the shape that `has_recursive_import_contract` reads."""

    def lines(value: object) -> str:
        return "\n".join(map(str, value if isinstance(value, list) else [value]))

    parser = configparser.ConfigParser(interpolation=None)
    settings = table if isinstance(table, dict) else {}
    option = "root_packages" if "root_packages" in settings else "root_package"
    parser["importlinter"] = {option: lines(settings.get(option, []))}
    contracts = settings.get("contracts")
    for index, contract in enumerate(contracts if isinstance(contracts, list) else []):
        if isinstance(contract, dict):
            parser[f"importlinter:contract:{index}"] = {
                str(key): lines(value) for key, value in contract.items()
            }
    return parser


def import_contract_gap(directory: Path, package: Group) -> str | None:
    """What a package's Import Linter file lacks for its roots, or None when each root is covered."""
    roots = python_roots(directory, package)
    configured = import_linter_owner(directory)
    if configured is not None:
        owner, parser = configured
        kind = "ini"
    else:
        owner = directory / "pyproject.toml"
        text = owner.read_text() if owner.is_file() else ""
        table = tomllib.loads(text).get("tool", {}).get("importlinter")
        parser = toml_import_linter(table)
        kind = "toml"
    missing = [
        root for root in roots if not has_recursive_import_contract(parser, [root])
    ]
    if not missing:
        return None
    ancestors = [value for root in missing for value in (root, root + ".**")]
    name = "No sibling dependency cycles in " + ", ".join(missing)
    kept, one_root = listed_roots(parser)
    listed = sorted({*kept, *missing})
    how = "put this in place of the root_package line" if one_root else "set this"
    if kind == "toml":
        edit = "root_packages = " + json.dumps(listed)
        block = (
            '[[tool.importlinter.contracts]]\nname = "' + name + '"\n'
            'type = "acyclic_siblings"\nancestors = '
            + json.dumps(ancestors)
            + "\ndepth = 0\n"
        )
    else:
        edit = "root_packages =" + "".join(f"\n    {value}" for value in listed)
        block = (
            f"[importlinter:contract:{'-'.join(missing)}]\nname = {name}\n"
            "type = acyclic_siblings\nancestors ="
            + "".join(f"\n    {value}" for value in ancestors)
            + "\ndepth = 0\n"
        )
    table = "tool.importlinter" if kind == "toml" else "importlinter"
    return (
        f"{owner.name} has no import contract for {', '.join(missing)}, so the imports "
        f"gate cannot find an import cycle there. In {Path(package['path'], owner.name)}, "
        f"under [{table}], {how}:\n{edit}\nThen add this contract:\n{block}"
    )


def require_imports(directory: Path, package: Group, roles: set[str]) -> None:
    if "imports" not in roles and python_roots(directory, package):
        step = imports_step(directory, package)
        require_roles(package["path"], {"imports"}, roles, step)


def require_import_contract(directory: Path, package: Group, gate: Gate) -> None:
    """Runs with the imports gate, not at the config load: each session start loads the config."""
    if gate.get("role") == "imports" and package.get("language") == "python":
        gap = import_contract_gap(directory, package)
        if gap:
            raise ValueError(f"{package['path']}: {gap}")


def import_configuration(directory: Path, package: Group, content: str) -> str:
    roots = python_roots(directory, package)
    if not roots:
        return content
    configured = import_linter_owner(directory)
    if configured is not None:
        owner, parser = configured
        if has_recursive_import_contract(parser, roots):
            return content
        raise ValueError(
            f"Import Linter prioritizes {owner.name}; preserve its existing contracts "
            "and add a depth-zero acyclic_siblings contract covering each root and its descendants there"
        )
    if "importlinter" in tomllib.loads(content).get("tool", {}):
        return content
    ancestors = [value for root in roots for value in (root, root + ".**")]
    return content + (
        "\n[tool.importlinter]\nroot_packages = " + json.dumps(roots) + "\n"
        '\n[[tool.importlinter.contracts]]\nname = "No sibling dependency cycles"\n'
        'type = "acyclic_siblings"\nancestors = '
        + json.dumps(ancestors)
        + "\ndepth = 0\n"
    )


def imports_step(directory: Path, package: Group) -> str:
    """The whole step after a first module: the template gate as setup adapts it, and its contract."""
    template = Path(__file__).resolve().parents[1] / (
        ".agents/skills/he/templates/hard-eng.python.json"
    )
    gate = next(
        check
        for check in json.loads(template.read_text())["packages"][0]["checks"]
        if check.get("role") == "imports"
    )
    manager = dependency_command(directory, "python")[0]
    gate["command"] = python_gate_command(gate["command"], manager)
    content = (directory / "pyproject.toml").read_text()
    block = import_configuration(directory, package, content)[len(content) :]
    where = Path(package["path"], "pyproject.toml")
    return (
        f"add this gate to package {package['path']} in hard-eng.gates.json: "
        + json.dumps(gate)
        + (f"; then add this to {where}:{block}" if block else "")
    )


def pyrefly_gap(file: str, options: Mapping[str, object] | None) -> str:
    """The step that makes a package's Pyrefly settings strict, or an empty string; None is a file with no Pyrefly table."""
    table, options = options is not None, options or {}
    errors = options.get("errors")
    refused = [key for key in PYREFLY_REFUSED if options.get(key)]
    if isinstance(errors, dict):
        refused += [
            f"errors.{name}"
            for name, value in errors.items()
            if value in (False, "ignore")
        ]
    steps = []
    wrong = []
    for key, value, bad in (
        ("preset", '"strict"', options.get("preset") not in {"strict", "all"}),
        (
            "check-unannotated-defs",
            "true",
            options.get("check-unannotated-defs", True) is not True,
        ),
    ):
        if bad:
            wrong.append(
                f"change {key} to {value}" if key in options else f"add {key} = {value}"
            )
    if wrong:
        place = "at the top of the file, before any [table] line"
        if file.endswith("pyproject.toml"):
            place = "under [tool.pyrefly]" if table else "in a new [tool.pyrefly] table"
        steps.append(f"{' and '.join(wrong)} {place}")
    if refused:
        steps.append(f"remove {', '.join(refused)}")
    return f"{file}: {'; '.join(steps)}" if steps else ""


def pyrefly_options(directory: Path) -> tuple[Path, Mapping[str, object] | None]:
    """The file that holds a package's Pyrefly settings, and the settings in it; None with no Pyrefly table."""
    native = directory / "pyrefly.toml"
    if native.exists():
        return native, tomllib.loads(native.read_text())
    project = directory / "pyproject.toml"
    return project, tomllib.loads(project.read_text()).get("tool", {}).get("pyrefly")


def validate_pyrefly(directory: Path, root: Path) -> None:
    """The types gate refuses a package whose Pyrefly settings are not strict."""
    file, options = pyrefly_options(directory)
    gap = pyrefly_gap(str(file.relative_to(root)), options)
    if gap:
        raise ValueError(
            f"Pyrefly requires strict checking without disabled diagnostics or Any import substitutions; {gap}"
        )


def configure_python(
    root: Path, directory: Path, package: Group, changes: dict[str, str]
) -> None:
    dependency_command(directory, "python")  # Existing configurations need a lock too.
    parallel_pytest(package)
    current_poetry_prefix(package)
    known_first_party(directory, package)
    native = directory / "pyrefly.toml"
    project = directory / "pyproject.toml"
    name = str(project.relative_to(root))
    content = project.read_text()
    settings = parse_project_text(content, name, tomllib.loads)
    options = (
        tomllib.loads(native.read_text())
        if native.exists()
        else settings.get("tool", {}).get("pyrefly")
    )
    if options is not None:
        gap = pyrefly_gap(
            str(native.relative_to(root) if native.exists() else name), options
        )
        if gap:
            raise ValueError(
                f"{package['path']}: existing Pyrefly settings need strict checking. {gap}. Ask the user before you make that change"
            )
    else:
        changes[name] = (
            content
            + '\n[tool.pyrefly]\npreset = "strict"\ncheck-unannotated-defs = true\n'
        )
    current = test_import_path(directory, package, changes.get(name, content))
    updated = import_configuration(directory, package, current)
    if updated != content:
        changes[name] = updated


def test_import_path(directory: Path, package: Group, content: str) -> str:
    """uv installs only a packaged project, so pytest needs the folder of root modules."""
    project = tomllib.loads(content)
    packaged = project.get("tool", {}).get("uv", {}).get("package")
    if (
        (packaged if isinstance(packaged, bool) else "build-system" in project)
        or "pytest" in project.get("tool", {})
        or any(
            (directory / name).is_file()
            for name in ("pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini")
        )
        or any(
            (directory / name).is_file()
            and f"[{section}]" in (directory / name).read_text()
            for name, section in (("tox.ini", "pytest"), ("setup.cfg", "tool:pytest"))
        )
    ):
        return content
    paths = sorted({"src" if name == "src" else "." for name in package["sources"]})
    return content + f"\n[tool.pytest.ini_options]\npythonpath = {json.dumps(paths)}\n"


def pytest_options(directory: Path) -> list[str]:
    for root in (directory, *directory.parents):
        for name in (
            "pytest.toml",
            ".pytest.toml",
            "pytest.ini",
            ".pytest.ini",
            "pyproject.toml",
            "tox.ini",
            "setup.cfg",
        ):
            path = root / name
            if path.is_file():
                options = pytest_config(path)
                if options is not None:
                    return shlex.split(options) if isinstance(options, str) else options
        if (root / ".git").exists():
            break
    return []


def pytest_config(path: Path) -> str | list[str] | None:
    if path.suffix == ".toml":
        config = tomllib.loads(path.read_text())
        if path.name == "pyproject.toml" and "pytest" not in config.get("tool", {}):
            return None
        section = (
            config.get("tool", {}).get("pytest", {})
            if path.name == "pyproject.toml"
            else config.get("pytest", {})
        )
        section = section.get("ini_options", section)
        value = section.get("addopts", [])
    else:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(path)
        section = "tool:pytest" if path.name == "setup.cfg" else "pytest"
        if not parser.has_section(section) and path.name not in {
            "pytest.ini",
            ".pytest.ini",
        }:
            return None
        value = parser.get(section, "addopts", fallback="")
    if value is not None and not (
        isinstance(value, str)
        or isinstance(value, list)
        and all(isinstance(arg, str) for arg in value)
    ):
        raise TypeError("pytest addopts must be text or a list of arguments")
    return value


def locks_nothing(directory: Path) -> bool:
    """OSV scans only registry, Git and URL packages; uv.lock also lists the project itself."""
    lockfile = directory / "uv.lock"
    if not lockfile.is_file():
        return False
    packages = tomllib.loads(lockfile.read_text()).get("package", [])
    return all(
        not {"registry", "git", "url"} & set(package.get("source", {}))
        for package in packages
    )


def osv_identity(package: Mapping[str, object], lockfile: object) -> None:
    """Pass a local uv package that has no version; refuse any other package without identity."""
    name = package.get("name")
    if not (isinstance(name, str) and name):
        raise ValueError(
            f"OSV report lists a package with no name, from {lockfile}. Run the scan again."
        )
    path = Path(str(lockfile))
    if package.get("version") == "" and package.get("ecosystem") == "PyPI":
        if path.name == "uv.lock" and path.is_file():
            wanted = name.lower().replace("_", "-").replace(".", "-")
            entries = tomllib.loads(path.read_text()).get("package", [])
            if any(
                entry.get("name", "").lower().replace("_", "-").replace(".", "-")
                == wanted
                and {"editable", "virtual", "directory"} & set(entry.get("source", {}))
                for entry in entries
            ):
                return
        if path.name == "uv.lock":
            raise ValueError(
                f"OSV report lists {name} with no version, from {lockfile}. "
                "Only a local uv package may have none. Run `uv lock`, then run the scan again."
            )
    if not (isinstance(package.get("ecosystem"), str) and package["ecosystem"]):
        raise ValueError(
            f"OSV report lists {name} with no ecosystem, from {lockfile}. Run the scan again."
        )
    raise ValueError(
        f"OSV report lists {name} with no version, from {lockfile}. "
        "Update the lockfile with its package manager so that it holds a version, "
        "then run the scan again."
    )
