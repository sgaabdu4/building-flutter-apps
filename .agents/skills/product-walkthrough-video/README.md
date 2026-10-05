# Playwright walkthrough skill

Workflow owner for the bundled recorder, review and MP4 delivery scripts. Run commands from this package directory. Use the existing runtime when available; install missing dependencies only within task authorization.

## Setup

```bash
cd /absolute/path/to/product-walkthrough-video
pnpm install --frozen-lockfile --ignore-scripts
pnpm exec playwright install chromium
brew install ffmpeg
```

On Linux, install FFmpeg with `sudo apt-get install -y ffmpeg` instead of Homebrew.

The skill pins Playwright in `package.json`; 1.62+ provides `page.screencast`, persistent user overlays, and exact recording start/stop control.

## Workflow

### Recorded E2E

For E2E-owned recorded web proof, run Phases 1–9 below: inspect/configure the real journey, record, mechanically check, visually inspect, repair and approve the exact WebM. Return the accepted WebM + run/review reports to [E2E](../e2e/SKILL.md#prove-the-journey) for product assertions and durable-state proof. MP4 conversion is unnecessary for this route.

Use the existing `pointer: false` configuration when no presentation pointer is needed; the pointer ring and its visibility/continuity and click-ripple checks then do not apply. Drag steps require the pointer's frame-level gesture audit, so pointer-free journeys use click, scroll, type, and press instead. Target geometry, focus, keyboard cues, strict journey checks, checkpoints, readable holds and the remaining mechanical/visual review still apply. This is still a paced recording, not raw rendering or latency proof. Arbitrary browser/device videos lack this recorder's required run report; use native verification for those surfaces.

### Video delivery

For a polished walkthrough, run Phases 1–11 below with the presentation pointer enabled. Reuse the same WebM verification, then convert the accepted source and separately review the exact delivered MP4. No second recorder or verification implementation.

## Non-negotiable recording method

- Use Playwright 1.62+ `page.screencast.start()` after the opening state is fully ready.
- Do not use browser-context `recordVideo` for the delivery recording. It starts during page creation and can capture blank or loading frames.
- When the pointer is enabled, use one only: the exact 20px red v17 ring in Playwright's `page.screencast.showOverlay()` plane. Pointer visibility/continuity and click-ripple requirements below apply only then; [Recorded E2E](#recorded-e2e) owns `pointer: false`.
- Do not put the persistent pointer in application DOM. Keep it in Playwright's user-overlay plane. The same-state reload guard may use the prior checkpoint as a transient document-start bitmap in a recorder-owned closed shadow root; it is not an interactive pointer and must be removed after readiness.
- Move Playwright's real mouse with timed intermediate events. `mouse.move({ steps })` alone is not pacing.
- Express canvas and drag-and-drop input with the strict locator-relative `drag` action. Do not replace the runner with custom Playwright code or use unexplained viewport coordinates.
- Use `typeKeys` for one paced text string after a visible action focuses a canvas or keyboard-driven editor. Do not create one held step per character.
- For a same-state full-document reload with an unavoidable bootstrap paint, `preserveVisualDuringReload` may bridge Playwright's post-commit overlay reattachment with the exact prior checkpoint from document start through readiness. Never use it for route changes or to conceal a meaningful product state; the zero-blank navigation audit includes the handoff immediately before navigation.
- Use timed smooth wheel increments. Never use one large wheel event for a product walkthrough.
- Use locators for final actions. Never click stale absolute coordinates.
- Pointer activation = stable target box + pointer inside it + at least 150ms settled + visible click cue + activation timestamp.
- `press` = stable target or explicit global scope + confirmed focus + visible key cue. Hide the pointer from cue start through activation so it cannot imply a click on another control.
- Input evidence = type + target/focus boxes + pointer position + settle time + activation time + cue interval. Do not add raw target text, selectors, typed values, URLs, or account data to this evidence.
- Use fixed waits only as presentation holds after a deterministic product-state wait or assertion.

The scripts in this directory implement these rules. Do not replace them with an improvised recorder.

## Required inputs

Determine these by inspecting the repository and the user's request:

- repository path;
- existing command that starts the application;
- local base URL;
- product-specific selector that proves the opening page is ready;
- intended start state;
- complete user journey;
- final state and assertion that proves success;
- stable accessible locator for every interaction;
- explicitly allowed API origins;
- safe seeded fixture, storage state, or test account if authentication is required.

Never record credentials, tokens, real customer data, private payloads, or an uncontrolled production session.

## Phase 1: inspect the repository

Read the package manifest, existing test and preview scripts, routes, application entry points, relevant feature code, existing Playwright tests, fixtures, and seed data.

Build the journey from the real product:

1. Start state.
2. Meaningful user action.
3. Visible product response.
4. Gate or decision.
5. Next action.
6. Final assertion.

Do not invent text, selectors, routes, or product behavior. Prefer role, label, placeholder, test-id, and exact text locators. Use stable CSS only for state markers that have no accessible locator.

## Phase 2: scaffold and configure

```bash
node scripts/scaffold.mjs \
  --repo /absolute/path/to/repository \
  --out /absolute/path/to/repository/.walkthrough \
  --base-url http://127.0.0.1:3000/ \
  --name feature-walkthrough
```

Replace the generated examples. Keep:

- `strictE2E: true`;
- a first `goto` step;
- a product-specific `readySelector`;
- `reducedMotion: "reduce"`;
- `captureStepScreenshots: true`;
- `blockExternalRequests: true`;
- the Playwright screencast pointer;
- `pointer.moveDurationMs` around 700–1000ms;
- `scrollDurationMs` at or above 600ms;
- `dragDurationMs` at or above 600ms for gesture journeys;
- holds at or above `minReadableHoldMs`;
- a final assertion within the final four steps;
- a final pause.

Strict preflight must remain enabled. Do not weaken the gate to make a broken config run.

## Phase 3: establish safety boundaries

Set:

- `allowedOrigins` to the local app and only the APIs needed by the journey;
- `allowedHttpResponses` only for deliberate, asserted negative-path responses, matched by exact status and narrow URL substring;
- `blockExternalRequests: true`;
- `blockEventStreams: true` unless an event stream is part of the feature;
- `acceptDownloads: false`;
- an uncommitted `storageState` only when needed.

Use a local safe proxy when an open-source demo references analytics, remote fonts, avatars, or other unrelated third-party assets. Replace those assets locally rather than allowlisting the internet.

An expected failed-auth or validation request must remain visible in evidence: the runner records a matched `allowedHttpResponses` entry as `expected-http-response` at informational severity. If Chromium emits a matching generic console error, allowlist its narrowest text with `allowedConsoleMessageSubstrings`; that match is a global substring, so it also downgrades the same message from any other request → review every remaining 4xx warning in the run report as unexpected. Never use broad status-only suppression; unmatched 4xx responses remain warnings and unmatched 5xx responses remain errors.

Use `textFromEnv` only for a browser-masked password field. A visible field must reject environment text unless `allowVisibleEnvText: true` explicitly marks known non-sensitive fixture copy. Never expose credentials, tokens, customer data, or private payloads in a visible field.

## Phase 4: start and verify the application

Use an existing repository command. Do not modify product code merely to make the recorder pass.

Confirm:

- the base URL returns successfully;
- the configured ready selector becomes visible;
- required local APIs respond;
- the safe fixture is reset;
- no unrelated process owns the expected port.

## Phase 5: record a numbered attempt

Never overwrite a prior attempt.

```bash
node scripts/run-walkthrough.mjs \
  --config /absolute/path/to/repository/.walkthrough/walkthrough.config.json \
  --output-dir /absolute/path/to/repository/.walkthrough/artifacts-attempt-01
```

The recorder must produce:

- `<name>.webm`;
- `<name>-run-report.json`;
- `<name>-timeline.json`;
- `<name>-opening.png`;
- one PNG under `step-checkpoints/` for every step.

The complete run report must include the current skill package name and version. Source review, conversion, and derived MP4 review must preserve that provenance through the run-report hash.

Reject the attempt immediately if the run report is not `passed`, contains an error finding, contains a sensitive finding, or lacks a checkpoint.

## Phase 6: run the unapproved mechanical review

```bash
node scripts/review-video.mjs \
  --video /path/to/artifacts-attempt-01/feature-walkthrough.webm \
  --timeline /path/to/artifacts-attempt-01/feature-walkthrough-run-report.json \
  --output-dir /path/to/artifacts-attempt-01/video-review \
  --report /path/to/artifacts-attempt-01/video-review.json
```

Exit code `2` with `status: "review-required"` means automated checks passed but visual review + approval remain; it is not completion. Any `failed` status requires root-cause repair and another attempt.

The reviewer enforces (pointer-specific checks apply when enabled):

- complete decode;
- monotonic frame timestamps;
- no blank opening and no single near-white or near-black frame;
- stable opening hold;
- persistent pointer around its expected recorded trajectory;
- pointer activation inside the recorded target box and focused keyboard activation with a complete key cue;
- no visible pointer during keyboard activation and no page change with conflicting input evidence;
- no blank, partially styled, or pointerless frame around reloads and full navigations;
- gradual motion across each scroll window, with locator-targeted no-op scrolls rejected;
- gradual locator-bound motion and pointer continuity across each drag window;
- no failed journey step;
- readable holds;
- all checkpoints present;
- a 10fps action sequence for every journey step;
- source-video SHA-256.

## Phase 7: inspect the complete attempt

Do all of the following:

1. Play the WebM from frame one to the end at 1x.
2. Inspect `opening-review-10fps.jpg`.
3. Inspect every `contact-sheet-*.jpg`.
4. Inspect every image under `action-review-10fps/`.
5. Inspect every image under `step-checkpoints/`.
6. Compare every state-changing action with the visible response.
7. Compare the visible journey with the requested start and end states.

Specifically reject:

- any first-frame flash, refresh, blank paint, font swap, layout jump, or duplicated opening;
- pointer disappearance, reset, style change, teleport, duplicate pointer, or inconsistent click cue;
- abrupt, bouncing, reversed, repeated, or unexplained scrolling;
- a click without a visible result;
- a state change without an action or expected response;
- a page change while the pointer remains on another control and the claimed keyboard focus or cue is missing;
- a hidden future stage appearing before its gate;
- a loader that vanishes too quickly to explain waiting;
- a state that is held too briefly to read;
- an unexplained overlay, popup, download, dialog, external page, or broken asset;
- a final frame that does not prove the requested outcome.

Contact sheets do not replace sequential playback. A clean report does not override a visible defect.

## Phase 8: repair and rerun

When anything fails:

1. Identify whether the cause is readiness, locator choice, pointer pacing, scroll timing, fixture state, application state, or journey design.
2. Fix the root cause within task authorization. If the fix requires unavailable access or an unresolved decision, report the exact blocker; do not approve the attempt.
3. Record to `artifacts-attempt-02` or the next unused number.
4. Run the complete mechanical review again.
5. Repeat the full visual review.

Do not approve an attempt and then patch the video. The accepted video must come from a clean real journey.

Continue until both the automated report and complete visual review are clean. Product defects also require E2E's original-case + affected-case regression proof; a cleaner recording alone does not close them.

## Phase 9: approve the accepted WebM

```bash
node scripts/review-video.mjs \
  --video /path/to/accepted/feature-walkthrough.webm \
  --timeline /path/to/accepted/feature-walkthrough-run-report.json \
  --output-dir /path/to/accepted/video-review \
  --report /path/to/accepted/video-review.json \
  --approve \
  --reviewer "Claude" \
  --notes "Watched the complete video at 1x and inspected the opening sheet, all contact sheets, every checkpoint, all navigations, pointer continuity, and smooth scrolls."
```

Approval must name the reviewer and state what was inspected. Never copy approval from another attempt.

The approval command must itself play the exact current file from zero through `ended` in Chromium at 1x. It rejects pauses, buffering stalls, seeking, playback-rate changes, non-monotonic media time, sampling gaps, wall-clock drift, early completion, and media errors. It binds schema-v2 `playbackEvidence` to the video hash, dimensions, duration, and complete run-report SHA-256. The command therefore takes approximately the video's full duration; approval notes alone can never satisfy this gate.

## Phase 10: convert through the hash gate

```bash
node scripts/convert-mp4.mjs \
  --input /path/to/accepted/feature-walkthrough.webm \
  --review /path/to/accepted/video-review.json \
  --output /absolute/path/to/Downloads/feature-walkthrough.mp4
```

Conversion must fail when the WebM hash differs from the approved report, the report lacks passed schema-v2 playback evidence, the proof does not match the video metadata, or the review is not bound to a complete run-report hash. The converter must produce a delivery manifest and validate H.264, yuv420p, dimensions, duration, full decode, and fast-start delivery settings.

## Phase 11: review the final MP4

Run the reviewer against the MP4 with a distinct output directory and report. Bind it to the accepted source review:

```bash
node scripts/review-video.mjs \
  --video /absolute/path/to/Downloads/feature-walkthrough.mp4 \
  --timeline /path/to/accepted/feature-walkthrough-run-report.json \
  --derived-from /path/to/accepted/video-review.json \
  --output-dir /absolute/path/to/Downloads/feature-walkthrough-mp4-review \
  --report /absolute/path/to/Downloads/feature-walkthrough-mp4-review.json
```

Repeat the complete 1x playback and visual inspection, inspect the MP4's generated sheets, then rerun with `--approve`, `--reviewer`, and descriptive `--notes`. This produces a separate MP4 playback proof; source evidence cannot be reused. The derived review must use the same complete run report as the source approval. Never reuse the WebM report path for the MP4.

Open the delivered MP4 through a fresh preview URL with a new cache-busting query or a new browser panel. Verify the displayed duration and first frame match the current file.

Do not rely on a previously opened preview.

## Completion gate

Recorded E2E requires conditions 1–7 on the accepted WebM, plus E2E's product assertions and durable-state proof. Video delivery requires all ten conditions on the source and exact delivered MP4. Do not report completion with a failed or review-required report.

1. The accepted run report is `passed`.
2. No runtime, safety, network, or sensitive-data error exists.
3. Recording began after the real opening state was ready.
4. Every frame decoded with monotonic timestamps.
5. Opening stability, input evidence, smooth-scroll, pacing, blank-frame and journey checks passed, plus pointer continuity when enabled.
6. Every step checkpoint exists and was inspected.
7. The complete WebM was watched and approved with passed, hash-bound real-time playback evidence.
8. The MP4 was generated from the exact approved WebM hash.
9. The complete MP4 was watched and approved separately with its own passed playback evidence.
10. A fresh preview displays that exact MP4.

User-reported defects follow [E2E's reopening rule](../e2e/SKILL.md#prove-the-journey); the affected media approval is invalid and the corrected journey needs a new attempt.

## Important configuration

```json
{
  "strictE2E": true,
  "readySelector": "[data-testid='app-ready']",
  "allowedHttpResponses": [
    { "status": 400, "urlIncludes": "/AuthService/SignIn" }
  ],
  "reducedMotion": "reduce",
  "videoQuality": 90,
  "visualStabilityMs": 300,
  "scrollDurationMs": 900,
  "dragDurationMs": 900,
  "captureStepScreenshots": true,
  "pointer": {
    "enabled": true,
    "color": "#ff3b30",
    "size": 20,
    "rippleSize": 38,
    "rippleMs": 520,
    "moveDurationMs": 900,
    "moveHoldMs": 320
  },
  "stepHoldMs": 1400,
  "minReadableHoldMs": 1200,
  "pointerMissingFailMs": 160,
  "openingStableMs": 800
}
```

Negative-path `allowedHttpResponses` follow [Phase 3](#phase-3-establish-safety-boundaries); `"pointer": false` follows [Recorded E2E](#recorded-e2e).

`reducedMotion: "reduce"` asks the application to honor `prefers-reduced-motion`; it does not rewrite application behavior. Keep meaningful product loaders and state changes. Remove decorative motion in the application or a safe recording fixture rather than masking real behavior in post-production.


Supported actions:

| Action | Purpose |
| --- | --- |
| `goto` | Open a path or URL |
| `click` | Move visibly, check actionability, then click a locator |
| `drag` | Drag between stable locator-relative points with paced real mouse input |
| `type` | Focus, clear, and type with `pressSequentially` |
| `typeKeys` | Type paced text into the currently focused keyboard-driven surface |
| `select` | Select a native option |
| `press` | Focus a stable target, hide the pointer, show the key cue, then press; use explicit global scope only for a real global shortcut |
| `hover` | Move the real pointer over a locator |
| `scroll` | Perform a timed smooth wheel scroll or reveal a target smoothly |
| `waitForSelector` / `waitForText` / `waitForUrl` | Wait for explicit application readiness |
| `assertVisible` / `assertText` / `assertUrl` | Prove journey outcomes |
| `pause` | Presentation hold only |
| `screenshot` | Capture an extra named state |
| `reload` / `back` / `forward` | Exercise browser navigation |
