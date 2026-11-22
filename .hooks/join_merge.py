"""Merge a join pull request into a base that requires linear history: lift only that rule, merge, put the saved protection back."""

import json
import signal
import tempfile
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from shipping import Shipment, ShippingError, _json, _object, gh

ATTEMPTS = 3
FLAGS = (
    "allow_force_pushes",
    "allow_deletions",
    "block_creations",
    "required_conversation_resolution",
    "lock_branch",
    "allow_fork_syncing",
)
KNOWN = {
    "url",
    "required_status_checks",
    "required_signatures",
    "enforce_admins",
    "required_pull_request_reviews",
    "restrictions",
    "required_linear_history",
    *FLAGS,
}
UNPROTECTED = "Branch not protected"
STOPS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)


def _plain(value: object) -> object:
    """The value without its URL fields, which GitHub fills in."""
    if isinstance(value, dict):
        return {
            key: _plain(item)
            for key, item in value.items()
            if key != "url" and not key.endswith("_url")
        }
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _enabled(saved: dict[str, object], key: str) -> bool:
    entry = saved.get(key)
    flag = entry.get("enabled") if isinstance(entry, dict) else None
    if not isinstance(flag, bool):
        raise ShippingError(f"The saved protection has no {key} setting to copy")
    return flag


def _checks(saved: dict[str, object]) -> dict[str, object] | None:
    found = _plain(saved.get("required_status_checks"))
    if found is None:
        return None
    rows = found.get("checks") if isinstance(found, dict) else None
    if (
        not isinstance(found, dict)
        or set(found) != {"strict", "contexts", "checks"}
        or not isinstance(rows, list)
        or not all(
            isinstance(r, dict) and set(r) == {"context", "app_id"} for r in rows
        )
        or set(found["contexts"]) != {row["context"] for row in rows}
    ):
        raise ShippingError("cannot copy the required status checks of the protection")
    return {
        "strict": found["strict"],
        "checks": [
            {
                "context": r["context"],
                "app_id": -1 if r["app_id"] is None else r["app_id"],
            }
            for r in rows
        ],
    }


def protection_body(saved: dict[str, object], linear: bool) -> dict[str, object]:
    """The PUT body that keeps every saved setting; a setting that the PUT cannot copy stops the merge before any write."""
    if (
        set(saved) - KNOWN
        or saved.get("required_pull_request_reviews") is not None
        or saved.get("restrictions") is not None
        or _enabled(saved, "required_signatures")
    ):
        raise ShippingError(
            "The protection holds a setting that this step cannot copy, so nothing "
            "was changed or merged. Merge by hand with the maintainer's yes."
        )
    return {
        "required_status_checks": _checks(saved),
        "enforce_admins": _enabled(saved, "enforce_admins"),
        "required_pull_request_reviews": None,
        "restrictions": None,
        "required_linear_history": linear,
        **{flag: _enabled(saved, flag) for flag in FLAGS},
    }


def _read(shipment: Shipment, endpoint: str) -> dict[str, object] | None:
    try:
        text = gh(shipment.root, "api", endpoint)
    except ShippingError as error:
        if UNPROTECTED in str(error):
            return None
        raise
    return dict[str, object](_object(_json(text, "protection"), "protection"))


def _put(shipment: Shipment, endpoint: str, body: dict[str, object]) -> None:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "protection.json"
        path.write_text(json.dumps(body))
        gh(shipment.root, "api", "--method", "PUT", endpoint, "--input", str(path))


def _restore(
    shipment: Shipment, endpoint: str, saved: dict[str, object], body: dict[str, object]
) -> str | None:
    """None once the protection reads back as saved; else the reason it does not."""
    reason = "no attempt was made"
    for attempt in range(ATTEMPTS):
        try:
            _put(shipment, endpoint, body)
            break
        except ShippingError as error:
            reason = str(error)
            if attempt + 1 < ATTEMPTS:
                time.sleep(2**attempt)
    else:
        return f"{reason}; put this body back by hand: {json.dumps(body)}"
    try:
        now = _read(shipment, endpoint)
    except ShippingError as error:
        return f"the read back failed: {error}"
    if _plain(now) != _plain(saved):
        return f"the protection differs from the saved copy {json.dumps(_plain(saved))}"
    return None


@contextmanager
def _stop_as_exit() -> Generator[None]:
    """A stop signal raises, so the protection is put back before the process ends."""

    def stop(number: int, _frame: object) -> None:
        raise SystemExit(128 + number)

    held = {name: signal.signal(name, stop) for name in STOPS}
    try:
        yield
    finally:
        for name, handler in held.items():
            signal.signal(name, handler)


@contextmanager
def _hold_stops() -> Generator[list[int]]:
    """A stop signal waits until the block ends; the caller ends the process after it has reported."""
    stopped = list[int]()
    held = {
        name: signal.signal(name, lambda number, _frame: stopped.append(number))
        for name in STOPS
    }
    try:
        yield stopped
    finally:
        for name, handler in held.items():
            signal.signal(name, handler)


def merge_join(shipment: Shipment) -> None:
    """Merge a verified join with a merge commit; the protection of its base is lifted for the merge only."""
    if shipment.method != "join":
        raise ShippingError("The protection step is only for a join pull request")
    endpoint = f"repos/{shipment.repository}/branches/{shipment.base}/protection"
    saved = _read(shipment, endpoint)
    merge = (
        "pr",
        "merge",
        shipment.pr_url,
        "--merge",
        "--match-head-commit",
        shipment.head_sha,
    )
    if saved is None or not _enabled(saved, "required_linear_history"):
        gh(shipment.root, *merge)
        return
    lifted, kept = protection_body(saved, False), protection_body(saved, True)
    merged = False
    with _stop_as_exit():
        try:
            _put(shipment, endpoint, lifted)
            gh(shipment.root, *merge)
            merged = True
        finally:
            with _hold_stops() as stopped:
                problem = _restore(shipment, endpoint, saved, kept)
            if problem:
                state = "was merged" if merged else "was not merged"
                raise ShippingError(
                    f"The join {state}, but the protection of {shipment.base} was not put back: {problem}"
                )
            if stopped:
                raise SystemExit(128 + stopped[0])
