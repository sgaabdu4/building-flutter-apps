"""Validate OSV scanner reports."""

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import cast

from gate_config import JsonObject
from project_setup import dependency_free

SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def validate_osv_package(
    item: JsonObject,
    source: JsonObject,
    layers: list[JsonObject],
    image: bool,
    unfixed: Callable[[str], object] | None = None,
) -> int:
    """1 when the package has vulnerabilities that no release fixes, else 0."""
    package = item["package"]
    if not isinstance(package, dict):
        raise TypeError("OSV package must be an object")
    commit = package.get("commit")
    if not (isinstance(commit, str) and commit) and not all(
        isinstance(package.get(key), str) and package[key]
        for key in ("name", "version", "ecosystem")
    ):
        from python_setup import osv_identity

        osv_identity(package, source["path"])
    left = int(item.get("vulnerabilities", []) != [] or item.get("groups", []) != [])
    if left:
        found = item.get("vulnerabilities")
        entries = found if isinstance(found, list) else []
        ids = [str(entry.get("id")) for entry in entries if isinstance(entry, dict)]
        name = f"{package.get('name') or commit}@{package.get('version')}"
        message = f"OSV reports vulnerable packages: {name}: " + ", ".join(ids)
        if unfixed is None:
            raise ValueError(message)
        from osv_unfixed import accept_unfixed

        try:
            accept_unfixed(item, unfixed)
        except ValueError as error:
            raise ValueError(f"{message} (not proven unfixable: {error})") from error
    if image:
        origin = package["image_origin_details"]
        if not isinstance(origin, dict):
            raise ValueError("OSV image package lacks layer origin details")
        index = origin["index"]
        if (
            source["type"] not in {"artifact", "os", "lockfile"}
            or type(index) is not int
            or not 0 <= index < len(layers)
            or layers[index]["is_empty"]
        ):
            raise ValueError("OSV package lacks a valid image layer origin")
    return left


def osv_layers(report: JsonObject) -> list[JsonObject]:
    metadata = report["image_metadata"]
    if not isinstance(metadata, dict):
        raise TypeError("OSV image metadata must be an object")
    layers = metadata["layer_metadata"]
    if not isinstance(layers, list) or not layers:
        raise ValueError("OSV image report contains no layers")
    for layer in layers:
        if not isinstance(layer, dict):
            raise TypeError("OSV image layer must be an object")
        if type(layer["is_empty"]) is not bool or (
            not layer["is_empty"]
            and (
                not isinstance(layer["diff_id"], str)
                or not SHA256_DIGEST.fullmatch(layer["diff_id"])
            )
        ):
            raise ValueError("OSV image report has invalid layer metadata")
    return cast(list[JsonObject], layers)


def validate_osv(
    path: Path,
    *,
    image: bool = False,
    empty_bun: Path | None = None,
    unfixed: Callable[[str], object] | None = None,
) -> None:
    try:
        report = json.loads(path.read_text())
        results = report["results"]
        if (
            report.get("errors")
            or report.get("error")
            or report.get("experimental_generic_findings")
        ):
            raise ValueError("OSV reports scan errors or findings")
        if (
            results in (None, [])
            and not image
            and empty_bun is not None
            and not (empty_bun / "bun.lock").exists()
            and dependency_free(empty_bun)
        ):
            print(
                "OSV: package.json declares no dependencies, so Bun keeps no lockfile"
            )
            return
        if not isinstance(results, list):
            raise TypeError("OSV results must be a list")
        layers = osv_layers(report) if image else []
        count = open_ = 0
        for result in results:
            if not all(
                isinstance(result["source"][key], str) and result["source"][key]
                for key in ("path", "type")
            ):
                raise ValueError("OSV report is missing its scan source")
            packages = result["packages"]
            if not isinstance(packages, list):
                raise TypeError("OSV packages must be a list")
            for item in packages:
                open_ += validate_osv_package(
                    item, result["source"], layers, image, unfixed
                )
                count += 1
        if not count:
            raise ValueError("OSV report contains no scanned packages")
        print(
            f"OSV validated {count} package records; "
            + (
                f"{open_} hold vulnerabilities that no release fixes"
                if open_
                else "no reported vulnerabilities"
            )
        )
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("OSV report is incomplete or malformed") from error


def validate_osv_image(path: Path) -> None:
    validate_osv(path, image=True)


def osv_unfixed_only(path: Path) -> bool:
    """True when the report holds vulnerabilities and no release fixes any of them; a ValueError says what is fixable."""
    import freshness

    try:
        report = json.loads(path.read_text())
        if not any(
            item.get("vulnerabilities")
            for result in report["results"]
            for item in result["packages"]
        ):
            return False
    except (KeyError, TypeError, AttributeError):
        return False
    validate_osv(path, unfixed=freshness.fetch_json)
    return True
