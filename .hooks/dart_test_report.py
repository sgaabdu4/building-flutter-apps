"""Read the machine-format report produced by a Dart test gate."""

import json
import re
from pathlib import Path
from typing import cast

from gate_config import JsonObject


def dart_events(path: Path) -> list[JsonObject]:
    """Return validated events from the supported JSON-lines report."""
    events = [
        item
        for line in path.read_text().splitlines()
        if line.strip()
        for event in [json.loads(line)]
        for item in (event if isinstance(event, list) else [event])
    ]
    if not all(isinstance(event, dict) for event in events):
        raise ValueError("Invalid Dart test report")
    return [cast(JsonObject, event) for event in events]


def failure_summary(path: Path) -> str | None:
    """Return one bounded failing-test summary from a machine-format Dart report."""
    try:
        events = dart_events(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    names: dict[int, str] = {}
    failures: list[int] = []
    errors: dict[int, str] = {}
    for event in events:
        if event.get("type") == "testStart" and isinstance(event.get("test"), dict):
            test = cast(JsonObject, event["test"])
            identifier, name = test.get("id"), test.get("name")
            if type(identifier) is int and isinstance(name, str):
                names[identifier] = name
        identifier = event.get("testID")
        if type(identifier) is not int:
            continue
        if event.get("type") == "testDone" and event.get("result") in {
            "failure",
            "error",
        }:
            failures.append(identifier)
        if event.get("type") == "error" and isinstance(event.get("error"), str):
            errors.setdefault(identifier, event["error"])
    if not failures:
        return None
    identifier = failures[0]
    name = names.get(identifier, f"test {identifier}")
    if (error := errors.get(identifier)) is None:
        return f"Dart test failure: {name}"
    detail = re.sub(r"\s+", " ", error).strip()
    return f"Dart test failure: {name}: {detail[:300]}"
