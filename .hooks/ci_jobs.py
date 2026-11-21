"""CI jobs for a project with Swift: Linux checks, macOS Swift checks and one required check."""

import json
import os
import re
import subprocess
import sys
import urllib.request
from argparse import ArgumentParser, ArgumentTypeError, Namespace
from collections.abc import Callable
from contextlib import redirect_stdout, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from gate_config import LANGUAGES, GateConfig, Group, JsonObject

JOB_BOUNDARY = re.compile(r"(?m)^(?=  [A-Za-z0-9_-]+:\n)")
CHECK_BASE_COMMAND = re.compile(
    r'(\.hooks/hard-eng\.py (?:impact|check) --base "\$BASE_SHA")'
)

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


def shard_value(value: str) -> str:
    if value in ("rest", "merge"):
        return value
    if value.isascii() and value.isdecimal() and int(value) > 0:
        return str(int(value))
    raise ArgumentTypeError("--shard takes a shard number, rest or merge")


def add_shard_option(parser: ArgumentParser) -> ArgumentParser:
    parser.add_argument(
        "--shard",
        type=shard_value,
        help="Run test shard N, the gates outside the shards (rest), or merge the shard reports (merge)",
    )
    return parser


def add_walls_command(add_parser: Callable[..., ArgumentParser]) -> None:
    walls = add_parser(
        "text-walls",
        help="List screen text blocks over the caps, or judge server strings with --stdin",
    )
    walls.add_argument("paths", nargs="*")
    walls.add_argument("--stdin", action="store_true")


def add_scope_options(checks: ArgumentParser) -> None:
    checks.add_argument(
        "--without-dependents",
        action="store_true",
        help="Check changed packages only; CI checks their dependents",
    )
    checks.add_argument(
        "--related-tests",
        action="store_true",
        help="Run only JavaScript tests related to the change; CI runs them all",
    )
    checks.add_argument(
        "--quick",
        action="store_true",
        help="Run only format, lint, types and the file secret scan; the Stop hook uses it",
    )
    checks.add_argument(
        "--commit-secrets",
        action="store_true",
        help="Run only the secret scan of the commits since --base, the plan checks and the changed-line text rules; pre-push uses it when CI runs the full check",
    )


NO_LANGUAGES = LanguageFilter()


def language_filter(args: Namespace) -> LanguageFilter:
    return LanguageFilter(tuple(args.only_language), tuple(args.skip_language))


def language_groups(groups: list[Group], languages: LanguageFilter) -> list[Group]:
    """Groups of the chosen languages; a group kept by `only` keeps the lockfiles gate of every folder above it."""
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
        elif only:
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
    from tool_setup import RELEASE_AGE_SECONDS

    cutoff = datetime.now(UTC) - timedelta(seconds=RELEASE_AGE_SECONDS)
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

    require_ci_base(base, root)
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
    return CHECK_BASE_COMMAND.sub(lambda match: f"{match[1]} {flag}", body)


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
    jobs = JOB_BOUNDARY.split(content)
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


def load_checked_policy(
    root: Path, config: GateConfig, workflow_checked: bool = False
) -> None:
    """Load the shipping policy; leaving the push check to CI needs that CI and a commit secret scan. A run inside the workflow needs no check of the workflow."""
    from shipping import ShippingError, load_policy

    policy = load_policy(root)
    if policy is None or policy["pre_push_checks"] != "ci":
        return
    if config.get("scan_git_history", True) is False or not any(
        gate.get("role") == "secrets-history" for gate in config["shared"]
    ):
        raise ShippingError(
            'shipping pre_push_checks "ci" needs the secrets-history gate and '
            "scan_git_history on: pre-push still scans the pushed commits for secrets"
        )
    sharded = any("shards" in g for p in config["packages"] for g in p["checks"])
    if not workflow_checked and (gap := ci_check_gap(root, sharded)):
        raise ShippingError(
            f'shipping pre_push_checks "ci" needs a workflow that runs `hard-eng.py check` '
            f"on every pull request: {gap}. Branch protection cannot be read offline, "
            "so it is not checked"
        )


PAIRED_CONDITION = re.compile(r"[\w.\-]+ != 'true'")


def workflow_jobs(workflow: object) -> dict[object, object]:
    jobs = workflow.get("jobs") if isinstance(workflow, dict) else None
    return jobs if isinstance(jobs, dict) else {}


def workflow_events(workflow: object) -> set[str]:
    triggers = (
        workflow.get("on", workflow.get(True)) if isinstance(workflow, dict) else None
    )
    if isinstance(triggers, str):
        return {triggers}
    return (
        {e for e in triggers if isinstance(e, str)}
        if isinstance(triggers, (list, dict))
        else set()
    )


def pull_request_filters(workflow: object) -> list[str]:
    from workflow_blocking import narrowing_filters

    triggers = (
        workflow.get("on", workflow.get(True)) if isinstance(workflow, dict) else None
    )
    return sorted(narrowing_filters(triggers))


def skips_a_run(node: dict[object, object]) -> str | None:
    """The `if` of a step, or None when it has none or only `${{ !cancelled() }}`."""
    from workflow_blocking import JOB_IF

    condition = node.get("if")
    text = str(condition).strip()
    return None if condition is None or JOB_IF.fullmatch(text) else text


def calling_jobs(workflow: object, called: str) -> list[object]:
    return [
        name
        for name, job in workflow_jobs(workflow).items()
        if isinstance(job, dict) and job.get("uses") == called
    ]


def without_comment(line: str) -> str:
    import shlex

    try:
        return " ".join(shlex.split(line, comments=True))
    except ValueError:
        return ""


def whole_check_arguments(command: str) -> bool:
    """Only --base, --shard and --plan-stage Complete leave the check whole."""
    import shlex

    try:
        words = shlex.split(command)
    except ValueError:
        return False
    stage = (
        words[words.index("--plan-stage") + 1 :][:1]
        if "--plan-stage" in words
        else ["Complete"]
    )
    options = {
        word for word in words[words.index("check") + 1 :] if word.startswith("-")
    }
    return options <= {"--base", "--shard", "--plan-stage"} and stage == ["Complete"]


def check_scope(command: str) -> str:
    """ "" for a check with no --shard, else `rest`, `merge` or `part` (a numbered shard)."""
    import shlex

    try:
        words = shlex.split(command)
    except ValueError:
        return "part"
    if "--shard" not in words[:-1]:
        return ""
    value = words[words.index("--shard") + 1]
    return value if value in {"rest", "merge"} else "part"


def job_always_runs(name: object, jobs: dict[object, object]) -> bool:
    """A job that no condition, and no `needs` job with one, can skip."""
    from workflow_blocking import skippable_jobs

    return isinstance(jobs.get(name), dict) and name not in skippable_jobs(jobs)


CHAIN_BREAK = re.compile(r"[|;]|(?<!&)&(?!&)")
PRINTED_OR_CONDITIONAL = re.compile(r"^(echo|printf)\b|[|;!]|(?<!&)&(?!&)")


def ends_the_command(rest: str) -> bool:
    """The check is the last command of the run: it ends its line or is followed by `&&` and a command with no pipe, `;` or lone `&`, and no later line follows, so the step takes the check's exit status."""
    line, _, later = rest.partition("\n")
    line = line.strip()
    return not later.strip() and (
        not line or (line.startswith("&&") and not CHAIN_BREAK.search(line))
    )


SHELL_OPEN = {"if", "case", "for", "while", "until"}
SHELL_CLOSE = {"fi", "esac", "done"}
SHELL_BRANCH = {"then", "else", "elif", "do"}
CHAIN_OPERATORS = re.compile(r"[;&|]")
STEP_ENDING = re.compile(
    r"(?<![\w$.-])(?:exit|return)(?![\w-])(?!\s+[1-9]\d*(?![\w$]))"
)
FAILING_EXIT = re.compile(r"exit\s+[1-9]\d*")
BODY_AFTER_KEYWORD = re.compile(r"\b(then|do)\s+\S|\b(fi|done|esac)\b")


def control_lines_only_fail(lines: list[str]) -> bool:
    """Each shell block before the check ends closed and only prints or exits non-zero, so it cannot skip the check with a pass; the generated launcher line is allowed."""
    from workflow_blocking import LAUNCHER, SPACES

    depth = 0
    for line in lines:
        words = line.split()
        if not words or LAUNCHER.fullmatch(SPACES.sub(" ", line.strip())):
            continue
        if words[0] in SHELL_OPEN:
            if BODY_AFTER_KEYWORD.search(line):
                return False
            depth += 1
        elif words[0] in SHELL_CLOSE:
            depth -= 1
        elif words[0] in SHELL_BRANCH:
            if BODY_AFTER_KEYWORD.search(line):
                return False
        elif depth and not (
            (words[0] in {"echo", "printf"} and not CHAIN_OPERATORS.search(line))
            or FAILING_EXIT.fullmatch(line.strip())
        ):
            return False
    return depth == 0


def shell_runs_it(raw: str, text: str, start: int) -> bool:
    """No shell condition, loop or earlier `exit` or `return` that can end the step with success can skip the command, and its line does not only print it."""
    if STEP_ENDING.search(text[:start]):
        return False
    lines = raw.splitlines()
    index = text.count("\n", 0, start)
    if not control_lines_only_fail(lines[: index + 1]):
        return False
    first = lines[index].split()
    if first and first[0] in SHELL_OPEN | SHELL_CLOSE | SHELL_BRANCH:
        return False
    before = text[text.rfind("\n", 0, start) + 1 : start].strip()
    return not PRINTED_OR_CONDITIONAL.search(before)


def step_runs_check(job: object, step: object, scope: str = "") -> bool:
    """The step runs `check` whole, or the one `scope` of its shards, and neither the job, the step nor the shell line turns a failure into a pass."""
    from ci_setup import HARD_ENG_CHECK_COMMAND
    from workflow_blocking import SAFE_FALSE

    if not isinstance(job, dict) or not isinstance(step, dict):
        return False
    if any(n.get("continue-on-error", False) not in SAFE_FALSE for n in (job, step)):
        return False
    raw = str(step.get("run")).replace("\\\n", " ")
    text = "\n".join(without_comment(line) for line in raw.splitlines())
    return any(
        whole_check_arguments(m[0])
        and check_scope(m[0]) == scope
        and ends_the_command(text[m.end() :])
        and shell_runs_it(raw, text, m.start())
        for m in HARD_ENG_CHECK_COMMAND.finditer(text)
    )


def job_covers(
    name: object, job: object, jobs: dict[object, object], scope: str
) -> bool:
    """An always-running job whose steps for `scope` cover every case: one has no `if`, or two have the `== 'true'` and `!= 'true'` forms of one condition."""
    steps = job.get("steps") if isinstance(job, dict) else None
    conditions = {
        skips_a_run(step)
        for step in (steps if job_always_runs(name, jobs) else None) or []
        if step_runs_check(job, step, scope)
    }
    return None in conditions or any(
        isinstance(c, str)
        and PAIRED_CONDITION.fullmatch(c)
        and c.replace("!= 'true'", "== 'true'") in conditions
        for c in conditions
    )


def runs_whole_check(workflow: object, sharded: bool = False) -> bool:
    """The always-running jobs cover every gate: one check with no --shard, or `--shard rest` alone with no sharded gate, or `rest` and `merge` with sharded gates (the merge fails when a numbered shard sent no report)."""
    jobs = workflow_jobs(workflow)

    def covered(scope: str) -> bool:
        return any(job_covers(n, j, jobs, scope) for n, j in jobs.items())

    return covered("") or (covered("rest") and (not sharded or covered("merge")))


def ci_check_gap(root: Path, sharded: bool = False) -> str | None:
    """Why no workflow runs the check on every pull request, or None when one does."""
    import yaml

    from ci_setup import project_workflows

    loaded: dict[str, object] = {}
    for path in project_workflows(root):
        try:
            loaded[path.name] = yaml.safe_load(path.read_text())
        except yaml.YAMLError:
            continue
    gap = "no workflow in .github/workflows runs it on every pull_request, directly or by calling the one that has only workflow_call"
    for name, workflow in loaded.items():
        if not runs_whole_check(workflow, sharded):
            continue
        if filters := pull_request_filters(workflow):
            gap = f"the pull_request trigger of {name} has a `{filters[0]}` filter"
        elif "pull_request" in workflow_events(workflow):
            return None
        if (called := called_gap(loaded, name)) is not None:
            if not called:
                return None
            gap = called
    return gap


def called_gap(loaded: dict[str, object], name: str) -> str | None:
    """None when no pull_request workflow calls `name`; "" when one calls it whole; else why not."""
    found = None
    for caller_name, caller in loaded.items():
        jobs = calling_jobs(caller, f"./.github/workflows/{name}")
        if not jobs or "pull_request" not in workflow_events(caller):
            continue
        if filters := pull_request_filters(caller):
            found = (
                f"the pull_request trigger of {caller_name} has a `{filters[0]}` filter"
            )
        elif not any(job_always_runs(job, workflow_jobs(caller)) for job in jobs):
            found = f"the job in {caller_name} that calls {name} has an `if` condition, or needs a job that has one"
        else:
            return ""
    return found
