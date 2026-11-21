"""The visible-change test and the shipping checks for screen evidence: measured captures, the look record and the plan's reference."""

import fnmatch
import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, cast
from urllib.parse import urlparse

from gate_config import JsonValue
from plans import _is_test as is_test_path
from ui_rules import COMMENT_LINE, is_theme_path

HTTP_STATUS_LINE = re.compile(r"(?im)^HTTP/\S+\s+(\d{3})\b")
CONTENT_TYPE_HEADER = re.compile(r"(?im)^content-type:\s*([^\r\n]+)")
CONTENT_LENGTH_HEADER = re.compile(r"(?im)^content-length:\s*([^\r\n]+)")
MARKUP = frozenset(
    (".tsx", ".jsx", ".vue", ".svelte", ".astro", ".html", ".css", ".scss", ".less")
)
ASSETS = frozenset(
    (".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico", ".svg")
    + (".woff", ".woff2", ".ttf", ".otf")
)
CATALOG_FOLDERS = frozenset(("l10n", "locales", "i18n", "messages"))
PAGE_WRITE = re.compile(
    r"innerHTML|textContent|createElement|\.style\b|className|classList"
)
SURFACE_ROUTE = re.compile(r"(?m)^Surface: *\w+ — (/\S*?)[,\s]")
TEMPLATE_MARKUP = re.compile(r"""(?:^|[\s`'">])</?[a-z][\w-]*(?:\s[^<>]*)?/?>""")
STRING_LITERAL = re.compile(r"""(["'])(?:(?!\1)[^\\\n]|\\.)+\1""")
SWIFT_VIEW = re.compile(
    r"\b(?:struct|class|extension)\s+\w+\s*:[^{]*\b(?:View|UIView|NSView|UIViewController|NSViewController)\b"
)
UX_SECTION = re.compile(r"(?ms)^## ux_reference\n(.*?)(?=^## |\Z)")
NOT_APPLICABLE = re.compile(r"N/A — \S")
UNCHANGED_LINE = re.compile(
    r"N/A — unchanged: !\[[^\]]*\]\(([^)\s]+)\) !\[[^\]]*\]\(([^)\s]+)\) — \S"
)
CAPTURE_NAME = re.compile(r"(.+)-(\d+)\.png")
NATIVE = (".dart", ".swift")


@dataclass(frozen=True)
class Change:
    path: str
    patch: str | None
    text: str | None = None


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def changed_lines(patch: str) -> list[str]:
    return [
        line[1:]
        for line in patch.splitlines()
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]


def is_visible(change: Change) -> bool:
    """Whether the change alters what a user sees: a test file never does; a file with no patch always may."""
    path = PurePosixPath(change.path)
    if is_test_path(path):
        return False
    if change.patch is None:
        return True
    lines = changed_lines(change.patch)
    if not any(line.strip() and not COMMENT_LINE.match(line) for line in lines):
        return False
    suffix = path.suffix.lower()
    if suffix in MARKUP or suffix in ASSETS or is_theme_path(change.path):
        return True
    if suffix == ".arb" or (
        suffix == ".json" and CATALOG_FOLDERS & {part.lower() for part in path.parts}
    ):
        return True
    text = change.text if change.text is not None else "\n".join(lines)
    if change.text is None and suffix in {".dart", ".swift"}:
        return suffix == ".swift" or "lib" in path.parts
    if suffix == ".dart":
        removed = any(
            line.startswith("-") and not line.startswith("---")
            for line in change.patch.splitlines()
        )
        return "lib" in path.parts and (
            removed
            or "Widget" in text
            or any(STRING_LITERAL.search(line) for line in lines)
        )
    if suffix == ".swift":
        return bool(SWIFT_VIEW.search(text))
    return suffix in {".js", ".ts"} and any(
        PAGE_WRITE.search(line) or TEMPLATE_MARKUP.search(line) for line in lines
    )


def matches(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def ui_names(item: Mapping[str, object], patterns: list[str]) -> list[tuple[str, bool]]:
    """The names of a changed file under `ui_paths`: its new name, or the old name of a file moved out (a removal, so no patch)."""
    name = str(item["filename"])
    if matches(name, patterns):
        return [(name, True)]
    previous = item.get("previous_filename")
    if previous is not None and matches(str(previous), patterns):
        return [(str(previous), False)]
    return []


def visible_files(changes: list[Change]) -> list[str]:
    return [change.path for change in changes if is_visible(change)]


def reference_section(plan_text: str) -> str:
    found = UX_SECTION.search(plan_text)
    return found[1].strip() if found else ""


def reference_problem(
    plan_text: str, visible: list[str], body: str, unchanged_note: bool
) -> str | None:
    """A not-applicable ux_reference, or the PR note `UI appearance: unchanged`, on a visible change."""
    if not visible:
        return None
    reference = reference_section(plan_text)
    named = ", ".join(visible[:3]) + (
        f" and {len(visible) - 3} more" if len(visible) > 3 else ""
    )
    if NOT_APPLICABLE.match(reference) and not UNCHANGED_LINE.match(reference):
        return (
            f"the branch changes what users see ({named}), but ux_reference says N/A; "
            "write the real reference, or `N/A — unchanged: ![Before](<file>) ![After](<file>) — <screen and state>` "
            "with equal captures of the base and the head"
        )
    if unchanged_note and not UNCHANGED_LINE.match(reference):
        return (
            f"`UI appearance: unchanged` on a visible change ({named}) stands only beside the plan line "
            "`N/A — unchanged: ![Before](<file>) ![After](<file>) — <screen and state>`"
        )
    return None


def browser_records(root: Path) -> list[dict[str, object]]:
    folder = root / ".hard-eng/browser"
    found: list[dict[str, object]] = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            record = json.loads(path.read_text())
        except ValueError:
            continue
        if isinstance(record, dict) and "sha256" in record and "image" in record:
            found.append(record)
    return found


GUIDELINES = (
    "textContrastGuideline",
    "labeledTapTargetGuideline",
    "iOSTapTargetGuideline",
    "androidTapTargetGuideline",
)


def guideline_problem(root: Path, visible: list[str]) -> str | None:
    """Each changed Flutter screen file has a widget test that imports it and checks the four accessibility guidelines."""
    from flutter_screens import flutter_packages, screen_files

    screens = [name for name in screen_files(root, visible) if name.endswith(".dart")]
    packages = flutter_packages(root)
    for screen in screens:
        base = next(item for item in packages if screen.startswith(f"{item}lib/"))
        inside = screen.removeprefix(f"{base}lib/")
        tests = [
            path.read_text(errors="replace")
            for path in sorted((root / base / "test").rglob("*_test.dart"))
        ]
        covering = [
            text for text in tests if inside in text and "meetsGuideline" in text
        ]
        if not covering:
            return f"the Flutter screen {screen} changed, but no widget test imports it and calls meetsGuideline; add one"
        for guideline in GUIDELINES:
            if not any(guideline in text for text in covering):
                return f"the widget test for {screen} does not check {guideline}; add it with meetsGuideline"
    return None


def merge_base(root: Path, base_ref: str) -> str:
    remote_ref = f"origin/{base_ref}"
    done = subprocess.run(
        ["git", "merge-base", "HEAD", remote_ref],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() if done.returncode == 0 else ""


def unchanged_problem(root: Path, reference: str, head: str, base: str) -> str | None:
    """The plan's `N/A — unchanged:` pair: equal captures at every width, the Before at the base, the After at the head, each from a clean checkout."""
    from browser import WIDTHS

    found = UNCHANGED_LINE.match(reference)
    if found is None:
        return None
    folder = (root / ".hard-eng/browser").resolve()
    stems = []
    for link in (found[1], found[2]):
        path = (root / link).resolve()
        name = CAPTURE_NAME.fullmatch(path.name)
        if path.parent != folder or name is None:
            return f"the unchanged pair must name captures in .hard-eng/browser, not {link}"
        stems.append(name[1])
    records = {str(item["image"]): item for item in browser_records(root)}
    for width in WIDTHS:
        pair = [records.get(f"{stem}-{width}.png") for stem in stems]
        if None in pair:
            return f"the unchanged pair has no measured record at {width} px; capture it at every width"
        before, after = cast(list[dict[str, object]], pair)
        if before["sha256"] != after["sha256"]:
            return f"the unchanged pair differs at {width} px; the screen changed, so write a real ux_reference"
        if before["commit"] != base or after["commit"] != head:
            return f"the unchanged pair must be a Before taken at the base ({base[:12]}) and an After taken at the head ({head[:12]}) at {width} px"
        if before.get("dirty") or after.get("dirty"):
            return f"the unchanged pair was taken with uncommitted changes at {width} px; commit and capture again"
    return None


def on_route(captured: str, route: str) -> bool:
    """Whether a captured page is the route itself or a path, query or fragment below it; the home route `/` is the home page only."""
    if route == "/":
        return captured == "/" or captured[:2] in ("/?", "/#")
    rest = captured.removeprefix(route)
    return captured.startswith(route) and (
        not rest or route.endswith("/") or rest[0] in "/?#"
    )


def _stem(record: dict[str, object]) -> str:
    name = CAPTURE_NAME.fullmatch(str(record["image"]))
    return name[1] if name else str(record["image"])


def _set_problem(
    records: list[dict[str, object]], stem: str, head: str, route: str
) -> str | None:
    """Why one capture set is not a clean measured set of the head, or None."""
    from browser import WIDTHS

    for width in WIDTHS:
        peer = next((r for r in records if r["image"] == f"{stem}-{width}.png"), None)
        if peer is None:
            return f"the After capture {stem} has no measured record at {width} px; capture it at every width"
        if route and not on_route(str(peer.get("route", "")), route):
            return f"the After capture {peer['image']} is of the page {peer.get('route') or 'unknown'}, but the plan's Surface names {route}; capture the changed screen"
        if peer.get("commit") != head or peer.get("dirty"):
            return f"the After capture {peer['image']} was not taken at the head ({head[:12]}) from a clean tree; commit, then capture again"
        if peer.get("findings"):
            rules = sorted(
                {
                    str(item.get("rule"))
                    for item in cast(list[dict[str, object]], peer["findings"])
                }
            )
            return f"the measured capture {peer['image']} has findings ({', '.join(rules)}); fix the screen and capture it again"
    return None


def measured_problem(
    root: Path, head: str, after: list[bytes], route: str = ""
) -> str | None:
    """Each After image is a measured capture of the head from a clean tree with no finding, and its name has a record at every width; of several sets with the same image, those taken at the head all count."""
    records = browser_records(root)
    for data in after:
        digest = sha256(data)
        stems = list(
            dict.fromkeys(_stem(item) for item in records if item["sha256"] == digest)
        )
        if not stems:
            return (
                f"an After image (sha256 {digest[:12]}) matches no measured capture in .hard-eng/browser; "
                "take After images with `browser capture` or `browser measure`, and draw rings only with --ring"
            )
        current = [
            stem
            for stem in stems
            if any(
                item.get("commit") == head and not item.get("dirty")
                for item in records
                if _stem(item) == stem
            )
        ]
        for stem in current or stems:
            if problem := _set_problem(records, stem, head, route):
                return problem
    return None


def look_record_problem(
    record: dict[str, object], head: str, body: str, after: list[bytes]
) -> str | None:
    """Why one look record does not back the PR: not clean, lacking an After image or a rule line, or not the block in the body."""
    import look
    from plans import split_rule_line, usability_rules

    if record.get("outcome") != "clean":
        return f"Look review: the record for {head[:12]} is {record.get('outcome')}; fix the screen and run `look` again"
    images = cast(list[dict[str, object]], record.get("images", []))
    hashes = {item["sha256"] for item in images}
    if missing := [d for d in map(sha256, after) if d not in hashes]:
        return f"Look review: the record does not cover the After image {missing[0][:12]}; run `look` on the After images"
    wanted = [name for name, _ in usability_rules()]
    lines = cast(list[str], record.get("rules", []))
    if [split_rule_line(line)[0] for line in lines] != wanted or any(
        split_rule_line(line)[1] == "Fail" for line in lines
    ):
        return "Look review: the record lacks a line for each Usability rule or holds a Fail; run `look` again"
    if problem := look.block_problem(body, len(after)):
        return f"Look review: {problem}"
    if look.block_text(record) not in body.replace("\r\n", "\n"):
        return "Look review: the PR block is not the block of this head's record; paste the block that `look` printed"
    return None


def look_problem(root: Path, head: str, body: str, after: list[bytes]) -> str | None:
    """A clean look record for this head that covers each After image, and a PR block that matches it."""
    import look

    records = look.records_for(root, head)
    if not records:
        return f"Look review: no record for {head[:12]}; run `python3 .hooks/hard-eng.py look <After images>` and paste its block into the PR body"
    problems = [look_record_problem(r, head, body, after) for r in records]
    return None if None in problems else problems[0]


def is_native(visible: list[str]) -> bool:
    return bool(visible) and all(name.endswith(NATIVE) for name in visible)


def surface_route(plan_text: str) -> str:
    """The route that the plan's `Surface: Existing — /route, rendered by ...` line names, or an empty string."""
    found = SURFACE_ROUTE.search(reference_section(plan_text))
    return found[1] if found else ""


def evidence_problem(
    root: Path,
    head: str,
    body: str,
    after: list[bytes],
    visible: list[str],
    route: str = "",
) -> str | None:
    if not is_native(visible) and (
        problem := measured_problem(root, head, after, route)
    ):
        return problem
    return look_problem(root, head, body, after)


def ship_problem(
    root: Path,
    head: str,
    body: str,
    files: list[dict[str, object]],
    patterns: list[str],
    plan_text: str,
    after_urls: list[str],
    base_ref: str,
    videos: int = 0,
) -> str | None:
    """What the PR lacks of screen evidence for its visible changes; None when the checks pass."""
    from gate_config import generated_sources
    from ship_evidence import UI_APPEARANCE_UNCHANGED

    changes = []
    for item in files:
        for name, is_new in ui_names(item, patterns):
            patch = item.get("patch") if is_new else None
            local = root / name
            text = local.read_text(errors="replace") if local.is_file() else None
            changes.append(
                Change(name, patch if isinstance(patch, str) else None, text)
            )
    visible = visible_files(changes)
    visible = [name for name in visible if name not in generated_sources(root, visible)]
    note = bool(UI_APPEARANCE_UNCHANGED.search(body))
    if problem := reference_problem(plan_text, visible, body, note):
        return problem
    if visible and UNCHANGED_LINE.match(reference_section(plan_text)):
        return unchanged_problem(
            root, reference_section(plan_text), head, merge_base(root, base_ref)
        )
    if problem := guideline_problem(
        root, [name for name in visible if (root / name).is_file()]
    ):
        return problem
    if videos and not after_urls and visible and not is_native(visible):
        return "the After is a video only; a web change also needs a measured After image, which `browser capture` writes at every width"
    after = [download(root, url) for url in after_urls]
    if not after:
        return None
    return evidence_problem(root, head, body, after, visible, surface_route(plan_text))


def changed_files(
    root: Path, owner: str, name: str, number: int
) -> list[dict[str, JsonValue]]:
    """The PR's files from the API, each with its name, its old name when renamed and its patch."""
    from shipping import ShippingError, _api_items

    endpoint = f"repos/{owner}/{name}/pulls/{number}/files?per_page=100"
    items = _api_items(root, endpoint, "files", "PR files query")
    for item in items:
        filename = item.get("filename")
        if not isinstance(filename, str) or not filename.strip():
            raise ShippingError("PR files query has an invalid filename")
        previous = item.get("previous_filename")
        if previous is not None and (
            not isinstance(previous, str) or not previous.strip()
        ):
            raise ShippingError("PR files query has an invalid previous filename")
    return items


def file_names(files: list[dict[str, JsonValue]]) -> list[str]:
    """The new name of each changed file, and the old name of each renamed one."""
    names: set[str] = set()
    for item in files:
        names.add(cast(str, item["filename"]))
        if item.get("previous_filename") is not None:
            names.add(cast(str, item["previous_filename"]))
    return sorted(names)


def check_attachment(root: Path, url: str) -> str:
    """The content type of a PR attachment on GitHub; refuses a missing, empty or non-image, non-video one."""
    from shipping import ShippingError, gh

    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/user-attachments/assets/")
    ):
        raise ShippingError("UI evidence URL is not an allowed GitHub attachment")
    # Signed attachment redirects can reject HEAD; keep binary data out of stdout.
    request = ("api", "--method", "GET", "--include", "--silent")
    try:
        response = gh(root, *request, "-H", "Range: bytes=0-0", url)
    except ShippingError:
        # GitHub can time out ranged requests while a plain GET succeeds.
        try:
            response = gh(root, *request, url)
        except ShippingError as error:
            raise ShippingError(
                f"UI evidence attachment is unavailable: {url} ({error})"
            ) from error
    statuses = HTTP_STATUS_LINE.findall(response)
    if not statuses or not 200 <= int(statuses[-1]) < 300:
        raise ShippingError(f"UI evidence attachment is unavailable: {url}")
    content_types = CONTENT_TYPE_HEADER.findall(response)
    content_type = content_types[-1].lower() if content_types else ""
    if not content_type.startswith(("image/", "video/")):
        raise ShippingError("UI evidence attachment is not image or video")
    lengths = CONTENT_LENGTH_HEADER.findall(response)
    if lengths:
        try:
            if int(lengths[-1]) <= 0:
                raise ValueError
        except ValueError as error:
            raise ShippingError("UI evidence attachment has invalid length") from error
    return content_type


def download(root: Path, url: str) -> bytes:
    """The raw bytes of a PR attachment, fetched with the user's own GitHub sign-in."""
    from shipping import ShippingError

    try:
        result = subprocess.run(
            ["gh", "api", "--method", "GET", url],
            cwd=root,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ShippingError(
            f"UI evidence attachment cannot be downloaded: {url}"
        ) from error
    if result.returncode != 0 or not result.stdout:
        raise ShippingError(f"UI evidence attachment cannot be downloaded: {url}")
    return result.stdout


class Described(Protocol):
    @property
    def body(self) -> str: ...
    @property
    def head_sha(self) -> str: ...
    @property
    def base_ref(self) -> str: ...


def ui_evidence(
    root: Path,
    pull: Described,
    files: list[dict[str, JsonValue]],
    patterns: list[str],
    plan: Path | None,
    check_attachment: Callable[[Path, str], str],
) -> None:
    """Raise ValueError when a PR that changes a UI file lacks its screen evidence."""
    from ship_evidence import attachment_urls

    urls = attachment_urls(pull.body, file_names(files), patterns)
    kinds = {url: check_attachment(root, url) for url in urls}
    final = urls[len(urls) // 2 :]
    after = [url for url in final if kinds[url].startswith("image/")]
    videos = sum(kinds[url].startswith("video/") for url in final)
    plan_text = plan.read_text() if plan is not None and plan.is_file() else ""
    problem = ship_problem(
        root,
        pull.head_sha,
        pull.body,
        cast(list[dict[str, object]], files),
        patterns,
        plan_text,
        after,
        pull.base_ref,
        videos,
    )
    if problem:
        raise ValueError(f"UI evidence: {problem}")
