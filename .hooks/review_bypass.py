"""Admin merge past a required review that nobody but the PR's author could give."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from urllib.parse import quote

import shipping
from gate_config import JsonValue
from shipping import (
    _PR_URL,
    _THREADS_QUERY,
    ShippingError,
    _api_items,
    _complete_nodes,
    _graphql_pull,
    _json,
    _object,
    _text,
)

_REVIEW_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!){viewer{login} "
    "repository(owner:$owner,name:$name){pullRequest(number:$number){"
    "viewerDidAuthor viewerCanMergeAsAdmin reviewDecision isMergeQueueEnabled baseRefName "
    "baseRef{branchProtectionRule{"
    "requiresCommitSignatures requiresDeployments lockBranch requiresStrictStatusChecks "
    "requiredStatusCheckContexts} rules(first:100){totalCount nodes{type parameters{"
    "...on RequiredStatusChecksParameters{strictRequiredStatusChecksPolicy "
    "requiredStatusChecks{context}} "
    "...on PullRequestParameters{requireCodeOwnerReview}}}}} "
    "commits(last:1){nodes{commit{oid statusCheckRollup{state contexts(first:100){"
    "totalCount nodes{...on CheckRun{name conclusion} ...on StatusContext{context state}}"
    "}}}}}}}}"
)
_PASSED = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_CODEOWNERS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
_BYPASSABLE_RULES = {
    "PULL_REQUEST",
    "REQUIRED_STATUS_CHECKS",
    "REQUIRED_LINEAR_HISTORY",
    "NON_FAST_FORWARD",
    "DELETION",
    "CREATION",
}


def _required_checks(
    protection: dict[str, JsonValue], rules: list[dict[str, JsonValue]]
) -> set[str]:
    contexts = protection.get("requiredStatusCheckContexts")
    names: list[JsonValue] = list(contexts) if isinstance(contexts, list) else []
    for rule in rules:
        parameters = rule.get("parameters")
        checks = (
            parameters.get("requiredStatusChecks")
            if isinstance(parameters, dict)
            else None
        )
        if isinstance(checks, list):
            names += [
                check.get("context") for check in checks if isinstance(check, dict)
            ]
    return {name for name in names if isinstance(name, str)}


def _other_merge_requirement(
    pull: dict[str, JsonValue], rollup: dict[str, JsonValue]
) -> str | None:
    """Why something besides the review may block; admin merge would bypass it too."""
    if pull.get("isMergeQueueEnabled") is not False:
        return "the base branch may require a merge queue"
    base = pull.get("baseRef")
    rules = _complete_nodes(base.get("rules") if isinstance(base, dict) else None)
    if not isinstance(base, dict) or rules is None:
        return "the base branch rules are unreadable"
    protection = base.get("branchProtectionRule") or {}
    if not isinstance(protection, dict) or any(
        value is not False
        for key, value in protection.items()
        if key != "requiredStatusCheckContexts"
    ):
        return "branch protection has another merge requirement"
    other = {str(node.get("type")) for node in rules} - _BYPASSABLE_RULES
    if other:
        return "a ruleset has another merge requirement: " + ", ".join(sorted(other))
    if any(
        rule.get("type") == "REQUIRED_STATUS_CHECKS"
        and not (
            isinstance(rule.get("parameters"), dict)
            and cast(dict[str, JsonValue], rule["parameters"]).get(
                "strictRequiredStatusChecksPolicy"
            )
            is False
        )
        for rule in rules
    ):
        return "a ruleset needs the branch up to date, which admin merge would skip"
    contexts = _complete_nodes(rollup.get("contexts"))
    passed = {
        str(node.get("name") or node.get("context"))
        for node in contexts or []
        if node.get("conclusion") in _PASSED or node.get("state") == "SUCCESS"
    }
    missing = _required_checks(protection, rules) - passed
    if contexts is None or missing:
        return "a required check has not passed: " + ", ".join(sorted(missing))
    return None


def bypass_problem(
    root: Path, owner: str, name: str, number: int, head_sha: str
) -> str | None:
    """Why a blocked PR is not blocked solely by a review only its author could give."""
    data, pull = _graphql_pull(root, owner, name, number, _REVIEW_QUERY)
    viewer = _text(_object(data.get("viewer"), "viewer"), "login", "viewer")
    nodes = _object(pull.get("commits"), "review commits").get("nodes")
    commit = (
        _object(_object(nodes[0], "review commit").get("commit"), "review commit")
        if isinstance(nodes, list) and len(nodes) == 1
        else {}
    )
    rollup = commit.get("statusCheckRollup")
    if pull.get("viewerDidAuthor") is not True:
        return "the viewer did not author the PR"
    if pull.get("viewerCanMergeAsAdmin") is not True:
        return "the author cannot bypass the review requirement"
    if pull.get("reviewDecision") != "REVIEW_REQUIRED":
        return "the block is not an outstanding required review"
    if commit.get("oid") != head_sha or not (
        isinstance(rollup, dict) and rollup.get("state") == "SUCCESS"
    ):
        return "not every head check succeeded"
    if problem := _other_merge_requirement(pull, rollup):
        return problem
    collaborators = _api_items(
        root,
        f"repos/{owner}/{name}/collaborators?per_page=100",
        "collaborators",
        "collaborators query",
    )
    pushers = {
        item.get("login")
        for item in collaborators
        if isinstance(item.get("permissions"), dict)
        and cast(dict[str, JsonValue], item["permissions"]).get("push") is True
    }
    if pushers != {viewer} and not _sole_code_owner(root, owner, name, pull, viewer):
        return "another collaborator can give the review"
    return None


def _sole_code_owner(
    root: Path, owner: str, name: str, pull: dict[str, JsonValue], viewer: str
) -> bool:
    """A required code-owner review where CODEOWNERS gives every file to the author alone."""
    base = pull.get("baseRef")
    rules = _complete_nodes(base.get("rules") if isinstance(base, dict) else None)
    if not any(
        rule.get("type") == "PULL_REQUEST"
        and isinstance(rule.get("parameters"), dict)
        and cast(dict[str, JsonValue], rule["parameters"]).get("requireCodeOwnerReview")
        is True
        for rule in rules or []
    ):
        return False
    branch = quote(_text(pull, "baseRefName", "review PR"), safe="")
    for path in _CODEOWNERS:
        try:
            text = shipping.gh(
                root,
                "api",
                "-H",
                "Accept: application/vnd.github.raw+json",
                f"repos/{owner}/{name}/contents/{path}?ref={branch}",
            )
        except ShippingError:
            continue
        entries = [
            line.split("#", 1)[0].split()
            for line in text.splitlines()
            if line.split("#", 1)[0].strip()
        ]
        return any(entry[0] == "*" for entry in entries) and all(
            [who.lower() for who in entry[1:]] == [f"@{viewer.lower()}"]
            for entry in entries
        )
    return False


def author_only_review_block(root: Path, url: str, head_sha: str) -> str | None:
    """None when the open PR waits only on a review nobody but its author could give."""
    match = _PR_URL.fullmatch(url)
    if match is None:
        return "the PR address is not a GitHub pull request"
    owner, name, number = match[1], match[2], int(match[3])
    pull = _object(
        _json(shipping.gh(root, "api", f"repos/{owner}/{name}/pulls/{number}"), "PR"),
        "PR",
    )
    if pull.get("mergeable") is not True or pull.get("mergeable_state") != "blocked":
        return "the PR is not blocked by a review"
    threads = _complete_nodes(
        _graphql_pull(root, owner, name, number, _THREADS_QUERY)[1].get("reviewThreads")
    )
    if threads is None or any(node.get("isResolved") is not True for node in threads):
        return "a review conversation is unresolved or uncounted"
    return bypass_problem(root, owner, name, number, head_sha)
