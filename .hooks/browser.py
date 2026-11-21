"""One browser command for agents: plain steps, sign-in per role and full-page captures."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import cast

from gate_config import GateConfig, parse_config

TOOL = "agent-browser"
ROLE_NAME = re.compile(r"[A-Za-z0-9_-]+")
USAGE = (
    "browser --session S <agent-browser step>: run one step from .hard-eng/browser. "
    "browser capture <url> --session S [--state FILE] [--ring SELECTOR] [--name NAME]: "
    "whole-page images at the standard widths with red boxes and hidden emails and phones, "
    "and a measured record for each image. "
    "browser measure --session S --name NAME [--ring SELECTOR]: the same for the open "
    "session's page at its current width. "
    "browser signin <role> --session S: save a session file for a role of hard-eng.gates.json. "
    "Every step needs its own --session; close --all is refused."
)
TIMEOUT = 600
STEP_TIMEOUT = 300
REFRESH_SECONDS = 24 * 60 * 60
WIDTHS = (390, 768, 1280)
SHARED = (
    "Each agent keeps its own browser session: pass --session NAME, and never "
    "`close --all`, because parallel agents share the tool."
)
USERNS_LIMIT = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
CHROME_PROFILE = Path("/etc/apparmor.d/agent-browser-chrome")
PROFILE = (
    "abi <abi/4.0>,\\ninclude <tunables/global>\\nprofile agent-browser-chrome "
    "@{HOME}/.agent-browser/browsers/chrome-*/chrome flags=(unconfined) {\\n  userns,\\n}\\n"
)
NO_SANDBOX = re.compile(r"(?:^|[\s,])--no-sandbox(?=$|[\s,=])")

PAGE_SCRIPT = """(async () => {
const phone = /(?<!\\d)(?:\\+\\d{1,3}[\\s.-]?)?(?:\\(\\d{2,5}\\)|\\d{2,5})[\\s.-]?\\d{3,5}(?:[\\s.-]?\\d{3,5})?(?!\\d)/g;
const hide = (text) => text
  .replace(/[\\w.+-]+@[\\w-]+(?:\\.[\\w-]+)+/g, "[hidden]")
  .replace(phone, (found) => (found.replace(/\\D/g, "").length >= 9 ? "[hidden]" : found));
const hideText = (node) => {
  if (node.parentElement?.closest("script,style,noscript")) return;
  const text = hide(node.nodeValue);
  if (text !== node.nodeValue) node.nodeValue = text;
};
const replaceFrame = (frame) => {
  if (!frame.isConnected) return;
  const box = frame.getBoundingClientRect();
  const holder = frame.ownerDocument.createElement("div");
  for (const name of ["id", "class", "style"]) {
    const value = frame.getAttribute(name);
    if (value !== null) holder.setAttribute(name, value);
  }
  holder.dataset.hardEngFrame = "";
  holder.textContent = "[frame hidden]";
  Object.assign(holder.style, {
    boxSizing: "border-box", overflow: "hidden", background: "#888", color: "#fff", font: "12px sans-serif",
  });
  if (box.width && box.height) Object.assign(holder.style, { width: box.width + "px", height: box.height + "px" });
  frame.replaceWith(holder);
};
const observer = new MutationObserver((changes) => {
  for (const change of changes) {
    if (change.type === "characterData") hideText(change.target);
    else if (change.type === "attributes" && change.target.matches("iframe,frame")) replaceFrame(change.target);
    else change.addedNodes.forEach(hideAll);
  }
});
const watch = (root) => {
  hideAll(root);
  observer.observe(root, {
    subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["src", "srcdoc"],
  });
};
const wrap = (view) => {
  const attach = view.Element.prototype.attachShadow;
  if (attach.hardEngWrapped) return;
  const wrapped = function (init) {
    const root = attach.call(this, init);
    watch(root);
    return root;
  };
  wrapped.hardEngWrapped = true;
  view.Element.prototype.attachShadow = wrapped;
};
wrap(window);
const watchFrame = (frame) => {
  let inner = null;
  try { inner = frame.contentDocument; } catch (error) { inner = null; }
  if (!inner?.body || (inner.URL === "about:blank" && frame.getAttribute("src"))) return replaceFrame(frame);
  frame.dataset.hardEngRead = "";
  wrap(inner.defaultView);
  if (!frame.hardEngWatched) {
    frame.hardEngWatched = true;
    frame.addEventListener("load", () => watchFrame(frame));
  }
  watch(inner.body);
};
const hideAll = (root) => {
  if (root.nodeType === Node.TEXT_NODE) return hideText(root);
  if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) return;
  const walker = (root.ownerDocument || document).createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) hideText(node);
  for (const element of [root, ...root.querySelectorAll("*")]) {
    if (element.matches?.("input,textarea") && element.type !== "password") element.value = hide(element.value);
    if (element.shadowRoot) watch(element.shadowRoot);
    if (element.matches?.("iframe,frame")) watchFrame(element);
    else if (element.matches?.("object,embed")) replaceFrame(element);
  }
};
watch(document.body);
const pageHeight = document.documentElement.scrollHeight;
const fixed = [...document.body.querySelectorAll("*")].flatMap((element) => {
  const style = getComputedStyle(element);
  const box = element.getBoundingClientRect();
  const inside = box.left >= -1 && box.top >= -1 && box.right <= innerWidth + 1 && box.bottom <= innerHeight + 1;
  return style.position === "fixed" && box.width && box.height && inside ? [{ element, style, box }] : [];
});
for (const { element, style, box } of fixed) {
  const atBottom = style.top === "auto" || box.top + box.height / 2 > innerHeight / 2;
  Object.assign(element.style, {
    position: "absolute", top: "0px", left: "0px", bottom: "auto", right: "auto",
    width: box.width + "px", height: box.height + "px", boxSizing: "border-box",
  });
  const now = element.getBoundingClientRect();
  element.style.top = (atBottom ? pageHeight - innerHeight : 0) + box.top - now.top - scrollY + "px";
  element.style.left = box.left - now.left + "px";
}
document.querySelectorAll("[data-he-ring]").forEach((ring) => ring.remove());
const missing = [];
for (const selector of RINGS) {
  let found = [];
  try { found = [...document.querySelectorAll(selector)]; } catch (error) { found = []; }
  const shown = found.filter((element) => {
    const box = element.getBoundingClientRect();
    return box.width > 0 && box.height > 0;
  });
  if (!shown.length) missing.push(selector);
  for (const element of shown) {
    const box = element.getBoundingClientRect();
    const ring = document.createElement("div");
    ring.dataset.heRing = "";
    Object.assign(ring.style, {
      position: "absolute", left: box.left + scrollX + "px", top: box.top + scrollY + "px",
      width: box.width + "px", height: box.height + "px", boxSizing: "border-box",
      border: "3px solid red", pointerEvents: "none", zIndex: "2147483647",
    });
    document.documentElement.appendChild(ring);
  }
}
return JSON.stringify(missing);
})()"""


FRAME_CHECK = """(() => {
const unread = (root) => [...root.querySelectorAll("*")].reduce((count, element) => {
  if (element.matches("object,embed")) return count + 1;
  if (element.shadowRoot) count += unread(element.shadowRoot);
  if (!element.matches("iframe,frame")) return count;
  if (!("hardEngRead" in element.dataset)) return count + 1;
  try { return count + unread(element.contentDocument); } catch (error) { return count + 1; }
}, 0);
return unread(document);
})()"""


def browser_roles(config: GateConfig) -> dict[str, dict[str, str]]:
    """Each `browser.roles` entry: a login page and the names of the variables that hold its sign-in."""
    section = config.get("browser", {})
    roles = section.get("roles", {}) if isinstance(section, dict) else None
    if not isinstance(roles, dict):
        raise TypeError("browser must be an object whose roles is an object")
    required = {"url", "username_env", "password_env"}
    for name, role in roles.items():
        if (
            not ROLE_NAME.fullmatch(name)
            or not isinstance(role, dict)
            or not required <= role.keys() <= required | {"env_file"}
            or not all(isinstance(value, str) and value for value in role.values())
        ):
            raise TypeError(
                f"browser.roles.{name} needs url, username_env and password_env as text, "
                "and may have env_file; the role name uses letters, digits, - and _"
            )
    return cast(dict[str, dict[str, str]], roles)


def output_folder(root: Path) -> Path:
    folder = root / ".hard-eng/browser"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def ensure_tool() -> str:
    """Install agent-browser when missing, else reuse it offline; look for a newer release once a day."""
    import fcntl
    from contextlib import redirect_stdout

    from tool_setup import PACKAGES, provision_batch, shared_tool_folder

    stamp = shared_tool_folder() / "browser-refreshed"
    stamp.parent.mkdir(parents=True, exist_ok=True)
    lock = (stamp.parent / "browser-install.lock").open("a")
    with lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with redirect_stdout(sys.stderr):
            due = (
                not stamp.exists()
                or time.time() - stamp.stat().st_mtime > REFRESH_SECONDS
            )
            batch = [PACKAGES[TOOL] + "@latest"]
            try:
                provision_batch(batch, TIMEOUT, offline=not due)
            except (subprocess.SubprocessError, OSError, ValueError):
                if not due:
                    raise
                provision_batch(batch, TIMEOUT, offline=True)
                due = False
            tool = shutil.which(TOOL)
            if tool is None:
                raise ValueError(f"{TOOL} is not on PATH after its install")
            digest = hashlib.sha256(tool.encode()).hexdigest()[:12]
            chrome = stamp.parent / f"browser-chrome-{digest}"
            if due or not chrome.is_file():
                done = subprocess.run(
                    [tool, "install"],
                    stdout=subprocess.PIPE,
                    text=True,
                    check=False,
                    timeout=TIMEOUT,
                )
                print(done.stdout, end="")
                if done.returncode:
                    raise ValueError(f"`{TOOL} install` failed; its messages are above")
                chrome.touch()
                if due:
                    stamp.touch()
    return tool


def sandbox_refusal(steps: list[str]) -> str | None:
    if any(
        NO_SANDBOX.search(text)
        for text in [*steps, os.environ.get("AGENT_BROWSER_ARGS", "")]
    ):
        return (
            "browser: --no-sandbox is refused, because it lets a page reach this "
            "machine and the signed-in session files."
        )
    if (
        USERNS_LIMIT.is_file()
        and USERNS_LIMIT.read_text().strip() == "1"
        and not CHROME_PROFILE.is_file()
    ):
        return (
            "browser: this Linux limits user namespaces through AppArmor, so Chrome "
            "cannot start its sandbox. Never pass --no-sandbox. Ask the user to run "
            f"once, as root:\n{root_step()}"
        )
    return None


def root_step() -> str:
    """The one-time step that lets the downloaded Chrome keep its sandbox under AppArmor."""
    return (
        f"printf '{PROFILE}' | sudo tee {CHROME_PROFILE} >/dev/null"
        f" && sudo apparmor_parser -r {CHROME_PROFILE}"
    )


def refusal(steps: list[str]) -> str | None:
    if not any(step == "--session" or step.startswith("--session=") for step in steps):
        return "browser: pass --session NAME. " + SHARED
    if "close" in steps and "--all" in steps:
        return "browser: `close --all` would end other agents' browsers. " + SHARED
    return None


def checkout_space(folder: Path) -> dict[str, str]:
    """Sessions live in the home folder; a namespace per checkout keeps worktrees apart."""
    digest = hashlib.sha256(str(folder.resolve()).encode()).hexdigest()[:10]
    return {**os.environ, "AGENT_BROWSER_NAMESPACE": "he-" + digest}


def run_tool(
    tool: str, folder: Path, session: str, *arguments: str, text: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [tool, "--session", session, *arguments],
        cwd=folder,
        env=checkout_space(folder),
        input=text,
        capture_output=True,
        text=True,
        check=False,
        timeout=STEP_TIMEOUT,
    )


def require(result: subprocess.CompletedProcess[str], secret: str = "") -> str:
    if result.returncode:
        message = (result.stderr or result.stdout).strip()
        raise ValueError(
            f"{TOOL} failed: {message.replace(secret, '***') if secret else message}"
        )
    return result.stdout


def unread_frames(tool: str, folder: Path, session: str, width: int) -> None:
    if json.loads(require(run_tool(tool, folder, session, "eval", FRAME_CHECK))):
        raise ValueError(
            f"a frame or embed that the capture could not read was on the page at width {width}, "
            "so it could show personal data; no image was kept"
        )


def measure_page(tool: str, folder: Path, session: str) -> list[dict[str, object]]:
    """The faults of the page as it is now: the page script and axe, before anything draws on it."""
    from ui_measure import AXE_TAGS, axe_findings, decoration_script, measure_script

    reply = require(
        run_tool(tool, folder, session, "eval", "--stdin", text=measure_script())
    )
    audit = require(
        run_tool(tool, folder, session, "a11y", "--tags", AXE_TAGS, "--json")
    )
    found = [*json.loads(json.loads(reply)), *axe_findings(audit)]
    contrast = [item for item in found if item["rule"] == "contrast"]
    if not contrast:
        return found
    selectors = [str(item["at"]) for item in contrast]
    reply = require(
        run_tool(
            tool, folder, session, "eval", "--stdin", text=decoration_script(selectors)
        )
    )
    flags = json.loads(json.loads(reply))
    skipped = [item for item, flag in zip(contrast, flags, strict=True) if flag]
    return [item for item in found if not any(item is gone for gone in skipped)]


def shoot_page(
    tool: str, root: Path, session: str, rings: list[str], name: str, width: int
) -> Path:
    """Measure the open page, hide personal data, draw rings and keep an image with its record."""
    from ui_measure import write_record

    folder = output_folder(root)
    findings = measure_page(tool, folder, session)
    script = PAGE_SCRIPT.replace("RINGS", json.dumps(rings))
    reply = require(run_tool(tool, folder, session, "eval", "--stdin", text=script))
    if missing := json.loads(json.loads(reply)):
        raise ValueError(
            f"--ring {', '.join(missing)} matched no visible element at width {width}"
        )
    unread_frames(tool, folder, session, width)
    image = folder / f"{name}-{width}.png"
    try:
        require(run_tool(tool, folder, session, "screenshot", "--full", str(image)))
        unread_frames(tool, folder, session, width)
        route = json.loads(
            require(run_tool(tool, folder, session, "eval", "location.pathname"))
        )
        write_record(root, image, width, findings, str(route))
    except BaseException:
        image.unlink(missing_ok=True)
        image.with_suffix(".json").unlink(missing_ok=True)
        raise
    if findings:
        print(
            f"browser: {len(findings)} findings at {width} px in {image.name}: "
            + ", ".join(
                f"{rule} x{count}"
                for rule, count in Counter(f["rule"] for f in findings).items()
            ),
            file=sys.stderr,
        )
    return image


def capture_page(tool: str, root: Path, args: argparse.Namespace, width: int) -> Path:
    state = ["--state", args.state] if args.state and width == WIDTHS[0] else []
    steps = [
        (*state, "set", "viewport", str(width), "900"),
        ("open", args.url),
        ("wait", "--load", "networkidle"),
    ]
    for step in steps:
        require(run_tool(tool, output_folder(root), args.session, *step))
    return shoot_page(tool, root, args.session, args.ring, args.name, width)


def forget(images: list[Path]) -> None:
    for image in images:
        image.unlink(missing_ok=True)
        image.with_suffix(".json").unlink(missing_ok=True)


def capture(root: Path, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="hard-eng.py browser capture")
    parser.add_argument("url")
    parser.add_argument("--session", required=True)
    parser.add_argument("--state")
    parser.add_argument("--ring", action="append", default=[])
    parser.add_argument("--name", default="capture")
    args = parser.parse_args(argv)
    if args.state:
        args.state = str(Path(args.state).resolve())
    tool, folder = ensure_tool(), output_folder(root)
    images: list[Path] = []
    try:
        for width in WIDTHS:
            images.append(capture_page(tool, root, args, width))
    except BaseException:
        forget(images)
        raise
    finally:
        run_tool(tool, folder, args.session, "close")
    print("\n".join(str(image) for image in images))
    return 0


def measure(root: Path, argv: list[str]) -> int:
    """Measure and capture the open session's page at its current width, and leave the session open."""
    parser = argparse.ArgumentParser(prog="hard-eng.py browser measure")
    parser.add_argument("--session", required=True)
    parser.add_argument("--ring", action="append", default=[])
    parser.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    tool, folder = ensure_tool(), output_folder(root)
    width = int(
        json.loads(require(run_tool(tool, folder, args.session, "eval", "innerWidth")))
    )
    print(shoot_page(tool, root, args.session, args.ring, args.name, width))
    return 0


def environment_value(name: str, env_file: Path | None) -> str:
    if name in os.environ:
        return os.environ[name]
    if env_file is not None and env_file.is_file():
        for line in env_file.read_text().splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            if key.strip() == name:
                return value.strip().strip("'\"")
    raise ValueError(f"{name} is not set in the environment or the role's env_file")


def signin(root: Path, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="hard-eng.py browser signin")
    parser.add_argument("role")
    parser.add_argument("--session", required=True)
    args = parser.parse_args(argv)
    roles = browser_roles(
        parse_config(
            (root / "hard-eng.gates.json").read_text(), require_impact_review=False
        )
    )
    if args.role not in roles:
        raise ValueError(f"browser.roles has no role {args.role}")
    role = roles[args.role]
    env_file = root / role["env_file"] if "env_file" in role else None
    username = environment_value(role["username_env"], env_file)
    password = environment_value(role["password_env"], env_file)
    tool, folder = ensure_tool(), output_folder(root)
    state = folder / "state" / f"{args.role}.json"
    login = f"{args.role}-{uuid.uuid4().hex[:12]}"
    state.parent.mkdir(exist_ok=True)

    def step(*arguments: str, text: str | None = None) -> str:
        return require(
            run_tool(tool, folder, args.session, *arguments, text=text), password
        )

    try:
        step(
            "auth",
            "save",
            login,
            "--url",
            role["url"],
            "--username",
            username,
            "--password-stdin",
            text=password,
        )
        step("auth", "login", login)
        step("state", "save", str(state))
    finally:
        run_tool(tool, folder, args.session, "auth", "delete", login)
        run_tool(tool, folder, args.session, "close")
    print(state)
    return 0


def dispatch(root: Path, argv: list[str]) -> int:
    if argv[:1] == ["capture"]:
        return capture(root, argv[1:])
    if argv[:1] == ["signin"]:
        return signin(root, argv[1:])
    if argv[:1] == ["measure"]:
        return measure(root, argv[1:])
    if reason := refusal(argv):
        print(reason, file=sys.stderr)
        return 2
    tool = ensure_tool()
    folder = output_folder(root)
    os.chdir(folder)
    os.execve(tool, [tool, *argv], checkout_space(folder))


def run(root: Path, argv: list[str]) -> int:
    """The launcher's entry for `browser` and for `look`, which shares its fast start."""
    if argv[0] == "look":
        from look import look_main

        return look_main(root, argv[1:])
    return browser_command(root, argv[1:])


def browser_command(root: Path, argv: list[str]) -> int:
    if reason := sandbox_refusal(argv):
        print(reason, file=sys.stderr)
        return 2
    try:
        return dispatch(root, argv)
    except (ValueError, TypeError, OSError, subprocess.SubprocessError) as error:
        print(f"Hard Eng: {error}", file=sys.stderr)
        return 1


def add_browser_command(add_parser: Callable[..., argparse.ArgumentParser]) -> None:
    add_parser(
        "browser",
        help="Drive a real browser with agent-browser: plain steps, capture, signin",
        description=USAGE,
    )
