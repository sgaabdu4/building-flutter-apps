"""Read the machine-format report produced by a Dart test gate."""

import json
import re
from pathlib import Path
from typing import cast

from gate_config import JsonObject

WHITESPACE_RUN = re.compile(r"\s+")
FLUTTER_FAILURE = "Test failed. See exception logs above"
PRINT_LIMIT = 600


def dart_events(path: Path) -> list[JsonObject]:
    """Return reporter events, skipping raw test output that shares the stream."""
    events: list[JsonObject] = []
    for line in path.read_text().splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        items = value if isinstance(value, list) else [value]
        if all(isinstance(item, dict) for item in items):
            events.extend(cast(JsonObject, item) for item in items)
    return events


def test_place(test: JsonObject) -> str:
    url = test.get("root_url") or test.get("url")
    line = test.get("root_line") if test.get("root_url") else test.get("line")
    return f"{url}:{line}"


def failure_summary(path: Path) -> str | None:
    """Return one bounded failing-test summary from a machine-format Dart report."""
    try:
        events = dart_events(path)
    except (OSError, ValueError):
        return None
    if not any(event.get("type") in {"testStart", "testDone"} for event in events):
        return unstructured_reason(path)
    return test_failure(events)


def test_failure(events: list[JsonObject]) -> str | None:
    names: dict[int, str] = {}
    places: dict[int, str] = {}
    prints: dict[int, list[str]] = {}
    failures: list[int] = []
    errors: dict[int, str] = {}
    for event in events:
        if event.get("type") == "testStart" and isinstance(event.get("test"), dict):
            test = cast(JsonObject, event["test"])
            identifier, name = test.get("id"), test.get("name")
            if type(identifier) is int and isinstance(name, str):
                names[identifier] = name
                places[identifier] = test_place(test)
        identifier = event.get("testID")
        if type(identifier) is not int:
            continue
        if event.get("type") == "testDone" and event.get("result") in {
            "failure",
            "error",
        }:
            failures.append(identifier)
        if event.get("type") == "print" and isinstance(event.get("message"), str):
            prints.setdefault(identifier, []).append(event["message"])
        if event.get("type") == "error" and isinstance(event.get("error"), str):
            errors.setdefault(identifier, event["error"])
    if not failures:
        return None
    identifier = failures[0]
    name = names.get(identifier, f"test {identifier}")
    printed = " ".join(prints.get(identifier, []))
    place = places.get(identifier, "no file")
    detail = failure_detail(errors.get(identifier), printed, place)
    return f"Dart test failure: {name}{detail}"


def unstructured_reason(path: Path) -> str | None:
    """The tool's own words, when the run ended before any test event."""
    lines = []
    for line in path.read_text().splitlines():
        try:
            if isinstance(json.loads(line), dict):
                continue
        except ValueError:
            pass
        if line.strip():
            lines.append(line)
    if not lines:
        return None
    return "Dart test run ended before its first test:\n" + "\n".join(lines[:20])


def failure_detail(error: str | None, printed: str, place: str) -> str:
    if error is None:
        return ""
    if error.startswith(FLUTTER_FAILURE):
        text = WHITESPACE_RUN.sub(" ", printed).strip()
        return ": " + f"{text[:PRINT_LIMIT]} ({place})".strip()
    return ": " + WHITESPACE_RUN.sub(" ", error).strip()[:300]
