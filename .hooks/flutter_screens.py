"""HE-NO-TEXT-WALLS: the Dart files and the message catalog that hold the screen text of a Flutter package."""

import json
import re
from pathlib import Path

ARB_DIRECTORY = re.compile(r"(?m)^arb-dir:\s*(\S+)")
ARB_TEMPLATE = re.compile(r"(?m)^template-arb-file:\s*(\S+)")
FLUTTER_SDK = re.compile(r"sdk:\s*flutter")


def flutter_packages(root: Path) -> list[str]:
    """The folder of each gates package with language dart and a Flutter pubspec, with a trailing slash."""
    try:
        packages = json.loads((root / "hard-eng.gates.json").read_text())["packages"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    found = []
    for package in packages if isinstance(packages, list) else []:
        if not isinstance(package, dict) or package.get("language") != "dart":
            continue
        folder = str(package.get("path", ".")).strip("/.")
        base = f"{folder}/" if folder else ""
        try:
            pubspec = (root / base / "pubspec.yaml").read_text()
        except OSError:
            continue
        if FLUTTER_SDK.search(pubspec):
            found.append(base)
    return found


def template_arb(root: Path, base: str) -> str:
    try:
        settings = (root / base / "l10n.yaml").read_text()
    except OSError:
        settings = ""
    folder = ARB_DIRECTORY.search(settings)
    template = ARB_TEMPLATE.search(settings)
    return f"{base}{(folder[1] if folder else 'lib/l10n').strip('/')}/{template[1] if template else 'app_en.arb'}"


def screen_files(root: Path, names: list[str]) -> list[str]:
    """The names that are Dart files under lib/ of a Flutter package, or its template ARB file."""
    if not any(name.endswith((".dart", ".arb")) for name in names):
        return []
    packages = flutter_packages(root)
    arbs = {template_arb(root, base) for base in packages}
    return [
        name
        for name in names
        if name in arbs
        or (
            name.endswith(".dart")
            and any(name.startswith(f"{b}lib/") for b in packages)
        )
    ]
