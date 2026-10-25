"""Adapt and check a Python package's test, import and source settings."""

import configparser
import json
import shlex
import tomllib
from pathlib import Path

from gate_config import Group
from project_setup import dependency_command, owned_files, source_roots


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


def python_gate_command(command: list[str], manager: str) -> list[str]:
    packages = {
        "pytest": ["pytest", "pytest-cov"],
        "deptry": ["deptry"],
        "lint-imports": ["import-linter"],
        "mutmut": ["pytest", "mutmut"],
    }[command[0]]
    prefix = ["uv", "run", "--no-sync"]
    if manager == "poetry":
        prefix = ["poetry", "run", "uv", "run", "--no-project", "--active"]
    for package in packages:
        prefix.extend(["--with", package, "--upgrade-package", package])
    return [*prefix, *command]


def python_roots(directory: Path, package: Group) -> list[str]:
    """Packages with a submodule; Import Linter rejects a `root.**` that matches nothing."""
    roots = set()
    for name in package["sources"]:
        path = directory / name
        if not path.is_dir():
            continue
        candidates = [path] if name != "src" else list(path.iterdir())
        roots.update(
            child.name
            for child in candidates
            if child.is_dir()
            and child.name.isidentifier()
            and (child / "__init__.py").exists()
            and any(file != child / "__init__.py" for file in child.rglob("*.py"))
        )
    return sorted(roots)


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


def has_recursive_import_contract(
    parser: configparser.ConfigParser, roots: list[str]
) -> bool:
    root_option = (
        "root_packages"
        if parser.has_option("importlinter", "root_packages")
        else "root_package"
    )
    configured_roots = {
        value.strip()
        for value in parser.get("importlinter", root_option, fallback="").splitlines()
        if value.strip()
    }
    if not set(roots).issubset(configured_roots):
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


def configure_python(
    root: Path, directory: Path, package: Group, changes: dict[str, str]
) -> None:
    dependency_command(directory, "python")  # Existing configurations need a lock too.
    parallel_pytest(package)
    native = directory / "pyrefly.toml"
    project = directory / "pyproject.toml"
    content = project.read_text()
    options = (
        tomllib.loads(native.read_text())
        if native.exists()
        else tomllib.loads(content).get("tool", {}).get("pyrefly")
    )
    if options is not None:
        if (
            options.get("preset") not in {"strict", "all"}
            or options.get("check-unannotated-defs", True) is not True
        ):
            raise ValueError(
                f"{package['path']}: existing Pyrefly settings need strict checking; preserve them and ask before changing them"
            )
    else:
        changes[str(project.relative_to(root))] = (
            content
            + '\n[tool.pyrefly]\npreset = "strict"\ncheck-unannotated-defs = true\n'
        )
    name = str(project.relative_to(root))
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


def require_listed_python_sources(
    root: Path, packages: list[Group], files: list[Path]
) -> None:
    """Code added after setup is checked only once its package lists it."""
    owned = owned_files(root, packages, files)
    for group in packages:
        if group.get("language") != "python":
            continue
        directory = root / group["path"]
        listed = set(group.get("sources", []))
        if missing := sorted(
            source_roots(directory, "python", owned[directory]) - listed
        ):
            raise ValueError(
                f"{group['path']}: Python code is outside its sources: {', '.join(missing)}; "
                "add each to the package's sources and to every check that names them "
                "(tests --cov=, annotations, dead-code, duplicates)"
            )


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
