"""Fail-closed verification of a GitHub pull request and its delivery proof."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast
from urllib.parse import urlparse

from gate_config import JsonValue
from ship_evidence import attachment_urls

Delivery = TypedDict("Delivery", {"name": str, "command": list[str]})

ShippingPolicy = TypedDict(
    "ShippingPolicy",
    {
        "base": str,
        "checks": list[str],
        "ui_paths": list[str],
        "ci_seconds": float,
        "pre_push_seconds": float,
        "delivery": list[Delivery],
    },
)


@dataclass(frozen=True)
class Shipment:
    root: Path
    plan: Path
    pr_url: str
    repository: str
    remote: str
    remote_url: str
    branch: str
    head_sha: str
    base: str
    merged_sha: str | None
    delivery_target: str


class ShippingError(ValueError):
    pass


class PendingCheck(ShippingError):
    """A required check has not concluded yet; it has not failed."""


_CONFIG_KEYS = {
    "base",
    "checks",
    "ui_paths",
    "ci_seconds",
    "pre_push_seconds",
    "delivery",
}
_DELIVERY_KEYS = {"name", "command"}
_BRANCH_PARTS = re.compile(r"^[A-Za-z0-9._/-]+$")
_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_PR_URL = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)/?$"
)
_GH_TIMEOUT = 30.0
_GIT_TIMEOUT = 30.0
_DELIVERY_TIMEOUT = 120.0


@dataclass(frozen=True)
class _PullRequest:
    state: str
    draft: bool
    head_ref: str
    head_sha: str
    head_repository: str
    base_ref: str
    base_repository: str
    body: str
    mergeable: bool | None
    mergeable_state: str | None
    merged: bool
    merged_at: str | None
    merge_commit_sha: str | None


def _run(
    root: Path,
    executable: str,
    args: tuple[str, ...],
    timeout: float,
    env: dict[str, str] | None = None,
) -> str:
    try:
        result = subprocess.run(
            [executable, *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ShippingError(f"{executable} query unavailable") from error
    if result.returncode != 0:
        reason = result.stderr.strip().rpartition("\n")[2]
        raise ShippingError(f"{executable} query failed: {reason}".removesuffix(": "))
    return result.stdout


def git(root: Path, *args: str) -> str:
    env = os.environ | {"PYTHONDONTWRITEBYTECODE": "1"}
    return _run(root, "git", args, _GIT_TIMEOUT, env=env)


def gh(root: Path, *args: str) -> str:
    return _run(root, "gh", args, _GH_TIMEOUT)


def _json(text: str, description: str) -> JsonValue:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError) as error:
        raise ShippingError(f"{description} returned invalid JSON") from error
    return cast(JsonValue, value)


def _object(value: JsonValue, description: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ShippingError(f"{description} must be an object")
    return value


def _text(mapping: dict[str, JsonValue], key: str, description: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ShippingError(f"{description} has no valid {key}")
    return value


def _optional_text(
    mapping: dict[str, JsonValue], key: str, description: str
) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ShippingError(f"{description} has invalid {key}")
    return value


def _sha(value: JsonValue, description: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ShippingError(f"{description} has invalid commit SHA")
    return value.lower()


def _repo(value: JsonValue, description: str) -> str:
    if not isinstance(value, str):
        raise ShippingError(f"{description} has no repository")
    owner, separator, name = value.partition("/")
    if (
        not separator
        or not owner
        or not name
        or "/" in name
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", owner)
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", name)
    ):
        raise ShippingError(f"{description} has an invalid repository")
    return f"{owner}/{name}".lower()


def _pr_url(pr_url: str) -> tuple[str, str, int]:
    match = _PR_URL.fullmatch(pr_url)
    if match is None:
        raise ShippingError("PR URL must be an https://github.com pull request URL")
    return match.group(1), match.group(2), int(match.group(3))


def _branch(value: str, description: str) -> str:
    if (
        not value
        or not _BRANCH_PARTS.fullmatch(value)
        or value.startswith("-")
        or ".." in value
        or "@{" in value
        or value.endswith(("/", ".", ".lock"))
    ):
        raise ShippingError(f"{description} is not a safe branch name")
    return value


def _number(value: JsonValue, description: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ShippingError(f"{description} must be a positive number")
    try:
        number = float(value)
    except OverflowError as error:
        raise ShippingError(f"{description} must be a positive number") from error
    if not math.isfinite(number) or number <= 0:
        raise ShippingError(f"{description} must be a positive number")
    return number


def _strings(value: JsonValue, description: str, required: bool = False) -> list[str]:
    if (
        not isinstance(value, list)
        or (required and not value)
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ShippingError(f"{description} must be strings")
    return cast(list[str], value)


def _check_names(value: JsonValue) -> list[str]:
    names = _strings(value, "shipping checks", required=True)
    if len(set(names)) != len(names):
        raise ShippingError("shipping checks must be unique")
    return names


def _delivery_entries(value: JsonValue) -> list[Delivery]:
    if not isinstance(value, list):
        raise ShippingError("shipping delivery must be a list")
    commands: list[Delivery] = []
    names: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != _DELIVERY_KEYS:
            raise ShippingError("shipping delivery entries need name and command")
        name = item["name"]
        command = item["command"]
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ShippingError("shipping delivery entries are malformed")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(arg, str) for arg in command)
        ):
            raise ShippingError("shipping delivery entries are malformed")
        args = cast(list[str], command)
        if not args[0].strip():
            raise ShippingError("shipping delivery entries are malformed")
        names.add(name)
        commands.append({"name": name, "command": args})
    return commands


def _policy(raw: dict[str, JsonValue]) -> ShippingPolicy:
    if set(raw) != _CONFIG_KEYS:
        raise ShippingError("shipping policy has unknown or missing keys")
    base = raw["base"]
    if not isinstance(base, str):
        raise ShippingError("shipping base must be a string")
    base = _branch(base, "shipping base")
    return {
        "base": base,
        "checks": _check_names(raw["checks"]),
        "ui_paths": _strings(raw["ui_paths"], "shipping ui_paths"),
        "ci_seconds": _number(raw["ci_seconds"], "shipping ci_seconds"),
        "pre_push_seconds": _number(
            raw["pre_push_seconds"], "shipping pre_push_seconds"
        ),
        "delivery": _delivery_entries(raw["delivery"]),
    }


def load_policy(root: Path, required: bool = True) -> ShippingPolicy | None:
    """Load and strictly validate the existing project's shipping policy."""

    path = root / "hard-eng.gates.json"
    if not path.is_file():
        if required:
            raise ShippingError("hard-eng.gates.json is required for shipping")
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ShippingError("hard-eng.gates.json is invalid") from error
    if not isinstance(payload, dict):
        raise ShippingError("hard-eng.gates.json must be an object")
    if "shipping" not in payload:
        if required:
            raise ShippingError("shipping policy is required")
        return None
    raw = payload["shipping"]
    if not isinstance(raw, dict):
        raise ShippingError("shipping policy must be an object")
    return _policy(cast(dict[str, JsonValue], raw))


def _pull(root: Path, owner: str, name: str, number: int) -> _PullRequest:
    endpoint = f"repos/{owner}/{name}/pulls/{number}"
    value = _json(gh(root, "api", endpoint), "PR query")
    data = _object(value, "PR response")
    head = _object(data.get("head"), "PR head")
    base = _object(data.get("base"), "PR base")
    mergeable = data.get("mergeable")
    if mergeable is not None and not isinstance(mergeable, bool):
        raise ShippingError("PR mergeability is invalid")
    draft = data.get("draft")
    if not isinstance(draft, bool):
        raise ShippingError("PR draft state is invalid")
    merged = data.get("merged")
    if not isinstance(merged, bool):
        raise ShippingError("PR merged state is invalid")
    body = data.get("body")
    if body is None:
        body = ""
    if not isinstance(body, str):
        raise ShippingError("PR body is invalid")
    return _PullRequest(
        state=_text(data, "state", "PR"),
        draft=draft,
        head_ref=_branch(_text(head, "ref", "PR head"), "PR head"),
        head_sha=_sha(head.get("sha"), "PR head"),
        head_repository=_repo(
            _object(head.get("repo"), "PR head repository").get("full_name"),
            "PR head repository",
        ),
        base_ref=_branch(_text(base, "ref", "PR base"), "PR base"),
        base_repository=_repo(
            _object(base.get("repo"), "PR base repository").get("full_name"),
            "PR base repository",
        ),
        body=body,
        mergeable=mergeable,
        mergeable_state=_optional_text(data, "mergeable_state", "PR"),
        merged=merged,
        merged_at=_optional_text(data, "merged_at", "PR"),
        merge_commit_sha=(
            None
            if data.get("merge_commit_sha") is None
            else _sha(data.get("merge_commit_sha"), "PR merge")
        ),
    )


def _page_sequence(value: JsonValue, key: str, description: str) -> list[JsonValue]:
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        raise ShippingError(f"{description} pagination is invalid")
    if not value:
        return []
    if all(isinstance(item, list) for item in value):
        return value
    if all(isinstance(item, dict) and key in item for item in value):
        return value
    if all(isinstance(item, dict) for item in value):
        return [value]
    raise ShippingError(f"{description} pagination is invalid")


def _pages(value: JsonValue, key: str, description: str) -> list[JsonValue]:
    pages = _page_sequence(value, key, description)
    output: list[JsonValue] = []
    totals: list[int] = []
    for page in pages:
        if isinstance(page, list):
            items: JsonValue = page
        else:
            if not isinstance(page, dict):
                raise ShippingError(f"{description} pagination is invalid")
            if page.get("truncated") is True or page.get("incomplete_results") is True:
                raise ShippingError(f"{description} response is truncated")
            items = page.get(key)
            total = page.get("total_count")
            if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
                totals.append(total)
        if not isinstance(items, list):
            raise ShippingError(f"{description} response has no {key}")
        output.extend(items)
    if totals and len(output) < max(totals):
        raise ShippingError(f"{description} pagination is incomplete")
    return output


def _api_items(
    root: Path, endpoint: str, key: str, description: str
) -> list[dict[str, JsonValue]]:
    value = _json(gh(root, "api", "--paginate", "--slurp", endpoint), description)
    items = _pages(value, key, description)
    if any(not isinstance(item, dict) for item in items):
        raise ShippingError(f"{description} contains an invalid item")
    return cast(list[dict[str, JsonValue]], items)


def _timestamp(value: JsonValue, description: str) -> float:
    if not isinstance(value, str) or not value.strip():
        raise ShippingError(f"{description} has no timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ShippingError(f"{description} has an invalid timestamp") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _run_sort_key(run: dict[str, JsonValue]) -> int:
    run_id = run.get("id")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        raise ShippingError("required check has no valid run identity")
    return run_id


def _check_revision(run: dict[str, JsonValue], revision: str) -> None:
    value = run.get("head_sha")
    if not isinstance(value, str) or value.lower() != revision:
        raise ShippingError("required check is stale")


def _checks(root: Path, repository: str, revision: str, policy: ShippingPolicy) -> None:
    endpoint = (
        f"repos/{repository}/commits/{revision}/check-runs?per_page=100&filter=all"
    )
    items = _api_items(root, endpoint, "check_runs", "check-runs query")
    by_name: dict[str, list[dict[str, JsonValue]]] = {
        name: [] for name in policy["checks"]
    }
    for item in items:
        name = item.get("name")
        if isinstance(name, str) and name in by_name:
            by_name[name].append(item)
    for name, candidates in by_name.items():
        if not candidates:
            raise PendingCheck(f"required check missing: {name}")
        run = max(candidates, key=_run_sort_key)
        if run.get("truncated") is True or (
            isinstance(run.get("output"), dict)
            and run["output"].get("truncated") is True
        ):
            raise ShippingError(f"required check truncated: {name}")
        _check_revision(run, revision)
        if run.get("status") != "completed":
            raise PendingCheck(f"required check has not completed: {name}")
        if run.get("conclusion") == "skipped":
            raise ShippingError(
                f"required check was skipped; gate its steps, not the job: {name}"
            )
        if run.get("conclusion") != "success":
            raise ShippingError(f"required check is not successful: {name}")
        started = _timestamp(run.get("started_at"), f"check {name}")
        completed = _timestamp(run.get("completed_at"), f"check {name}")
        duration = completed - started
        if duration < 0 or duration > policy["ci_seconds"]:
            raise ShippingError(f"required check is outside the CI budget: {name}")


def _changed_paths(root: Path, owner: str, name: str, number: int) -> list[str]:
    endpoint = f"repos/{owner}/{name}/pulls/{number}/files?per_page=100"
    items = _api_items(root, endpoint, "files", "PR files query")
    paths: list[str] = []
    for item in items:
        filename = item.get("filename")
        if not isinstance(filename, str) or not filename.strip():
            raise ShippingError("PR files query has an invalid filename")
        paths.append(filename)
        previous = item.get("previous_filename")
        if previous is not None:
            if not isinstance(previous, str) or not previous.strip():
                raise ShippingError("PR files query has an invalid previous filename")
            paths.append(previous)
    return sorted(set(paths))


def _check_attachment(root: Path, url: str) -> None:
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
    response = gh(root, *request, "-H", "Range: bytes=0-0", url)
    statuses = re.findall(r"(?im)^HTTP/\S+\s+(\d{3})\b", response)
    if not statuses or not 200 <= int(statuses[-1]) < 300:
        raise ShippingError("UI evidence attachment is unavailable")
    content_types = re.findall(r"(?im)^content-type:\s*([^\r\n]+)", response)
    content_type = content_types[-1].lower() if content_types else ""
    if not content_type.startswith(("image/", "video/")):
        raise ShippingError("UI evidence attachment is not image or video")
    lengths = re.findall(r"(?im)^content-length:\s*([^\r\n]+)", response)
    if lengths:
        try:
            if int(lengths[-1]) <= 0:
                raise ValueError
        except ValueError as error:
            raise ShippingError("UI evidence attachment has invalid length") from error


def _ui_evidence(
    root: Path, pull: _PullRequest, paths: list[str], policy: ShippingPolicy
) -> None:
    try:
        urls = attachment_urls(pull.body, paths, policy["ui_paths"])
    except ValueError as error:
        raise ShippingError(str(error)) from error
    for url in urls:
        _check_attachment(root, url)


def _root_and_branch(root: Path, require_branch: bool) -> tuple[Path, str, str]:
    resolved = root.resolve()
    actual = Path(git(root, "rev-parse", "--show-toplevel").strip()).resolve()
    if actual != resolved:
        raise ShippingError("shipping root is not the repository checkout")
    try:
        branch = git(root, "symbolic-ref", "--quiet", "--short", "HEAD").strip()
    except ShippingError:
        if require_branch:
            raise
        branch = ""
    if require_branch and not branch:
        raise ShippingError("shipping requires a named task branch")
    head = _sha(git(root, "rev-parse", "HEAD").strip(), "local checkout")
    return resolved, branch, head


def origin_repository(remote_url: str) -> str:
    value = remote_url
    if value.startswith("git@github.com:"):
        location = value.removeprefix("git@github.com:")
    else:
        parsed = urlparse(value)
        if parsed.scheme not in {"https", "ssh"} or parsed.hostname != "github.com":
            raise ShippingError("origin must be a GitHub remote")
        location = parsed.path.lstrip("/")
    location = location.removesuffix(".git").strip("/")
    return _repo(location, "origin")


def _clean(root: Path) -> None:
    if git(root, "status", "--porcelain", "-uall", "--ignore-submodules=none").strip():
        raise ShippingError("shipping requires a clean task checkout")


def _plan_target(root: Path, plan: Path) -> tuple[Path, str]:
    resolved_root = root.resolve()
    resolved_plan = plan.resolve()
    if not resolved_plan.is_relative_to(resolved_root):
        raise ShippingError("shipping plan must be inside the repository")
    if not resolved_plan.is_file():
        raise ShippingError(
            "shipping plan not found in this checkout; check out the PR's head branch"
        )
    try:
        from plans import plan_sections, validate_plan

        if validate_plan(resolved_plan) != "Complete":
            raise ShippingError("shipping requires a Complete plan")
        sections = plan_sections(resolved_plan.read_text())
    except ShippingError:
        raise
    except (OSError, UnicodeError, ValueError) as error:
        raise ShippingError(
            "shipping plan failed native Complete validation"
        ) from error
    targets = re.findall(
        r"(?im)^\s*(?:[-*+]\s+)?Delivery target:\s*(PR|Merge|Deploy)\s*$",
        sections["Verification"],
    )
    if len(targets) != 1:
        raise ShippingError(
            "Verification needs one Delivery target: PR, Merge or Deploy"
        )
    return resolved_plan, targets[0]


def _remote_sha(root: Path, base: str, remote_url: str) -> str:
    ref = f"refs/heads/{base}"
    output = git(root, "ls-remote", "--heads", remote_url, ref).strip()
    rows = [line.split() for line in output.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) < 2 or rows[0][1] != ref:
        raise ShippingError("current remote base is unavailable")
    return _sha(rows[0][0], "current remote base")


def _remote_base(root: Path, base: str, remote_url: str) -> str:
    expected = _remote_sha(root, base, remote_url)
    ref = f"refs/heads/{base}:refs/remotes/origin/{base}"
    git(root, "fetch", "--no-tags", remote_url, ref)
    current = _remote_sha(root, base, remote_url)
    if current != expected:
        raise ShippingError("remote base changed during verification")
    return current


def _delivered(root: Path, pull: _PullRequest, base: str, remote_url: str) -> str:
    if pull.state != "closed" or not pull.merged or pull.merged_at is None:
        raise ShippingError("PR is not confirmed merged")
    if pull.merge_commit_sha is None:
        raise ShippingError("merged PR has no merge commit")
    remote_base = _remote_base(root, base, remote_url)
    try:
        git(root, "merge-base", "--is-ancestor", pull.merge_commit_sha, remote_base)
    except ShippingError as error:
        raise ShippingError(
            "merge commit is not reachable from current remote base"
        ) from error
    return pull.merge_commit_sha


def _ready_state(
    root: Path,
    pull: _PullRequest,
    policy: ShippingPolicy,
    branch: str,
    local_head: str,
) -> tuple[str, None]:
    if pull.state != "open" or pull.draft:
        raise ShippingError("PR must be open and ready for review")
    if branch != pull.head_ref or local_head != pull.head_sha:
        raise ShippingError("local task branch or HEAD does not match PR")
    if branch == policy["base"]:
        raise ShippingError("shipping requires a task branch distinct from base")
    if pull.mergeable is not True or pull.mergeable_state != "clean":
        raise ShippingError("PR mergeability is not clean")
    _clean(root)
    return pull.head_sha, None


def _delivery(root: Path, policy: ShippingPolicy, revision: str, pr_url: str) -> None:
    for item in policy["delivery"]:
        env = os.environ.copy()
        env.update({"HE_SHIP_REVISION": revision, "HE_SHIP_PR_URL": pr_url})
        command = item["command"]
        try:
            stdout = _run(root, command[0], tuple(command[1:]), _DELIVERY_TIMEOUT, env)
        except ShippingError as error:
            raise ShippingError(f"delivery check failed: {item['name']}") from error
        value = _json(stdout, f"delivery check {item['name']}")
        data = _object(value, f"delivery check {item['name']}")
        if data.get("status") != "passed" or data.get("revision") != revision:
            raise ShippingError(
                f"delivery check did not prove revision: {item['name']}"
            )


def verify(root: Path, plan: Path, pr_url: str, stage: str) -> Shipment:
    if stage not in {"ready", "delivered"}:
        raise ShippingError("shipping stage must be ready or delivered")
    policy = cast(ShippingPolicy, load_policy(root, required=True))
    owner, name, number = _pr_url(pr_url)
    resolved_root, branch, local_head = _root_and_branch(root, stage == "ready")
    origin_url = git(root, "remote", "get-url", "origin").strip()
    repository = origin_repository(origin_url)
    url = f"https://github.com/{owner}/{name}/pull/{number}"
    if repository != f"{owner}/{name}".lower():
        raise ShippingError("PR URL repository does not match origin")
    resolved_plan, target = _plan_target(resolved_root, plan)
    if target == "Deploy" and not policy["delivery"]:
        raise ShippingError("Deploy target requires configured delivery checks")
    pull = _pull(resolved_root, owner, name, number)
    if pull.base_ref != policy["base"]:
        raise ShippingError("PR base branch does not match shipping policy")
    if pull.base_repository != repository or pull.head_repository != repository:
        raise ShippingError("PR repository or head repository does not match origin")
    if stage == "ready":
        revision, merged_sha = _ready_state(
            resolved_root, pull, policy, branch, local_head
        )
    else:
        _clean(resolved_root)
        revision = _delivered(resolved_root, pull, policy["base"], origin_url)
        merged_sha = revision
    if policy["ui_paths"]:
        paths = _changed_paths(resolved_root, owner, name, number)
        _ui_evidence(resolved_root, pull, paths, policy)
    _checks(resolved_root, repository, revision, policy)
    if stage == "delivered" and target == "Deploy":
        _delivery(resolved_root, policy, revision, url)
    current = _pull(resolved_root, owner, name, number)
    if current != pull:
        raise ShippingError("PR changed during shipping verification")
    return Shipment(
        root=resolved_root,
        plan=resolved_plan,
        pr_url=url,
        repository=f"{owner}/{name}",
        remote="origin",
        remote_url=origin_url,
        branch=pull.head_ref,
        head_sha=pull.head_sha,
        base=policy["base"],
        merged_sha=merged_sha,
        delivery_target=target,
    )
