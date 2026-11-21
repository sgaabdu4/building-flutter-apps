# Browser command

## Plain steps

- `python3 .hooks/hard-eng.py browser --session S <step>` runs one agent-browser step (`open`, `click`, `eval`, `console`, `errors`, `screenshot`, `close`, ...). `browser --session S --help` lists them.
- Plain steps run from `.hard-eng/browser/`, so relative file paths in a step resolve there.

## Capture

- `browser capture <url> --session S [--state FILE] [--ring SELECTOR] [--name NAME]` writes whole-page images at 390, 768 and 1280 px to `.hard-eng/browser/<name>-<width>.png`. It also writes a `<name>-<width>.json` record of the measured findings next to each image, and prints the paths. The measure reports these faults. Text faults: low contrast, text under 11 px, and extra secondary text. Control faults: a missing label, a button or form control under 44 px (even a pointer-only one), a link under 24 px, competing filled buttons, and a password or search field that breaks its row in [Standard patterns](../../he-plan/references/ux.md). The measure does not check links against 44 px, so check that touch target yourself. Layout faults: no shared left edge, more than 2 accent colours, and overflow. Without `--name` the name is `capture`, so a second capture replaces the first. Pass a name for each, such as `--name before` and `--name after`.
- `capture` loads `<url>` fresh at each width and closes its session at the end. It cannot show a state reached by clicks. For such a state, use a URL that opens it, or plain steps followed by `browser measure`. A plain `screenshot` cannot be an After image, because it hides nothing and draws no rings. For a plain `screenshot` that is not an After image, add `--full` and use fake data. Look at the image before you share it. Give `capture` and `signin` their own session name, not the one you click in.
- Red boxes go on each element that a `--ring` selector matches in the main page. Rings do not reach into shadow roots or frames. A `--ring` with no visible match at 390, 768 or 1280 px stops the capture with an error. Ring only elements that show at every width.
- `browser measure --session S --name NAME [--ring SELECTOR]` measures the open session's page at its current width. It saves an image and a record. Use it for a state reached by clicks. `--ring` draws red boxes, as in `capture`. Run it once at each of 390, 768 and 1280 px, with the same `--name`. Before each run, set the width with the plain step `set viewport <width> 900`.
- Emails and phone numbers are hidden, also inside open shadow roots and same-origin frames.
- A frame, `object` or `embed` that the command cannot read, such as a frame from another site, becomes a grey box of the same size. If one still shows when the screenshot is taken, for example because it loaded late, the capture deletes all its images, prints no paths and fails. Do not take a plain `screenshot` instead: capture a page or state without that frame, or report the gap.
- Hiding is a pattern match over page text. It misses names and other personal data, and text in closed shadow roots, canvas, images and video. Look at each image, and use fake data before you share it.

## Sign in

- `browser signin <role> --session S` saves a sign-in to `.hard-eng/browser/state/<role>.json` and prints that path. Pass the printed path to `capture --state`, or to `--state` on the first plain step of a session.
- Roles come from `browser.roles` in `hard-eng.gates.json`: `url` (the login page), `username_env`, `password_env` and an optional `env_file`. The command reads each name from the environment first, then from `env_file`. The password goes to the tool on standard input only.

## Setup limits

- Codex in a workspace-write sandbox cannot start Chrome. Ask for approval, then run every `browser` call, `capture` and `signin` too, outside the sandbox.
- Never pass `--no-sandbox`; the command refuses it.
- On a Linux that limits user namespaces, the command refuses every call and prints a one-time root command. Do not run it yourself. Give it to the user as printed, and run the browser call again after the user confirms it is done.
