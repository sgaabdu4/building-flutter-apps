"""Fail when a direct dependency trails its newest stable release that is two days old."""

import json
import re
import subprocess
import urllib.parse
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from gate_config import Gate, JsonObject
from tool_setup import RELEASE_AGE_SECONDS

VERSION_LINE = re.compile(r"\S+(?: v\S+|(?=\n[├└]──))")
DIGIT_RUN = re.compile(r"\d+")
RELEASE_VERSION = re.compile(r"(\d+(?:\.\d+)*)(?:\.post(\d+))?")
PUB_PIN = re.compile(
    r"\b([a-z][a-z0-9_]*) (\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.]*[0-9A-Za-z])?)"
)

WAIT = timedelta(seconds=RELEASE_AGE_SECONDS)
MAX_HOLD_DAYS = 14
HOLD_KEYS = {"package", "version", "reason", "until"}
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
Fetch = Callable[[str], object]
Stale = tuple[str, str, str]


def fetch_json(url: str) -> object:
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": "hard-eng-freshness"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def version_key(version: str, *, strict: bool) -> tuple[tuple[int, ...], int] | None:
    """Release numbers, then post number; strict allows no suffix except `.postN`."""
    release = version.partition("+")[0]
    match = RELEASE_VERSION.fullmatch(release)
    if strict and match is None:
        return None
    numbers = [int(part) for part in DIGIT_RUN.findall(match[1] if match else release)]
    while numbers and numbers[-1] == 0:
        numbers.pop()
    return tuple(numbers), int(match[2]) if match and match[2] else -1


def released_before(stamp: object, cutoff: datetime) -> bool:
    return isinstance(stamp, str) and datetime.fromisoformat(stamp) <= cutoff


def newest(candidates: list[str]) -> str | None:
    keyed = [(version_key(item, strict=True), item) for item in candidates]
    return max(((k, v) for k, v in keyed if k is not None), default=(None, None))[1]


def pub_versions(name: str, fetch: Fetch) -> list[JsonObject]:
    package = fetch(f"https://pub.dev/api/packages/{urllib.parse.quote(name)}")
    if not isinstance(package, dict) or not isinstance(package.get("versions"), list):
        raise TypeError(f"pub.dev returned an unreadable record for {name}")
    return [item for item in package["versions"] if not item.get("retracted")]


def pub_eligible(name: str, fetch: Fetch, cutoff: datetime, ceiling: str) -> str | None:
    return newest(
        [
            str(item["version"])
            for item in pub_versions(name, fetch)
            if released_before(item["published"], cutoff)
            and not newer(str(item["version"]), ceiling)
        ]
    )


def pypi_eligible(
    name: str, fetch: Fetch, cutoff: datetime, ceiling: str
) -> str | None:
    """The ceiling is uv's latest: it obeys the project's Python range, a newer release may not."""
    package = fetch(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json")
    if not isinstance(package, dict) or not isinstance(package.get("releases"), dict):
        raise TypeError(f"PyPI returned an unreadable record for {name}")
    return newest(
        [
            version
            for version, files in package["releases"].items()
            if files
            and not all(item.get("yanked") for item in files)
            and not newer(version, ceiling)
            and released_before(
                min(item["upload_time_iso_8601"] for item in files), cutoff
            )
        ]
    )


def newer(target: str | None, current: str) -> bool:
    if target is None:
        return False
    want, have = version_key(target, strict=True), version_key(current, strict=False)
    return want is not None and have is not None and want > have


def behind(
    rows: list[tuple[str, str]],
    eligible: Callable[[str], str | None],
) -> list[Stale]:
    found = [(name, current, eligible(name)) for name, current in rows]
    return [
        (name, current, target)
        for name, current, target in found
        if target and newer(target, current)
    ]


def bun_rows(text: str) -> list[Stale]:
    if not text.lstrip().startswith("bun outdated"):
        raise ValueError("bun outdated printed no report")
    columns: list[str] = []
    rows = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not line.startswith("|") or set(line) <= set("|-"):
            continue
        if cells[0] == "Package":
            columns = cells
        elif columns and len(cells) == len(columns):
            row = dict(zip(columns, cells, strict=True))
            latest = row["Latest"].removesuffix("*").strip()
            if not row["Package"].endswith("(peer)") and newer(latest, row["Current"]):
                rows.append((row["Package"].partition(" ")[0], row["Current"], latest))
    return rows


def dart_rows(text: str) -> dict[str, tuple[str, str]]:
    """Name → current and the newest version pub can resolve beside the others."""
    report = json.loads(text[text.index("{") :])
    return {
        item["package"]: (item["current"]["version"], item["resolvable"]["version"])
        for item in report["packages"]
        if item["kind"] in {"direct", "dev"}
        and item.get("current")
        and item.get("resolvable")
        and item["resolvable"]["version"] != item["current"]["version"]
    }


UV_ROW = re.compile(
    r"[├└]── (?P<name>\S+) v(?P<current>\S+)(?: \([^)]*\))*? \(latest: v(?P<latest>[^)]+)\)$"
)


def uv_rows(text: str) -> list[tuple[str, str, str]]:
    if not VERSION_LINE.match(text):
        raise ValueError("uv tree printed no dependency tree")
    return list(
        dict.fromkeys(
            (match["name"].partition("[")[0], match["current"], match["latest"])
            for line in text.splitlines()
            if (match := UV_ROW.match(line))
        )
    )


def poetry_rows(text: str) -> list[Stale]:
    report = json.loads(text)
    if not isinstance(report, list):
        raise TypeError("poetry show printed no package list")
    return [
        (item["name"], item["version"], item["latest_version"])
        for item in report
        if item["latest_version"] != item["version"]
    ]


PUB_UPGRADE = ("pub", "upgrade", "--major-versions", "--unlock-transitive")
UPGRADES = {
    "bun": "bun update {recursive}--latest --minimum-release-age={age} {names}",
    "dart": f"dart {' '.join(PUB_UPGRADE)} {{names}}",
    "flutter": f"flutter {' '.join(PUB_UPGRADE)} {{names}}",
}


def stale_dependencies(
    tool: str, text: str, fetch: Fetch, now: datetime
) -> list[Stale]:
    cutoff = now - WAIT
    if tool == "bun":
        return bun_rows(text)
    if tool == "poetry":
        return poetry_rows(text)
    if tool in {"dart", "flutter"}:
        rows = dart_rows(text)
        return behind(
            [(name, current) for name, (current, _) in rows.items()],
            lambda name: pub_eligible(name, fetch, cutoff, rows[name][1]),
        )
    rows = uv_rows(text)
    installable = {name: latest for name, _, latest in rows}
    return behind(
        [(name, current) for name, current, _ in rows],
        lambda name: pypi_eligible(name, fetch, cutoff, installable[name]),
    )


def bun_waiting(directory: Path, recursive: bool) -> Callable[[str], bool]:
    """A release Bun cannot install yet, because a dependency it pins is younger than the wait."""

    def waiting(name: str) -> bool:
        age = f"--minimum-release-age={int(WAIT.total_seconds())}"
        done = subprocess.run(
            ["bun", "update", *(["-r"] if recursive else []), "--latest", name]
            + ["--dry-run", age],
            cwd=directory,
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
        blocked = "blocked by minimum-release-age"
        return done.returncode != 0 and blocked in done.stdout + done.stderr

    return waiting


def pub_waiting(
    tool: str, directory: Path, fetch: Fetch, now: datetime
) -> Callable[[str], bool]:
    """A release pub cannot resolve yet, because each pin that blocks it has only younger fixes."""
    cutoff = now - WAIT

    def fixed_only_later(name: str, pinned: str) -> bool:
        fixes = [
            item
            for item in pub_versions(name, fetch)
            if newer(str(item["version"]), pinned)
        ]
        return bool(fixes) and not any(
            released_before(item["published"], cutoff) for item in fixes
        )

    def waiting(name: str) -> bool:
        done = subprocess.run(
            [tool, *PUB_UPGRADE, name, "--dry-run"],
            cwd=directory,
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
        message = done.stdout + done.stderr
        if done.returncode == 0 or "version solving failed" not in message:
            return False
        pins = {
            found[1]: found[2]
            for found in PUB_PIN.finditer(message)
            if found[1] != name
        }
        return bool(pins) and all(fixed_only_later(*pin) for pin in pins.items())

    return waiting


def freshness_waiting(gate: Gate, directory: Path) -> Callable[[str], bool] | None:
    tool = Path(gate["command"][0]).name
    if tool == "bun":
        return bun_waiting(directory, "-r" in gate["command"])
    if tool in {"dart", "flutter"}:
        return pub_waiting(tool, directory, fetch_json, datetime.now(UTC))
    return None


def held(stale: Stale, holds: list[JsonObject], today: date) -> bool:
    name, _, target = stale
    return any(
        hold["package"] == name
        and hold["version"] == target
        and today <= date.fromisoformat(str(hold["until"]))
        for hold in holds
    )


def validate_holds(holds: object, today: date | None = None) -> None:
    today = today or datetime.now(UTC).date()
    if not isinstance(holds, list):
        raise TypeError("holds must be a list")
    for hold in holds:
        if not isinstance(hold, dict) or set(hold) != HOLD_KEYS:
            raise ValueError("Each hold needs package, version, reason and until")
        if not all(isinstance(value, str) and value.strip() for value in hold.values()):
            raise ValueError(
                "Each hold needs a nonblank package, version, reason and until"
            )
        if not DATE.fullmatch(hold["until"]):
            raise ValueError("A hold's until must be a date such as 2026-11-02")
        if date.fromisoformat(hold["until"]) > today + timedelta(days=MAX_HOLD_DAYS):
            raise ValueError(f"A hold ends within {MAX_HOLD_DAYS} days of today")


def validate_gate_holds(gate: Gate) -> None:
    if "holds" not in gate:
        return
    if gate.get("role") != "freshness":
        raise ValueError(f"{gate['name']}: only a freshness check takes holds")
    validate_holds(gate["holds"])


def validate_freshness(
    path: Path,
    gate: Gate,
    fetch: Fetch = fetch_json,
    now: datetime | None = None,
    waiting: Callable[[str], bool] | None = None,
    directory: Path = Path(),
) -> None:
    now = now or datetime.now(UTC)
    tool = Path(gate["command"][0]).name
    try:
        stale = stale_dependencies(tool, path.read_text(), fetch, now)
    except OSError as error:
        raise ValueError(f"Registry unreachable: {error}") from error
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise ValueError(f"{tool} output is unreadable: {error!r}") from error
    if tool == "poetry":
        from poetry_freshness import poetry_targets

        stale = poetry_targets(directory, stale)
    holds: list[JsonObject] = gate.get("holds", [])
    stale = [item for item in stale if not held(item, holds, now.date())]
    if waiting is not None:
        early = [item for item in stale if waiting(item[0])]
        for name, _, target in early:
            print(f"{name} {target} needs a dependency that is not 2 days old yet")
        stale = [item for item in stale if item not in early]
    if stale:
        names = " ".join(dict.fromkeys(name for name, _, _ in stale))
        recursive = "-r " if "-r" in gate["command"] else ""
        step = UPGRADES.get(tool, "").format(
            recursive=recursive, names=names, age=RELEASE_AGE_SECONDS
        )
        step = f"Run `{step}` in a separate PR first (baseline repair)."
        if tool == "uv":
            from uv_freshness import uv_steps

            step = uv_steps(directory, path.read_text(), stale)
        if tool == "poetry":
            from poetry_freshness import poetry_steps

            step = poetry_steps(directory, stale)
        raise ValueError(
            "Outdated direct dependencies: "
            + "; ".join(f"{n} {c} → {t}" for n, c, t in stale)
            + f". {step}"
        )
    print("Every direct dependency is on its newest release at least 2 days old")
