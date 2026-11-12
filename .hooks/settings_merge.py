"""Merge installed settings into a project's settings file."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gate_config import JsonObject


def hook_identity(item: object) -> str:
    """The same matcher and commands are the same hook, whatever its timeout."""
    handlers = item.get("hooks") if isinstance(item, dict) else None
    if not isinstance(item, dict) or not isinstance(handlers, list):
        return json.dumps(item, sort_keys=True)
    commands = [h.get("command") for h in handlers if isinstance(h, dict)]
    return json.dumps([item.get("matcher"), commands])


def merge(
    current: JsonObject, additions: JsonObject, path: tuple[str, ...] = ()
) -> JsonObject:
    if not isinstance(current, dict):
        raise TypeError(f"Conflicting setting {'.'.join(path)}; expected an object")
    for key, value in additions.items():
        location = (*path, key)
        existing = current.get(key)
        if key not in current:
            current[key] = value
        elif isinstance(value, dict):
            if not isinstance(existing, dict):
                raise TypeError(
                    f"Conflicting setting {'.'.join(location)}; expected an object"
                )
            merge(existing, value, location)
        elif (
            isinstance(value, list)
            and path == ("hooks",)
            and isinstance(existing, list)
        ):
            known = {hook_identity(item) for item in existing}
            for item in value:
                if hook_identity(item) not in known:
                    existing.append(item)
        elif current[key] != value:
            raise ValueError(
                f"Conflicting setting {'.'.join(location)}; preserve it and ask before changing it"
            )
    return current
