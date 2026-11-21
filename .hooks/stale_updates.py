"""Remove what an ended update or push check left behind: candidate worktrees and temporary folders."""

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from tidy_guards import (
    ITEM_ERRORS,
    TidyStop,
    cargo_target,
    expire_rescues,
    foreign_folder,
    holds_repository,
    idle,
    idle_worktree,
    inside,
    logged_ids,
    note,
    open_paths,
    paused_branches,
    quiet_folders,
    reflog_time,
    same_place,
    save_commits,
    scratch_git,
    tidy_git,
    tidy_run,
)

OWNER = re.compile(r"hard-eng-update (\d+)")
TEMPORARY = re.compile(
    r"hard-eng-(?:update|push|gate|gitleaks|dart-parser|scaffold-check|mutation|tidy)-[a-z0-9_]{8}"
)
WORKTREE = re.compile(r"hard-eng-(?:update-.+/candidate|push-.+/project)")


def alive(process: int) -> bool:
    try:
        os.kill(process, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def abandoned(path: Path, owner: re.Match[str] | None) -> bool:
    """Updaters before the lock ran under a one-hour hook, and a push's checks end within a day."""
    if owner is not None:
        return not alive(int(owner[1]))
    hours = 6 if path.name == "candidate" else 24
    try:
        return time.time() - path.parent.stat().st_mtime > hours * 3600
    except FileNotFoundError:
        return False


def sweep_temporary() -> None:
    """Directories a killed Hard Eng process left behind; none of its runs lasts a day."""
    for path in Path(tempfile.gettempdir()).iterdir():
        with suppress(OSError):
            if (
                TEMPORARY.fullmatch(path.name)
                and path.is_dir()
                and not path.is_symlink()
                and time.time() - path.stat().st_mtime > 24 * 3600
            ):
                shutil.rmtree(path)


def stop_idle_watcher(worktree: Path) -> None:
    """Git restarts a file watcher on the next command, so stopping an idle one loses nothing."""
    with suppress(OSError, subprocess.SubprocessError):
        index = subprocess.check_output(
            ["git", "rev-parse", "--path-format=absolute", "--git-path", "index"],
            cwd=worktree,
            text=True,
            timeout=30,
        ).strip()
        if idle(Path(index).stat().st_mtime):
            subprocess.run(
                ["git", "fsmonitor--daemon", "stop"],
                cwd=worktree,
                capture_output=True,
                timeout=30,
                check=False,
            )


def remove_stale_candidates(root: Path) -> None:
    """Remove candidates whose update has exited; the caller holds the lock."""
    from ship_actions import worktrees

    for fields in worktrees(root):
        path = Path(fields.get("worktree", ""))
        owner = OWNER.fullmatch(fields.get("locked", ""))
        if not WORKTREE.fullmatch(f"{path.parent.name}/{path.name}"):
            if path.is_dir() and not same_place(path.resolve(), root.resolve()):
                stop_idle_watcher(path)
            continue
        if not abandoned(path, owner):
            continue
        if owner is not None and not path.exists():
            subprocess.run(
                ["git", "worktree", "unlock", str(path)], cwd=root, check=True
            )
        elif not subprocess.run(
            ["git", "worktree", "remove", "--force", "--force", str(path)],
            cwd=root,
            check=False,
            timeout=120,
        ).returncode:
            shutil.rmtree(path.parent, ignore_errors=True)
    sweep_temporary()
    subprocess.run(["git", "worktree", "prune"], cwd=root, check=True, timeout=60)


STASH_SUBJECT = re.compile(r"(?:WIP on|On) ([^:]+):")
MERGE_REPOSITORY = "merge.git"
ANSWERS = "hard-eng-tidy-gh.json"
REMOVED = "hard-eng-tidy-removed.log"
REMOVED_DAYS = 30
PROTECTED_BRANCHES = {"main", "master", "develop", "hard-eng/update"}
OWNED_PREFIXES = ("codex/",)


def tidy_gh(cwd: Path, *arguments: str) -> list[object] | None:
    """The JSON list gh printed, or None when gh gave no usable answer."""
    try:
        done = tidy_run(cwd, 60, "gh", *arguments)
        found = json.loads(done.stdout) if done.returncode == 0 else None
    except (TidyStop, ValueError):
        return None
    return found if isinstance(found, list) else None


def fetch_tip(root: Path, base: str) -> str:
    """The base tip that origin reported, once its objects are here; no shared FETCH_HEAD."""
    rows = tidy_git(root, "ls-remote", "origin", f"refs/heads/{base}").split()
    if len(rows) != 2:
        raise TidyStop(f"origin has no unique branch {base}")
    tidy_git(root, "fetch", "--quiet", "--no-tags", "origin", base)
    tidy_git(root, "cat-file", "-e", f"{rows[0]}^{{commit}}")
    return rows[0]


def load_answers(path: Path) -> dict[str, dict[str, float]]:
    """What gh said in the last day, so a kept branch costs no call at each session start."""
    found: dict[str, dict[str, float]] = {"unmerged": {}, "open": {}}
    with suppress(OSError, ValueError, AttributeError):
        for kind, entries in json.loads(path.read_text()).items():
            if kind in found:
                found[kind] = {
                    key: stamp
                    for key, stamp in entries.items()
                    if isinstance(stamp, (int, float)) and not idle(stamp)
                }
    return found


@dataclass
class Tidy:
    root: Path
    session: Path
    base: str
    tip: str
    repository: str | None
    on_origin: set[str]
    protected: set[str]
    removed: Counter[str]
    scratch: Path
    common: Path
    answers: dict[str, dict[str, float]]

    @classmethod
    def open(cls, root: Path, removed: Counter[str]) -> "Tidy":
        from shipping import ShippingError, origin_repository
        from update_runner import update_base

        try:
            base = update_base(root)
            tip = fetch_tip(root, base)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise TidyStop(f"fetch of the base branch failed: {error}") from error
        try:
            repository = origin_repository(
                tidy_git(root, "config", "--get", "remote.origin.url").strip()
            )
        except ShippingError:
            repository = None
        heads = tidy_git(root, "ls-remote", "--heads", "origin")
        on_origin = {
            line.split("\t")[1].removeprefix("refs/heads/")
            for line in heads.splitlines()
            if "\t" in line
        }
        default = tidy_run(
            root, 120, "git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"
        )
        named = default.stdout.strip().removeprefix("origin/")
        objects = tidy_git(
            root, "rev-parse", "--path-format=absolute", "--git-path", "objects"
        ).strip()
        scratch = Path(tempfile.mkdtemp(prefix="hard-eng-tidy-"))
        made = scratch_git(
            scratch, "init", "--bare", "--quiet", "--template=", MERGE_REPOSITORY
        )
        if made.returncode:
            raise TidyStop("the scratch repository could not be made")
        (scratch / MERGE_REPOSITORY / "objects/info/alternates").write_text(
            f"{objects}\n"
        )
        common = common_dir(root)
        return cls(
            root,
            root.resolve(),
            base,
            tip,
            repository,
            on_origin,
            {*PROTECTED_BRANCHES, base, named},
            removed,
            scratch,
            common,
            load_answers(common / ANSWERS),
        )

    def content_merged(self, head: str) -> bool:
        """Merging the head into the base tip changes nothing, so the base holds every change.

        The merge runs in an empty repository with no attributes and no merge drivers, so no setting can turn a change into nothing.
        """
        done = scratch_git(
            self.scratch,
            "merge-tree",
            "--write-tree",
            self.tip,
            head,
            repository=self.scratch / MERGE_REPOSITORY,
        )
        if done.returncode == 1:
            return False
        if done.returncode:
            raise TidyStop(f"`git merge-tree` exited {done.returncode}")
        tree = tidy_git(self.root, "rev-parse", f"{self.tip}^{{tree}}").strip()
        return done.stdout.split()[0] == tree

    def named_commits(self, cwd: Path, refs: list[str], tips: list[str]) -> set[str]:
        """The tips and both commit ids of every line in the logs of the refs; a zero id is no commit."""
        commits = set(tips)
        for ref in refs:
            log = Path(
                tidy_git(
                    cwd,
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-path",
                    f"logs/{ref}",
                ).strip()
            )
            commits |= logged_ids(log)
        return {commit for commit in commits if commit.strip("0")}

    def unreachable(self, commits: set[str], *excluded: str) -> list[str]:
        """The named commits that no excluded revision contains; rev-list walks, because --no-walk ignores --not."""
        if not commits:
            return []
        listed = "\n".join([*sorted(commits), "--not", *excluded]) + "\n"
        done = tidy_run(self.root, 120, "git", "rev-list", "--stdin", lines=listed)
        if done.returncode:
            raise TidyStop(f"`git rev-list` exited {done.returncode}")
        return [commit for commit in done.stdout.split() if commit in commits]

    def rescue_tips(self, commits: set[str]) -> list[str]:
        """One tip for each line of commits that the base tip lacks; a ref keeps its ancestors."""
        lacking = self.unreachable(commits, self.tip)
        if not lacking:
            return []
        return tidy_git(
            self.root, "merge-base", "--independent", "--end-of-options", *lacking
        ).split()

    def base_held(self, ignore: str) -> bool:
        """Some local branch, remote-tracking ref or tag other than the one that goes holds the base tip that the checks used; a narrowed fetch refspec leaves none."""
        held = tidy_git(
            self.root,
            "for-each-ref",
            "--count=2",
            "--format=%(refname)",
            "--contains",
            self.tip,
            "refs/heads",
            "refs/remotes",
            "refs/tags",
        )
        return any(name != ignore for name in held.split())

    def destroy(
        self,
        what: str,
        commits: set[str],
        recheck: Callable[[], str | None],
        ref: str,
        *command: str,
    ) -> str | None:
        """The one act that deletes: name every commit by a rescue ref, read the checks last, write the record, then remove."""
        dropped = self.rescue_tips(commits)
        if not self.base_held(ref):
            dropped = [*dropped, self.tip]
        save_commits(self.root, dropped, time.time())
        reason = recheck()
        if reason is None:
            self.record_removal(what)
            tidy_git(self.root, *command)
        return reason

    def reflog_holds_work(
        self, cwd: Path, head: str, refs: list[str], tips: list[str] | None = None
    ) -> bool:
        """A removal drops the logs and refs it owns; keep an item whose logs or refs name a commit that is merged nowhere."""
        commits = self.named_commits(cwd, refs, tips or [])
        if not commits:
            return False
        unmerged = self.unreachable(commits, self.tip, head, "--remotes")
        return not all(self.content_merged(commit) for commit in unmerged)

    def merged(self, state: dict[str, bool], head: str) -> bool:
        if "merged" not in state:
            state["merged"] = self.local_merged(head)
        return state["merged"]

    def local_merged(self, head: str) -> bool:
        ancestor = tidy_run(
            self.root, 120, "git", "merge-base", "--is-ancestor", head, self.tip
        ).returncode
        if ancestor not in {0, 1}:
            raise TidyStop("`git merge-base` failed")
        return ancestor == 0 or self.content_merged(head)

    def fresh(self, kind: str, key: str) -> bool:
        stamp = self.answers[kind].get(key)
        return stamp is not None and not idle(stamp)

    def remember(self, kind: str, key: str) -> None:
        self.answers[kind][key] = time.time()

    def pulls(self, state: str, branch: str, field: str) -> list[object] | None:
        base = ("--base", self.base) if state == "merged" else ()
        return tidy_gh(
            self.root,
            "pr",
            "list",
            "--repo",
            self.repository or "",
            "--state",
            state,
            "--head",
            branch,
            *base,
            "--json",
            field,
        )

    def pr_merged(self, head: str, branch: str | None) -> bool:
        """gh finds a merged PR with this exact head; a no is remembered for a day."""
        key = f"{branch}@{head}"
        if branch is None or self.repository is None or self.fresh("unmerged", key):
            return False
        pulls = self.pulls("merged", branch, "headRefOid")
        found = any(
            isinstance(pull, dict) and pull.get("headRefOid") == head
            for pull in pulls or []
        )
        if pulls is not None and not found:
            self.remember("unmerged", key)
        return found

    def open_pr(self, branch: str) -> bool:
        """True when the branch has an open PR, or when no answer can say that it has none; a yes is remembered for a day."""
        if branch not in self.on_origin:
            return False
        if self.repository is None or self.fresh("open", branch):
            return True
        pulls = self.pulls("open", branch, "number")
        if pulls:
            self.remember("open", branch)
        return pulls is None or bool(pulls)

    def pr_reason(self, head: str, branch: str | None, merged: bool) -> str | None:
        """The checks that ask gh, after every local check passed."""
        if not merged and not self.pr_merged(head, branch):
            return "not merged"
        if branch is not None and self.open_pr(branch):
            return "open PR or no PR answer"
        return None

    def stashed(self, branch: str | None, head: str | None) -> bool:
        listing = tidy_git(self.root, "stash", "list", "--format=%P%x09%gs")
        for line in listing.splitlines():
            parents, _, subject = line.partition("\t")
            parent = parents.split(" ")[0]
            named = STASH_SUBJECT.match(subject)
            if (head is not None and parent == head) or (
                branch is not None and named is not None and named[1] == branch
            ):
                return True
        return False

    def worktree_busy(self, path: Path) -> bool:
        names = open_paths()
        return names is None or inside(path, names)

    def record_removal(self, what: str) -> None:
        """What a removal drops is written first, so a lost branch or folder comes back from its commit within the pruning time."""
        log = self.common / REMOVED
        now = time.time()
        kept: list[str] = []
        with suppress(FileNotFoundError):
            for row in log.read_text().splitlines():
                stamp = row.partition(" ")[0]
                if stamp.isdigit() and now - int(stamp) < REMOVED_DAYS * 86400:
                    kept.append(row)
        log.write_text("".join(f"{row}\n" for row in [*kept, f"{now:.0f} {what}"]))

    def branch_reason(self, name: str, tip: str, checked_out: set[str]) -> str | None:
        state: dict[str, bool] = {}
        local = self.branch_local(name, tip, checked_out, state)
        return local or self.pr_reason(tip, name, self.merged(state, tip))

    def branch_local(
        self, name: str, tip: str, checked_out: set[str], state: dict[str, bool]
    ) -> str | None:
        logged = reflog_time(self.root, f"refs/heads/{name}")

        checks: list[tuple[str, Callable[[], bool]]] = [
            (
                "protected",
                lambda: name in self.protected or name.startswith(OWNED_PREFIXES),
            ),
            ("checked out", lambda: name in checked_out),
            (
                "used in the last 24 hours or no log",
                lambda: logged is None or not idle(logged),
            ),
            (
                "not merged",
                lambda: (
                    not self.merged(state, tip)
                    and self.fresh("unmerged", f"{name}@{tip}")
                ),
            ),
            ("a stash names it", lambda: self.stashed(name, None)),
            (
                "its log holds commits that are merged nowhere",
                lambda: self.reflog_holds_work(self.root, tip, [f"refs/heads/{name}"]),
            ),
        ]
        return next((reason for reason, kept in checks if kept()), None)

    def checked_out(self) -> set[str]:
        from ship_actions import worktrees

        pointed = tidy_git(
            self.root, "for-each-ref", "--format=%(symref)", "refs/heads"
        ).split()
        return (
            {
                record.get("branch", "").removeprefix("refs/heads/")
                for record in worktrees(self.root)
            }
            | paused_branches(self.common)
            | {name.removeprefix("refs/heads/") for name in pointed}
        )

    def remove_branch(self, line: str) -> None:
        tip, ref, symref = line.split(" ")
        name = ref.removeprefix("refs/heads/")
        if symref:
            note(f"kept branch {name}: symbolic ref to {symref}")
            return
        reason = self.branch_reason(name, tip, self.checked_out())
        if reason is not None:
            if reason not in {"protected", "checked out"}:
                note(f"kept branch {name}: {reason}")
            return
        commits = self.named_commits(self.root, [ref], [tip])
        late = self.destroy(
            f"branch {name} {tip}",
            commits,
            lambda: self.branch_local(name, tip, self.checked_out(), {}),
            ref,
            "update-ref",
            "-d",
            "--no-deref",
            ref,
            tip,
        )
        if late is not None:
            note(f"kept branch {name}: {late}")
            return
        note(f"removed branch {name} at {tip} (merged, idle)")
        self.removed["branches"] += 1
        self.drop_config(name)

    def config_keys(self) -> list[str]:
        """Every `branch.<name>.<key>` config key; NUL separated, because a hand-edited subsection may hold a space."""
        done = tidy_run(
            self.root,
            120,
            "git",
            "config",
            "-z",
            "--name-only",
            "--get-regexp",
            r"^branch\.",
        )
        return [key for key in done.stdout.split("\0") if "." in key]

    def drop_config(self, name: str) -> None:
        """The branch is gone; its upstream and description go too. Git matches the section name up to a `]`, and refuses `--remove-section` for a name that holds one, so such a name, or a collision with another name that starts with `<name>]`, is left to per-key commands for the removed branch's own keys. When the collision check itself fails, the log asks for a look and names no removal command."""
        section = f"branch.{name}"
        try:
            keys = self.config_keys()
            own = [key for key in keys if key[len("branch.") : key.rindex(".")] == name]
            others = {
                line.split(" ")[1].removeprefix("refs/heads/")
                for line in tidy_git(
                    self.root,
                    "for-each-ref",
                    "--format=%(objectname) %(refname)",
                    "refs/heads",
                ).splitlines()
            } | {key[len("branch.") : key.rindex(".")] for key in keys}
        except ITEM_ERRORS:
            note(
                f"branch {name} is gone; its settings were not checked, so look at `git config --get-regexp '^branch'` before you reuse the name"
            )
            return
        if "]" in name or any(other.startswith(f"{name}]") for other in others):
            self.advise_unset(name, own)
            return
        try:
            done = tidy_run(
                self.root, 120, "git", "config", "--remove-section", section
            )
            failed = bool(
                done.returncode and "no such section" not in done.stderr
            ) or any(
                key[len("branch.") : key.rindex(".")] == name
                for key in self.config_keys()
            )
        except ITEM_ERRORS:
            failed = True
        if failed:
            note(
                f"branch {name} is gone but its settings stay; run `git config --remove-section {shlex.quote(section)}` before you reuse the name"
            )

    def advise_unset(self, name: str, own: list[str]) -> None:
        """Per-key commands touch only the removed branch's section; no own key means nothing stays and nothing is said."""
        if own:
            note(
                f"branch {name} is gone but its settings stay, because Git cannot remove a section of that name safely; run "
                + "; ".join(
                    f"`git config --unset-all {shlex.quote(key)}`" for key in own
                )
            )

    def remove_branches(self) -> None:
        """A failure on one branch keeps it and goes on; a failed listing stops the repository."""
        if (self.common / "info/grafts").exists():
            note("kept every branch: info/grafts changes what counts as an ancestor")
            return
        storage = tidy_run(
            self.root, 120, "git", "config", "--get", "extensions.refstorage"
        )
        if storage.stdout.strip() not in {"", "files"}:
            note("kept every branch: the reflogs are not plain files (reftable)")
            return
        listing = tidy_git(
            self.root,
            "for-each-ref",
            "--format=%(objectname) %(refname) %(symref)",
            "refs/heads",
        )
        for line in listing.splitlines():
            try:
                self.remove_branch(line)
            except ITEM_ERRORS as error:
                note(f"kept branch {line.split(' ')[1]}: {error}")

    def target_reason(self, path: Path) -> str | None:
        target = path / "target"
        checks: list[tuple[str, Callable[[], bool]]] = [
            (
                "no cargo build folder",
                lambda: not (path / "Cargo.toml").is_file() or not cargo_target(path),
            ),
            (
                "the build folder is a link or a mount point",
                lambda: foreign_folder(path, target),
            ),
            (
                "git does not ignore it",
                lambda: (
                    tidy_run(
                        path, 120, "git", "check-ignore", "-q", "target"
                    ).returncode
                    != 0
                ),
            ),
            (
                "git tracks files in it",
                lambda: bool(tidy_git(path, "ls-files", "--", "target").strip()),
            ),
            (
                "worktree used in the last 24 hours",
                lambda: not idle_worktree(path),
            ),
            (
                "build folder changed in the last 24 hours",
                lambda: not quiet_folders(target),
            ),
            ("a process is inside", lambda: self.worktree_busy(path)),
            (
                "a nested repository is inside it",
                lambda: holds_repository(target),
            ),
        ]
        return next((reason for reason, kept in checks if kept()), None)

    def trim_target(self, record: dict[str, str]) -> None:
        path = Path(record.get("worktree", ""))
        if (
            "bare" in record
            or "prunable" in record
            or not path.is_dir()
            or same_place(path.resolve(), self.session)
        ):
            return
        reason = self.target_reason(path)
        if reason is None:
            shutil.rmtree(path / "target")
            note(f"removed build folder {path / 'target'} (idle cargo target)")
            self.removed["build folders"] += 1
        elif not reason.startswith("no cargo"):
            note(f"kept build folder {path / 'target'}: {reason}")

    def trim_targets(self) -> None:
        """A failure on one build folder keeps it and goes on; a failed listing stops the repository."""
        from ship_actions import worktrees

        for record in worktrees(self.root):
            try:
                self.trim_target(record)
            except ITEM_ERRORS as error:
                note(f"kept build folder of {record.get('worktree')}: {error}")

    def run(self) -> None:
        self.remove_branches()
        self.trim_targets()
        expire_rescues(self.root, time.time())


def tidy(root: Path) -> None:
    """Remove merged idle worktrees and branches and idle cargo build folders. One item that fails is kept and the next goes on; a failure for the whole repository stops it."""
    from update_runner import LOG_FILE, RESULT_FILE, exclusive

    removed: Counter[str] = Counter()
    with (common_dir(root) / "hard-eng-tidy.lock").open("a") as handle:
        if not exclusive(handle):
            note("skipped: another tidy is running")
            return
        opened: Tidy | None = None
        try:
            opened = Tidy.open(root, removed)
            opened.run()
        except ITEM_ERRORS as error:
            note(
                f"stopped for this repository, what is not yet removed is kept: {error}"
            )
        finally:
            if opened is not None:
                shutil.rmtree(opened.scratch, ignore_errors=True)
                with suppress(OSError):
                    (opened.common / ANSWERS).write_text(json.dumps(opened.answers))
    if removed:
        result = root / RESULT_FILE
        result.parent.mkdir(parents=True, exist_ok=True)
        counts = ", ".join(
            f"{removed[kind]} {kind}" for kind in ("branches", "build folders")
        )
        with result.open("a") as out:
            out.write(f"Tidy: removed {counts} ({LOG_FILE}).\n")


MARKER = "# Hard Eng worktree launcher, local to this checkout"


def git_run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments], cwd=root, capture_output=True, text=True, check=False
    )


def common_dir(root: Path) -> Path:
    found = git_run(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(found.stdout.strip()).resolve()


def worktree_place(root: Path, target: Path) -> tuple[str, str, Path]:
    """Where a hook file sits: in Git's folder, tracked, ignored or loose in the main checkout, or elsewhere."""
    common = common_dir(root)
    place = target.resolve()
    main = common.parent
    if place.is_relative_to(common):
        return "git", "", main
    folder = next(path for path in place.parents if path.is_dir())
    top = git_run(folder, "rev-parse", "--show-toplevel").stdout.strip()
    if common.name != ".git" or not top or Path(top).resolve() != main:
        return "elsewhere", "", main
    name = place.relative_to(main).as_posix()
    if git_run(main, "ls-files", "--error-unmatch", "--", name).returncode == 0:
        return "tracked", name, main
    if git_run(main, "check-ignore", "-q", "--", name).returncode == 0:
        return "ignored", name, main
    return "loose", name, main


def committed_bytes(root: Path, name: str) -> bytes | None:
    revision = "HEAD:" + name
    shown = subprocess.run(
        ["git", "show", revision], cwd=root, capture_output=True, check=False
    )
    return None if shown.returncode else shown.stdout


def exclude_file(root: Path) -> Path:
    found = git_run(
        root, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"
    )
    return Path(found.stdout.strip())


def hide(root: Path, name: str) -> None:
    """Keep the loose launcher out of status once the install commit holds the source file."""
    from gate_config import SOURCE_FILE

    exclude = exclude_file(root)
    text = exclude.read_text() if exclude.is_file() else ""
    line = "/" + name
    if line in text.splitlines() or committed_bytes(root, SOURCE_FILE) is None:
        return
    exclude.parent.mkdir(parents=True, exist_ok=True)
    separator = "" if not text or text.endswith("\n") else "\n"
    with exclude.open("a") as handle:
        handle.write(f"{separator}{MARKER}\n{line}\n")


def unhide(root: Path, name: str) -> None:
    """Remove the exclude line that hide wrote, and only that one."""
    exclude = exclude_file(root)
    if not exclude.is_file():
        return
    lines = exclude.read_text().splitlines(keepends=True)
    for index in range(1, len(lines)):
        if (
            lines[index].rstrip("\r\n") == "/" + name
            and lines[index - 1].rstrip("\r\n") == MARKER
        ):
            del lines[index - 1 : index + 1]
            exclude.write_text("".join(lines))
            return


def give_back(root: Path, target: Path, name: str) -> None:
    """Restore the tracked hook that a rerun replaced, when its kept copy still equals the committed hook."""
    import hook_chain

    copy = hook_chain.project_copy(target)
    committed = committed_bytes(root, name)
    mode = git_run(root, "ls-tree", "HEAD", "--", name).stdout.split(" ", 1)[0]
    if (
        committed is None
        or mode not in {"100644", "100755"}
        or copy.is_symlink()
        or not copy.is_file()
        or copy.read_bytes() != committed
        or git_run(
            root, "ls-files", "--error-unmatch", "--", copy.relative_to(root).as_posix()
        ).returncode
        == 0
        or not (hook_chain.is_own(root, target) or target.read_bytes() == committed)
    ):
        return
    target.unlink(missing_ok=True)
    target.write_bytes(committed)
    target.chmod(0o755 if mode == "100755" else 0o644)
    copy.unlink()


def without_launchers(
    root: Path, shared: list[dict[str, list[str]]], listed: set[str]
) -> None:
    """Take the launchers that the committed gates file does not list out of each shellcheck command."""
    import hook_chain

    for gate in list(shared):
        command = gate["command"]
        if Path(command[0]).name != "shellcheck" or "--" not in command:
            continue
        gate["command"] = [
            part
            for part in command
            if part in listed or not hook_chain.is_own(root, root / part)
        ]
        if gate["command"] != command and gate["command"][-1] == "--":
            shared.remove(gate)


def drop_launcher_entries(root: Path) -> None:
    """Undo a rerun that listed Hard Eng's launcher in the shell gate, when nothing else in the file changed."""
    import json

    gates = root / "hard-eng.gates.json"
    committed = committed_bytes(root, gates.name)
    if (
        committed is None
        or gates.is_symlink()
        or not gates.is_file()
        or gates.read_bytes() == committed
    ):
        return
    try:
        config, head = json.loads(gates.read_bytes()), json.loads(committed)
        listed = {part for gate in head["shared"] for part in gate["command"]}
        without_launchers(root, config["shared"], listed)
    except (ValueError, KeyError, TypeError, IndexError):
        return
    if config == head:
        gates.write_bytes(committed)


def settle_main(main: Path, own: bool) -> None:
    import hook_chain

    target = hook_chain.locate(main, "post-checkout")[1]
    place, name, _ = worktree_place(main, target)
    if place == "loose" and hook_chain.is_own(main, target):
        hide(main, name)
    elif (
        place == "ignored" and target.is_file() and not hook_chain.is_own(main, target)
    ):
        unhide(main, name)
    elif place == "tracked" and own:
        give_back(main, target, name)
    if own:
        drop_launcher_entries(main)


def settle_worktree_hook(root: Path) -> None:
    """Undo what an earlier setup rerun left in a hooks folder inside the main checkout."""
    common = common_dir(root)
    if common.name != ".git":
        return
    try:
        settle_main(common.parent, common.parent == root.resolve())
    except (ValueError, OSError, subprocess.SubprocessError):
        return
