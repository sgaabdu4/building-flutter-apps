"""HE-SOURCE-COVERAGE: the form of a plan's Sources + coverage section; it proves no truth."""

from collections.abc import Callable

import plans

SECTION = "Sources + coverage"
STATUSES = ("In scope", "Later", "Proposal", "Open")
DECIDERS = ("user", "client")
FORMS = (
    "`- <item>: In scope — <exact words from the Acceptance + steps line that "
    "names and proves it>`, `- <item>: Later — user|client, <place of the "
    "decision>`, `- <item>: Proposal — <your own rule, limit or exclusion>; yes — "
    "user|client, <place of the answer>` or `- <item>: Open — <question for the "
    "client or the user>`"
)
ROWS = (
    "one row for each person or role, team, screen, rule and requested outcome "
    f"that the sources name: {FORMS}"
)
ASK = "The plan is not Ready before the answer"
PAUSE = "in Blockers of a Draft plan with `Handoff: Clarification`"
NO_READER = ("pending", "n/a", "none")
LINES = {
    "Sources": (
        "each source the user gave, separated by `;`, each with the words `read "
        "in full`, or `N/A — reason` when the request is the only source"
    ),
    "Reviewer": (
        "what a second reader found after it read only the sources and the plan, "
        "or `N/A — reason` for one small source"
    ),
    "Deliverables": (
        "each thing that you make for the client outside the repository, or `None`"
    ),
}


def decided(text: str) -> bool:
    who, _, place = text.partition(",")
    name, _, note = who.strip().lower().partition(" ")
    named = not note or (note.startswith("(") and note.endswith(")"))
    return name in DECIDERS and named and bool(place.strip())


def asked(blockers: str, text: str) -> bool:
    words = text.lower().strip("`?. ")
    return bool(words) and words in blockers


def row_error(row: str, acceptance: list[str], blockers: str) -> str | None:
    marks = [(row.find(f": {status} — "), status) for status in STATUSES]
    at, status = min((mark for mark in marks if mark[0] > 0), default=(0, ""))
    rest = row[at + len(status) + 5 :].strip()
    name = f"row '{row[:60]}'"
    if not status:
        return f"{name} has no status; give this row one of these forms: {FORMS}"
    if status == "In scope":
        words = rest.strip("`")
        if not words or not any(words in line for line in acceptance):
            return (
                f"{name} points to no acceptance line; after `In scope — ` copy "
                "exact words from the Acceptance + steps line that names this item "
                "and proves it"
            )
    elif status == "Later" and not decided(rest):
        return (
            f"{name} names no decider; after `Later — ` write `client`, or `user` "
            "when the work is for the user, then a comma and the place of the "
            "decision. A name can follow the word in brackets: `client (head "
            "teacher), call minute 18`. Your own exclusion is a "
            "`Proposal` row, never a decision of the client"
        )
    elif status == "Open" and not asked(blockers, rest):
        return (
            f"{name} is an open question. Set `Status: Draft` and `Handoff: "
            "Clarification`, copy the question of this row into Blockers and "
            f"ask the user. {ASK}"
        )
    elif status == "Proposal":
        proposal, mark, answer = rest.rpartition("; yes — ")
        answered = mark and proposal.strip() and decided(answer)
        if not answered and not asked(blockers, proposal or rest):
            return (
                f"{name} is a proposal with no answer. Set `Status: Draft` and "
                "`Handoff: Approval` (`Clarification` while an `Open` row "
                "waits), copy the proposal of this row into Blockers as a "
                f"question and ask the user. {ASK}. After a yes, add `; yes — "
                "user|client, <place of the answer>`"
            )
    return None


def form_errors(sections: dict[str, str]) -> list[str]:
    part = sections.get(SECTION, "")
    lines = [line.strip() for line in part.splitlines()]
    found = {
        name: [
            line[len(name) + 1 :].strip()
            for line in lines
            if line.startswith(f"{name}:")
        ]
        for name in LINES
    }
    sources = found["Sources"]
    rows = [line[2:].strip() for line in lines if line.startswith(("- ", "* ", "+ "))]
    if not part.strip():
        return [
            (
                f"plan needs one '## {SECTION}' section. The request is the only "
                "source: write `Sources: N/A — reason`, with no `Reviewer:` line "
                "and no rows. Else write a "
                "`Sources:` line with each source the user gave and the words "
                "`read in full`, a `Reviewer:` line, a `Deliverables:` line, then "
                f"{ROWS}"
            )
        ]
    if len(sources) == 1 and sources[0].startswith("N/A — "):
        if rows:
            return [
                (
                    "`Sources: N/A` holds no rows; delete the rows, or name each "
                    "source on the `Sources:` line"
                )
            ]
        return []
    for name, wanted in LINES.items():
        if len(found[name]) != 1 or not found[name][0]:
            return [f"needs one '{name}:' line: {wanted}"]
    entries = [entry.strip() for entry in sources[0].split(";") if entry.strip()]
    unread = [entry for entry in entries if not read_state(entry)]
    if unread:
        return [
            (
                f"source '{unread[0][:60]}' is not read in full; read it and write "
                "`read in full`. If you cannot read a part, name that part in "
                f"this entry and {PAUSE}. After the user excludes it, add "
                "`excluded by the user` to this entry"
            )
        ]
    reviewer = found["Reviewer"][0].lower()
    if reviewer.startswith(NO_READER if len(entries) > 1 else "pending"):
        return [
            (
                "the second reader has not run; a second reader is required for "
                "more than one source and for one large source. Start a "
                "reader, give it only the sources and the plan, repair what it "
                "finds and write its result on the 'Reviewer:' line. No reader "
                f"can start: set `Reviewer: Pending` and write that {PAUSE}"
            )
        ]
    if not rows:
        return [f"needs {ROWS}"]
    decisions = "\n" + sections["Decisions + authorization"]
    block = decisions.partition("\nBlockers:")[2].partition("\nHandoff:")[0]
    label = block.partition("\n")[0].strip()
    blockers = "" if not label or plans.no_blockers(label) else block.lower()
    acceptance = sections["Acceptance + steps"].splitlines()
    return [error for row in rows if (error := row_error(row, acceptance, blockers))]


def read_state(entry: str) -> bool:
    full = "read in full" in entry and "not read in full" not in entry
    return full or "excluded by the user" in entry


def coverage_errors(
    sections: dict[str, str], legacy: bool, age: Callable[[], bool] | None
) -> list[str]:
    """A Complete plan from before the rule stays valid: an unchanged one, and one last edited before the installed update."""
    errors: list[str] = [] if legacy else form_errors(sections)
    if errors and age is not None and not age():
        return []
    return [f"{SECTION}: {error} (HE-SOURCE-COVERAGE)" for error in errors]
