"""Select PR attachments from declared, inspected visual comparison evidence."""

import fnmatch
import re

BEFORE_AFTER_LABEL = re.compile(r"(?m)^\s*(?:Before|After):")
UI_APPEARANCE_UNCHANGED = re.compile(
    r"^UI appearance: unchanged(?:[ \t]*—[ \t]*(.*))?$", re.MULTILINE
)

_ASSET_URL = r"https://github\.com/user-attachments/assets/[^)\s?#]+"
_BEFORE = re.compile(
    rf"^\s*Before:\s*!\[[^\]\r\n]*\]\(({_ASSET_URL})\)\s*$",
    re.MULTILINE,
)
_AFTER = re.compile(
    rf"^\s*After:\s*!\[[^\]\r\n]*\]\(({_ASSET_URL})\)\s*$",
    re.MULTILINE,
)
_RAW_BEFORE = re.compile(
    rf"^[ \t]*Before:[ \t]*\r?\n(?:[ \t]*\r?\n)*[ \t]*({_ASSET_URL})[ \t]*\r?$",
    re.MULTILINE,
)
_RAW_AFTER = re.compile(
    rf"^[ \t]*After:[ \t]*\r?\n(?:[ \t]*\r?\n)*[ \t]*({_ASSET_URL})[ \t]*\r?$",
    re.MULTILINE,
)


def attachment_urls(body: str, paths: list[str], patterns: list[str]) -> list[str]:
    if not any(
        fnmatch.fnmatchcase(path, pattern) for path in paths for pattern in patterns
    ):
        return []
    unchanged = UI_APPEARANCE_UNCHANGED.findall(body)
    if unchanged:
        if (
            len(unchanged) != 1
            or not unchanged[0].strip()
            or BEFORE_AFTER_LABEL.search(body)
        ):
            raise ValueError(
                "Unchanged UI requires one comparison note and no Before/After attachments"
            )
        return []
    before = _BEFORE.findall(body) + _RAW_BEFORE.findall(body)
    after = _AFTER.findall(body) + _RAW_AFTER.findall(body)
    urls = before + after
    if not before or len(before) != len(after) or len(set(urls)) != len(urls):
        raise ValueError(
            "UI changes require distinct Before and After attachments or an explained unchanged appearance; "
            "upload the pair with `gh pr edit <url> --body-file <body.md> --attach <before> --attach <after>` "
            "(he-ship checks: UI evidence in the PR)"
        )
    return urls
