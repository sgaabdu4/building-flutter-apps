"""Billed GitHub Actions minutes and where each job's time goes."""

import math
import re
from pathlib import Path
from statistics import median

from gate_config import JsonValue

RUNNER_MULTIPLIERS = {"windows": 2, "macos": 10}
SETUP_STEP = re.compile(
    r"(?i)^(?:set up job|complete job|post )|checkout|set ?up|install|cache|restore|download"
)


def billed_job(job: dict[str, JsonValue]) -> tuple[int, float, int] | None:
    """Billed whole minutes, actual minutes and runner multiplier; None when never started."""
    from shipping import _timestamp

    if not job.get("runner_name") or not job.get("steps"):
        return None
    minutes = (
        _timestamp(job.get("completed_at"), "job")
        - _timestamp(job.get("started_at"), "job")
    ) / 60
    labels = job.get("labels")
    names = " ".join(map(str, labels if isinstance(labels, list) else [])).lower()
    multiplier = (
        0
        if "self-hosted" in names
        else next(
            (value for name, value in RUNNER_MULTIPLIERS.items() if name in names), 1
        )
    )
    return math.ceil(minutes) * multiplier, minutes, multiplier


def phases(job: dict[str, JsonValue]) -> tuple[float, float, float] | None:
    """Seconds waiting for a runner, setting up and running; None without timings."""
    from shipping import ShippingError, _timestamp

    try:
        created, started, completed = (
            _timestamp(job.get(key), "job")
            for key in ("created_at", "started_at", "completed_at")
        )
    except ShippingError:
        return None
    steps = job.get("steps")
    work = 0.0
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, dict) or SETUP_STEP.search(str(step.get("name"))):
            continue
        try:
            work += _timestamp(step.get("completed_at"), "step") - _timestamp(
                step.get("started_at"), "step"
            )
        except ShippingError:
            continue
    total = completed - started
    work = min(work, total)
    return max(started - created, 0.0), total - work, work


def queue_note(
    root: Path, repository: str, run: dict[str, JsonValue], budget: float
) -> str:
    """Text to add to a queued check's message when no runner took it past the budget."""
    from datetime import UTC, datetime

    from shipping import ShippingError, _json, _object, _timestamp, gh

    try:
        job = _object(
            _json(
                gh(root, "api", f"repos/{repository}/actions/jobs/{run.get('id')}"),
                "job",
            ),
            "job",
        )
        waited = datetime.now(UTC).timestamp() - _timestamp(
            job.get("created_at"), "job"
        )
    except ShippingError:
        return ""
    labels = job.get("labels")
    names = ", ".join(map(str, labels)) if isinstance(labels, list) else ""
    if job.get("status") != "queued" or "self-hosted" not in names:
        return ""
    if job.get("runner_name") or waited <= budget:
        return ""
    return (
        f"; no runner has taken it for {int(waited // 60)} min (labels: {names}). "
        "Start a runner with those labels, or ask its owner whether it serves this "
        "PR's author. GitHub fails a job queued over 24 hours."
    )


def recent_runs(
    root: Path, repository: str, days: int, limit: int | None
) -> list[dict[str, JsonValue]]:
    """Runs from the last days, or the newest limit runs when a limit is set."""
    from datetime import UTC, datetime, timedelta

    from shipping import ShippingError, _api_items, _json, gh

    if limit is None:
        since = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
        return _api_items(
            root,
            f"repos/{repository}/actions/runs?per_page=100&created=>={since}",
            "workflow_runs",
            "workflow runs",
        )
    runs: list[dict[str, JsonValue]] = []
    page = 1
    while len(runs) < limit:
        endpoint = f"repos/{repository}/actions/runs?per_page=100&page={page}"
        value = _json(gh(root, "api", endpoint), "workflow runs")
        page_runs = value.get("workflow_runs") if isinstance(value, dict) else None
        if not isinstance(page_runs, list):
            raise ShippingError("workflow runs page has no run list")
        items = [item for item in page_runs if isinstance(item, dict)]
        runs += items
        if len(items) < 100:
            break
        page += 1
    return runs[:limit]


def workflow_jobs(
    root: Path, repository: str, days: int, limit: int | None = None
) -> tuple[int, list[tuple[str, str, dict[str, JsonValue]]]]:
    from concurrent.futures import ThreadPoolExecutor

    from shipping import _api_items

    runs = recent_runs(root, repository, days, limit)

    def jobs(run: dict[str, JsonValue]) -> list[tuple[str, str, dict[str, JsonValue]]]:
        endpoint = f"repos/{repository}/actions/runs/{run.get('id')}/jobs?per_page=100&filter=all"
        event = str(run.get("event"))
        name = run.get("path") if event == "dynamic" else run.get("name")
        return [
            (str(name), event, job)
            for job in _api_items(root, endpoint, "jobs", "workflow jobs")
        ]

    with ThreadPoolExecutor(max_workers=8) as pool:
        return len(runs), [row for rows in pool.map(jobs, runs) for row in rows]


def print_phases(rows: list[tuple[str, str, dict[str, JsonValue]]]) -> None:
    timings: dict[tuple[str, str], list[tuple[float, float, float]]] = {}
    for workflow, _, job in rows:
        completed = job.get("status") == "completed" and billed_job(job)
        if completed and (split := phases(job)) is not None:
            timings.setdefault((workflow, str(job.get("name"))), []).append(split)
    slowest = sorted(
        timings.items(), key=lambda item: -median(sum(split) for split in item[1])
    )[:5]
    print("Slowest jobs, median s:  queue  setup    run  total  runs  workflow / job")
    for (workflow, name), splits in slowest:
        queue, setup, work = (median(values) for values in zip(*splits, strict=True))
        print(
            f"{'':24}{queue:6.0f} {setup:6.0f} {work:6.0f} {queue + setup + work:6.0f}"
            f"  {len(splits):4}  {workflow} / {name}"
        )


def ci_usage(
    root: Path, repository: str | None, days: int, limit: int | None = None
) -> int:
    """Print billed Actions minutes by workflow, event and job, the slowest jobs' queue,
    setup and run time, and jobs run on both push and PR."""
    from shipping import git, origin_repository

    repository = repository or origin_repository(
        git(root, "remote", "get-url", "origin").strip()
    )
    count, rows = workflow_jobs(root, repository, days, limit)
    billed: dict[tuple[str, str, str], list[tuple[int, float, int]]] = {}
    totals = {
        "billed": 0,
        "cancelled": 0,
        "failure": 0,
        "unstarted": 0,
        "running": 0,
        "own": 0,
    }
    actual = 0.0
    for workflow, event, job in rows:
        if job.get("status") != "completed":
            totals["running"] += 1
            continue
        usage = billed_job(job)
        if usage is None:
            totals["unstarted"] += 1
            continue
        billed.setdefault((workflow, event, str(job.get("name"))), []).append(usage)
        totals["own"] += usage[2] == 0
        totals["billed"] += usage[0]
        actual += usage[1] * usage[2]
        if job.get("conclusion") in {"cancelled", "failure"}:
            totals[str(job.get("conclusion"))] += usage[0]
    window = f"last {limit} runs" if limit else f"last {days} days"
    print(
        f"{repository}, {window}: {count} runs, {len(rows)} jobs. "
        f"Billed {totals['billed']} min ({totals['billed'] - actual:.0f} rounding up to whole minutes); "
        f"cancelled {totals['cancelled']}, failed {totals['failure']}; "
        f"{totals['unstarted']} jobs never got a runner and are not billed; "
        f"{totals['own']} self-hosted jobs are not billed; "
        f"{totals['running']} jobs still running are not counted. "
        "Standard runners on public repositories are free."
    )
    print("billed  runs  median s  p90 s  workflow / event / job")
    for (workflow, event, name), usages in sorted(
        billed.items(), key=lambda item: -sum(usage[0] for usage in item[1])
    )[:25]:
        seconds = sorted(usage[1] * 60 for usage in usages)
        print(
            f"{sum(usage[0] for usage in usages):6}  {len(usages):4}  "
            f"{seconds[len(seconds) // 2]:8.0f}  {seconds[int(0.9 * (len(seconds) - 1))]:5.0f}  "
            f"{workflow} / {event} / {name}"
        )
    print_phases(rows)
    repeated = {
        (workflow, name)
        for workflow, event, name in billed
        if event == "push" and (workflow, "pull_request", name) in billed
    }
    for workflow, name in sorted(repeated):
        minutes = [
            sum(usage[0] for usage in billed[workflow, event, name])
            for event in ("push", "pull_request")
        ]
        print(
            f"Runs on push and pull_request: {workflow} / {name} "
            f"(push {minutes[0]} min, pull_request {minutes[1]} min)"
        )
    return 0


def _compared_tree(comparison: dict[str, JsonValue], side: str) -> str | None:
    """The tree of one commit of a compare reply. A merge commit on the branch is not in the PR head, but its files are when the merge base has the same tree."""
    value: JsonValue = comparison.get(side)
    for key in ("commit", "tree", "sha"):
        value = value.get(key) if isinstance(value, dict) else None
    return value if isinstance(value, str) else None


def _pull_request_head(
    root: Path, repository: str, base: str, branch: str
) -> tuple[str, str]:
    """The head and tree of the one PR merged into this push, whatever the merge method."""
    from shipping import ShippingError, _json, _object, _sha, _text, gh, git

    revision = git(root, "rev-parse", "HEAD").strip()
    endpoint = f"repos/{repository}/commits/{revision}/pulls"
    value = _json(gh(root, "api", endpoint), "commit PRs")
    if not isinstance(value, list):
        raise ShippingError("commit PRs response is invalid")
    heads = set()
    for item in value:
        pull = _object(item, "PR")
        if (
            pull.get("merged_at")
            and _object(pull.get("base"), "PR base").get("ref") == branch
        ):
            heads.add(_sha(_object(pull.get("head"), "PR head").get("sha"), "PR head"))
    if len(heads) != 1:
        raise ShippingError("push merges no single PR")
    head = heads.pop()
    endpoint = f"repos/{repository}/compare/{base}...{head}"
    comparison = _object(_json(gh(root, "api", endpoint), "compare"), "compare")
    if comparison.get("status") not in {"ahead", "identical"}:
        tree = _compared_tree(comparison, "base_commit")
        if tree is None or tree != _compared_tree(comparison, "merge_base_commit"):
            raise ShippingError("PR head does not contain the previous base")
    endpoint = f"repos/{repository}/git/commits/{head}"
    commit = _object(_json(gh(root, "api", endpoint), "PR commit"), "PR commit")
    return head, _text(_object(commit.get("tree"), "PR tree"), "sha", "PR tree")


def _release_revision(base_branch: str) -> str | None:
    """The head commit of a PR from the base branch into another branch of this repository."""
    import os

    from shipping import ShippingError, _json, _object, _repo, _sha, _text

    try:
        text = Path(os.environ.get("GITHUB_EVENT_PATH", "")).read_text()
    except OSError as error:
        raise ShippingError("the event file is unreadable") from error
    pull = _object(_object(_json(text, "event"), "event").get("pull_request"), "PR")
    head = _object(pull.get("head"), "PR head")
    base = _object(pull.get("base"), "PR base")
    if (
        _text(head, "ref", "PR head") != base_branch
        or _text(base, "ref", "PR base") == base_branch
    ):
        return None
    repositories = {
        _repo(_object(side.get("repo"), "PR repository").get("full_name"), "PR")
        for side in (head, base)
    }
    return _sha(head.get("sha"), "PR head") if len(repositories) == 1 else None


def reused_pull_request(root: Path, base: str) -> str | None:
    """The commit whose passed required checks already cover this branch push or release PR."""
    import os

    from shipping import ShippingError, _checks, _repo, _sha, git, load_policy

    try:
        policy = load_policy(root, required=False)
        event = os.environ.get("GITHUB_EVENT_NAME")
        ref = os.environ.get("GITHUB_REF", "")
        on_push = event == "push" and ref.startswith("refs/heads/")
        if (
            policy is None
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or not (on_push or event == "pull_request")
        ):
            return None
        release = "" if on_push else _release_revision(policy["base"]) or ""
        if not (on_push or release):
            return None
    except ShippingError:
        return None
    try:
        if git(root, "status", "--porcelain"):
            raise ShippingError("the checkout has uncommitted changes")
        repository = _repo(os.environ.get("GITHUB_REPOSITORY"), "workflow")
        if on_push:
            head, tree = _pull_request_head(
                root,
                repository,
                _sha(base, "push base"),
                ref.removeprefix("refs/heads/"),
            )
        else:
            head = release
            tree = git(root, "rev-parse", f"{head}^{{tree}}").strip()
        if tree != git(root, "rev-parse", "HEAD^{tree}").strip():
            raise ShippingError("the covering PR tested a different tree")
        _checks(root, repository, head, policy, False, completed_only=not on_push)
    except ShippingError as error:
        who = "merged PR's" if on_push else "earlier"
        where = "push" if on_push else "PR"
        print(
            f"Running the checks again; the {who} checks do not cover this {where}: {error}",
            flush=True,
        )
        return None
    return head
