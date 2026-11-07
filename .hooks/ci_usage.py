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
    multiplier = next(
        (value for name, value in RUNNER_MULTIPLIERS.items() if name in names), 1
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
    totals = {"billed": 0, "cancelled": 0, "failure": 0, "unstarted": 0, "running": 0}
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
