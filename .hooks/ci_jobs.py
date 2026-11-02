"""CI jobs for a project with Swift: Linux checks, macOS Swift checks and one required check."""

import json
import os
import re
import subprocess
import sys
import urllib.request
from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from contextlib import redirect_stdout, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from gate_config import LANGUAGES, GateConfig, Group, JsonObject

FILTER_LANGUAGES = sorted({*LANGUAGES.values(), "swift"})


class LanguageFilter(NamedTuple):
    only: tuple[str, ...] = ()
    skip: tuple[str, ...] = ()


def add_language_filters(parser: ArgumentParser) -> ArgumentParser:
    exclusive = parser.add_mutually_exclusive_group()
    for flag, help_text in (
        ("only", "Run only the groups of this language and their dependency installs"),
        ("skip", "Skip the groups of this language"),
    ):
        exclusive.add_argument(
            f"--{flag}-language",
            action="append",
            choices=FILTER_LANGUAGES,
            default=[],
            help=help_text,
        )
    return parser


NO_LANGUAGES = LanguageFilter()


def language_filter(args: Namespace) -> LanguageFilter:
    return LanguageFilter(tuple(args.only_language), tuple(args.skip_language))


def language_groups(groups: list[Group], languages: LanguageFilter) -> list[Group]:
    """Groups of the chosen languages; a group kept by `only` keeps its ancestors' lockfiles gates."""
    only, skip = languages
    if not only and not skip:
        return groups

    def chosen(group: Group) -> bool:
        language = group.get("language")
        return language not in skip and (not only or language in only)

    paths = [PurePosixPath(group["path"]) for group in groups if chosen(group)]
    result: list[Group] = []
    for group in groups:
        if chosen(group):
            result.append(group)
        elif only and group.get("language"):
            installs = [g for g in group["checks"] if g.get("role") == "lockfiles"]
            if installs and any(
                PurePosixPath(group["path"]) in p.parents for p in paths
            ):
                result.append({**group, "checks": installs})
    names = ", ".join(group["path"] for group in result) or "none"
    print(f"Language filter: checking {names}")
    return result


def has_swift(groups: list[Group]) -> bool:
    return any(group.get("language") == "swift" for group in groups)


def impact_runner(groups: list[Group]) -> str:
    """Xcode runs on macOS; every other selection stays on Linux."""
    return "macos-latest" if has_swift(groups) else "ubuntu-latest"


BUN_RELEASES = "https://api.github.com/repos/oven-sh/bun/releases?per_page=5"
EXACT_VERSION = re.compile(r"\d+\.\d+\.\d+")
BUN_TAG = re.compile(r"bun-v(\d+\.\d+\.\d+)")


def bun_releases() -> list[JsonObject]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "hard-eng"}
    if token := os.environ.get("GH_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(BUN_RELEASES, headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        releases = json.load(response)
    return [item for item in releases if isinstance(item, dict)]


def released_bun(release: JsonObject, cutoff: datetime) -> str | None:
    tag, stamp = release.get("tag_name"), release.get("published_at")
    found = BUN_TAG.fullmatch(tag) if isinstance(tag, str) else None
    if (
        found is None
        or release.get("draft") is not False
        or release.get("prerelease") is not False
        or not isinstance(stamp, str)
        or datetime.fromisoformat(stamp) > cutoff
    ):
        return None
    return found[1]


def bootstrap_bun(
    tools: list[str], releases: Callable[[], list[JsonObject]] | None = None
) -> str | None:
    """An exact Bun version lets a runner's installed or cached Bun serve setup-bun."""
    pinned = next((tool[4:] for tool in tools if tool.startswith("bun@")), "")
    if EXACT_VERSION.fullmatch(pinned):
        return pinned
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return None
    cutoff = datetime.now(UTC) - timedelta(days=2)
    try:
        versions = [
            released_bun(release, cutoff) for release in (releases or bun_releases)()
        ]
    except (OSError, ValueError):
        return None
    return max(
        (version for version in versions if version),
        key=lambda version: tuple(map(int, version.split("."))),
        default=None,
    )


def impact_outputs(
    root: Path, base: str, proven: Callable[[str], bool], languages: LanguageFilter
) -> int:
    """Tell CI the runner, the tools and whether Swift is affected, before tools exist."""
    from ci_setup import impact_tools, push_base, require_ci_base
    from gate_config import affected_groups, parse_config

    require_ci_base(base)
    base = push_base(root, base) or base
    done = False
    with redirect_stdout(sys.stderr), suppress(OSError, subprocess.SubprocessError):
        done = proven(base)
    if done:
        print("docs_only=true\nrunner=" + impact_runner([]) + "\napple=false")
        if bun := bootstrap_bun([]):
            print(f"bun={bun}")
        return 0
    config = parse_config((root / "hard-eng.gates.json").read_text())
    groups: list[Group] = [
        *config["packages"],
        {"path": ".", "checks": config["shared"]},
    ]
    with redirect_stdout(sys.stderr):
        selected = affected_groups(root, groups, base)
        needed = language_groups(selected, languages)
    docs_only = bool(config["packages"]) and len(selected) == 1
    print(f"docs_only={str(docs_only).lower()}")
    tools = impact_tools(root, needed)
    print("tools=" + " ".join(tools))
    print("runner=" + impact_runner(selected))
    print(f"apple={str(has_swift(selected)).lower()}")
    if bun := bootstrap_bun(tools):
        print(f"bun={bun}")
    return 0


LINUX_RUNNER = "vars.CI_RUNS_ON && fromJSON(vars.CI_RUNS_ON) || 'ubuntu-latest'"
MACOS_RUNNER = (
    "vars.CI_MACOS_RUNS_ON && fromJSON(vars.CI_MACOS_RUNS_ON) || 'macos-latest'"
)
LINUX_HEADER = "    runs-on: ${{ " + LINUX_RUNNER + " }}\n"
MACOS_HEADER = "    runs-on: ${{ " + MACOS_RUNNER + " }}\n"
IMPACT_NAME = "  impact:\n    name: impact\n"
CHECK_NAME = "  hard-eng:\n    name: hard-eng\n"
CHECK_JOB = CHECK_NAME + LINUX_HEADER
CHECKOUT = re.compile(
    r"(?m)^      - uses: actions/checkout@[^\n]*\n(?:        [^\n]*\n)*"
)
IMPACT_BASE = (
    "          BASE_SHA: ${{ inputs.base_sha || github.event.pull_request.base.sha"
    " || github.event.before }}\n"
)
OLD_OUTPUT = "      runner: ${{ steps.impact.outputs.runner }}\n"
OLD_FALLBACK = '|| echo runner=ubuntu-latest >> "$GITHUB_OUTPUT"'
FALLBACK = "|| printf 'runner=ubuntu-latest\\napple=true\\n' >> \"$GITHUB_OUTPUT\""
RUNNER_JOB = (
    IMPACT_NAME
    + LINUX_HEADER
    + "    timeout-minutes: 5\n    outputs:\n"
    + OLD_OUTPUT
    + "      apple: ${{ steps.impact.outputs.apple }}\n    steps:\n%s"
    + "      - name: Choose the runner\n        id: impact\n        env:\n"
    + IMPACT_BASE
    + "          GH_TOKEN: ${{ github.token }}\n"
    + '        run: python3 .hooks/hard-eng.py impact --base "$BASE_SHA" >> "$GITHUB_OUTPUT" '
    + FALLBACK
    + "\n\n"
)
SPLIT_HEADER = (
    "    needs: impact\n    if: ${{ !cancelled() }}\n"
    "    runs-on: ${{ needs.impact.outputs.runner == 'macos-latest' && 'macos-latest' || ("
    + LINUX_RUNNER
    + ") }}\n"
)
LINUX_JOB = "  linux:\n    name: hard-eng-linux\n" + LINUX_HEADER
APPLE_JOB = (
    "  apple:\n    name: hard-eng-apple\n    needs: impact\n"
    "    if: ${{ needs.impact.outputs.apple != 'false' }}\n" + MACOS_HEADER
)
GATE_JOB = (
    CHECK_NAME
    + "    needs: [impact, linux, apple]\n    if: ${{ !cancelled() }}\n"
    + LINUX_HEADER
    + """    timeout-minutes: 5
    steps:
      - name: Require every check job to pass
        env:
          IMPACT: ${{ needs.impact.result }}
          LINUX: ${{ needs.linux.result }}
          APPLE: ${{ needs.apple.result }}
        run: |
          echo "impact: $IMPACT, linux: $LINUX, apple: $APPLE"
          [ "$IMPACT" = success ] && [ "$LINUX" = success ] && { [ "$APPLE" = success ] || [ "$APPLE" = skipped ]; }
"""
)
HOSTED_HEADER = "    runs-on: ubuntu-latest\n"
OLD_RUNNER_HEADER = (
    "    needs: impact\n    if: ${{ !cancelled() }}\n"
    "    runs-on: ${{ needs.impact.outputs.runner || 'macos-latest' }}\n"
)
NEXT_JOB = re.compile(r"(?m)^  [\w-]+:\n")
CHECK_COMMAND = '.hooks/hard-eng.py check --base "$BASE_SHA"'


def with_language(body: str, flag: str) -> str:
    return re.sub(
        r'(\.hooks/hard-eng\.py (?:impact|check) --base "\$BASE_SHA")',
        lambda match: f"{match[1]} {flag}",
        body,
    )


def migrate_swift_runner(config: GateConfig, content: str) -> str:
    """A project with a Swift group runs only its Swift checks on macOS; Linux runs the rest."""
    if not has_swift(config["packages"]) or "\n  apple:\n" in content:
        return content
    split = "  impact:\n" in content
    header = CHECK_NAME + SPLIT_HEADER if split else CHECK_JOB
    start = content.find(header)
    following = NEXT_JOB.search(content, start + len(header))
    end = len(content) if following is None or start < 0 else following.start()
    checkout = CHECKOUT.search(content)
    head = content[:start]
    if (
        content.count(header) != 1
        or checkout is None
        or CHECK_COMMAND not in content[start:end]
        or (split and (OLD_OUTPUT not in head or OLD_FALLBACK not in head))
    ):
        print(
            "CI runner not added: .github/workflows/hard-eng.yml is customised. "
            "Add the impact, linux and apple jobs from the Hard Eng generator and "
            "make the hard-eng job require them so Swift checks run on macOS only.",
            file=sys.stderr,
        )
        return content
    body = content[start + len(header) : end].rstrip("\n") + "\n\n"
    if split:
        head = head.replace(
            OLD_OUTPUT,
            OLD_OUTPUT + "      apple: ${{ steps.impact.outputs.apple }}\n",
            1,
        ).replace(OLD_FALLBACK, FALLBACK, 1)
    else:
        head += RUNNER_JOB % checkout[0]
    linux = LINUX_JOB + with_language(body, "--skip-language swift")
    apple = APPLE_JOB + with_language(body, "--only-language swift")
    jobs = head + linux + apple + GATE_JOB
    return jobs + "\n" + content[end:] if end < len(content) else jobs


BUN_LATEST = re.compile(
    r"(?m)^(      - uses: oven-sh/setup-bun@[^\n]*\n        with:\n          bun-version: )latest$"
)
BUN_VERSION = "${{ steps.impact.outputs.bun || 'latest' }}"


def migrate_bun_version(content: str) -> str:
    """Ask setup-bun for the exact version the impact step resolved, in every job that has that step."""
    jobs = re.split(r"(?m)^(?=  [A-Za-z0-9_-]+:\n)", content)
    return "".join(
        BUN_LATEST.sub(lambda match: match[1] + BUN_VERSION, job)
        if "        id: impact\n" in job
        else job
        for job in jobs
    )


def migrate_runner_variable(content: str) -> str:
    """Move the generated jobs' hosted runner onto the CI_RUNS_ON variable; a failed impact step stays on Linux."""
    for old, new in (
        (IMPACT_NAME + HOSTED_HEADER, IMPACT_NAME + LINUX_HEADER),
        (CHECK_NAME + HOSTED_HEADER, CHECK_JOB),
        (CHECK_NAME + OLD_RUNNER_HEADER, CHECK_NAME + SPLIT_HEADER),
        (
            '|| echo runner=macos-latest >> "$GITHUB_OUTPUT"',
            '|| echo runner=ubuntu-latest >> "$GITHUB_OUTPUT"',
        ),
    ):
        content = content.replace(old, new, 1)
    return content
