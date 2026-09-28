import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

const skillRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const runner = path.join(skillRoot, 'scripts', 'run-walkthrough.mjs');
const reviewer = path.join(skillRoot, 'scripts', 'review-video.mjs');
const require = createRequire(path.join(skillRoot, 'package.json'));

function preflightError(message) {
  console.error(`gesture-smoke preflight: ${message}`);
  process.exit(1);
}

let chromiumExecutable = '';
try {
  chromiumExecutable = require('playwright').chromium.executablePath();
} catch {
  preflightError('playwright is not installed; run pnpm install --frozen-lockfile --ignore-scripts from this package directory');
}
if (!existsSync(chromiumExecutable)) {
  preflightError('Chromium is not installed; run pnpm exec playwright install chromium from this package directory');
}
for (const tool of ['ffmpeg', 'ffprobe']) {
  const probe = spawnSync(tool, ['-version'], { stdio: 'ignore' });
  if (probe.error || probe.status !== 0) {
    preflightError(`${tool} is not installed; run: sudo apt-get install -y ffmpeg (Linux) or brew install ffmpeg (macOS)`);
  }
}

const slowCapture = process.env.WALKTHROUGH_SMOKE_PROFILE === 'slow-capture';
const captureSpeedKinds = new Set(['long-static-run', 'non-smooth-gesture']);
const cleanReviewCodes = slowCapture ? [1, 2] : [2];
const cleanReviewStatuses = slowCapture ? ['review-required', 'failed'] : ['review-required'];
if (slowCapture) {
  console.error(
    'gesture-smoke: WALKTHROUGH_SMOKE_PROFILE=slow-capture — tolerating capture-speed findings (long-static-run, non-smooth-gesture); full motion assertions require hardware that sustains real-time recording',
  );
}

function unexpectedFindings(report) {
  return report.findings.filter((finding) => !(slowCapture && captureSpeedKinds.has(finding.kind)));
}

const workspace = await mkdtemp(path.join(tmpdir(), 'walkthrough-gesture-'));
let succeeded = false;

function fixtureHtml(delayedReload = false) {
  return `<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gesture fixture</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f5f1e8; color: #201f1c; font: 18px system-ui, sans-serif; }
  body[data-delayed-reload] main { visibility: hidden; }
  body[data-restored] main { background: #edf7ef; }
  main { width: 720px; padding: 40px; background: white; border: 1px solid #d8d1c3; }
  button { margin-bottom: 20px; padding: 10px 16px; font: inherit; }
  [data-gesture-surface] { position: relative; width: 640px; height: 280px; border: 2px solid #70695f; background: #faf8f3; overflow: hidden; touch-action: none; }
  .marker { position: absolute; width: 28px; height: 28px; border-radius: 50%; background: #315c8c; transform: translate(-50%, -50%); left: 20%; top: 50%; }
  output { display: block; min-height: 1.5em; margin-top: 20px; }
</style>
<body${delayedReload ? ' data-delayed-reload="true" data-restored="true"' : ''}>
<main${delayedReload ? '' : ' data-ready="true"'}>
  <h1>Gesture fixture</h1>
  <button id="open-panel" type="button">Open panel</button>
  <div data-gesture-surface role="application" aria-label="Gesture surface" tabindex="0">
    <div class="marker" aria-hidden="true"${delayedReload ? ' style="left:80%;top:50%"' : ''}></div>
  </div>
  <output id="status" aria-live="polite">${delayedReload ? 'Typed EXC' : 'Waiting for drag'}</output>
</main>
<script>
  const surface = document.querySelector("[data-gesture-surface]");
  const marker = document.querySelector(".marker");
  const status = document.querySelector("#status");
  const openPanel = document.querySelector("#open-panel");
  let start = null;
  ${delayedReload ? 'surface.dataset.typed = "EXC";' : ''}
  surface.addEventListener("pointerdown", (event) => {
    start = { x: event.clientX, y: event.clientY };
    surface.setPointerCapture(event.pointerId);
  });
  surface.addEventListener("pointermove", (event) => {
    if (!start) return;
    const bounds = surface.getBoundingClientRect();
    marker.style.left = (event.clientX - bounds.left) + "px";
    marker.style.top = (event.clientY - bounds.top) + "px";
  });
  surface.addEventListener("pointerup", (event) => {
    if (!start) return;
    const distance = Math.round(Math.hypot(event.clientX - start.x, event.clientY - start.y));
    start = null;
    surface.dataset.dragged = "true";
    status.textContent = "Dragged " + distance + " pixels";
  });
  surface.addEventListener("click", (event) => {
    if (!event.shiftKey) return;
    fetch("/expected-conflict").then(() => {
      surface.dataset.shiftClicked = "true";
      status.textContent = "Shift clicked";
    });
    surface.addEventListener("keydown", (event) => {
      if (event.key.length !== 1) return;
      surface.dataset.typed = (surface.dataset.typed || "") + event.key;
      status.textContent = "Typed " + surface.dataset.typed;
    });
  });
  openPanel.addEventListener("click", () => {
    history.pushState({}, "", "/panel");
    document.body.dataset.panelOpen = "true";
    status.textContent = "Panel opened";
  });
  ${delayedReload ? 'window.setTimeout(() => { document.body.removeAttribute("data-delayed-reload"); document.querySelector("main").dataset.ready = "true"; }, 700);' : ''}
</script>
</body>
</html>`;
}

let documentLoads = 0;
const server = createServer((request, response) => {
  if (request.url === '/expected-conflict') {
    response.writeHead(409, {
      'cache-control': 'no-store',
      'content-type': 'application/json',
    });
    response.end('{"expected":true}');
    return;
  }
  response.writeHead(200, {
    'cache-control': 'no-store',
    'content-type': request.url === '/favicon.ico' ? 'image/x-icon' : 'text/html; charset=utf-8',
  });
  if (request.url === '/favicon.ico') {
    response.end('');
    return;
  }
  documentLoads += 1;
  response.end(fixtureHtml(documentLoads > 1));
});

function runNode(script, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [script, ...args], {
      cwd: skillRoot,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const stdout = [];
    const stderr = [];
    child.stdout.on('data', (chunk) => stdout.push(chunk));
    child.stderr.on('data', (chunk) => stderr.push(chunk));
    child.on('error', reject);
    child.on('close', (code) =>
      resolve({
        code,
        stdout: Buffer.concat(stdout).toString('utf8'),
        stderr: Buffer.concat(stderr).toString('utf8'),
      }),
    );
  });
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

try {
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  const baseUrl = `http://127.0.0.1:${address.port}/`;
  const outputDir = path.join(workspace, 'artifacts-attempt-01');
  const reviewDir = path.join(outputDir, 'video-review');
  const noOpReviewDir = path.join(outputDir, 'no-op-review');
  const ambiguousReviewDir = path.join(outputDir, 'ambiguous-keyboard-review');
  const configPath = path.join(workspace, 'walkthrough.config.json');
  const unsafeConfigPath = path.join(workspace, 'unsafe-walkthrough.config.json');
  const invalidStepConfigPath = path.join(workspace, 'invalid-step-walkthrough.config.json');
  const reportPath = path.join(outputDir, 'gesture-smoke-run-report.json');
  const reviewPath = path.join(outputDir, 'gesture-smoke-review.json');
  const noOpReportPath = path.join(outputDir, 'gesture-smoke-no-op-run-report.json');
  const noOpReviewPath = path.join(outputDir, 'gesture-smoke-no-op-review.json');
  const ambiguousReportPath = path.join(outputDir, 'gesture-smoke-ambiguous-run-report.json');
  const ambiguousReviewPath = path.join(outputDir, 'gesture-smoke-ambiguous-review.json');
  const config = {
    name: 'gesture-smoke',
    repository: 'synthetic-gesture-fixture',
    baseUrl,
    strictE2E: true,
    readySelector: "[data-ready='true']",
    allowedOrigins: [new URL(baseUrl).origin],
    allowedHttpResponses: [{ status: 409, urlIncludes: '/expected-conflict' }],
    allowedConsoleMessageSubstrings: ['Failed to load resource: the server responded with a status of 409'],
    blockExternalRequests: true,
    viewport: { width: 900, height: 700 },
    visualStabilityMs: 200,
    stepHoldMs: 900,
    openingHoldMs: 900,
    finalHoldMs: 900,
    minReadableHoldMs: 800,
    openingStableMs: 700,
    pointer: {
      enabled: true,
      color: '#ff3b30',
      size: 20,
      moveDurationMs: 700,
      moveHoldMs: 200,
    },
    steps: [
      {
        action: 'goto',
        label: 'Open the ready gesture fixture',
        url: '/',
        holdMs: 900,
      },
      {
        action: 'drag',
        label: 'Drag across the interaction surface',
        target: { selector: '[data-gesture-surface]' },
        from: { xRatio: 0.2, yRatio: 0.5 },
        to: { xRatio: 0.8, yRatio: 0.5 },
        durationMs: 900,
        readySelector: "[data-dragged='true']",
        holdMs: 900,
      },
      {
        action: 'assertText',
        label: 'Prove the drag result',
        target: { selector: '#status' },
        text: 'Dragged',
        holdMs: 900,
      },
      {
        action: 'click',
        label: 'Shift click a relative canvas point',
        target: { selector: '[data-gesture-surface]' },
        position: { xRatio: 0.35, yRatio: 0.35 },
        modifiers: ['Shift'],
        readySelector: "[data-shift-clicked='true']",
        holdMs: 900,
      },
      {
        action: 'assertText',
        label: 'Prove the modified click result',
        target: { selector: '#status' },
        text: 'Shift clicked',
        holdMs: 900,
      },
      {
        action: 'typeKeys',
        label: 'Type into the keyboard-driven surface',
        text: 'EXC',
        typeDelayMs: 120,
        readySelector: "[data-typed='EXC']",
        holdMs: 900,
      },
      {
        action: 'assertText',
        label: 'Prove the keyboard input result',
        target: { selector: '#status' },
        text: 'Typed EXC',
        holdMs: 900,
      },
      {
        action: 'press',
        label: 'Open the panel with the keyboard',
        target: { selector: '#open-panel' },
        key: 'Enter',
        readySelector: "body[data-panel-open='true']",
        holdMs: 900,
      },
      {
        action: 'assertText',
        label: 'Prove the keyboard activation result',
        target: { selector: '#status' },
        text: 'Panel opened',
        holdMs: 900,
      },
      {
        action: 'reload',
        label: 'Reload the delayed fixture without a visual flash',
        preserveVisualDuringReload: true,
        visualGuardLeadMs: 500,
        visualGuardSettleMs: 160,
        holdMs: 900,
      },
      {
        action: 'assertText',
        label: 'Prove the restored keyboard state',
        target: { selector: '#status' },
        text: 'Typed EXC',
        holdMs: 900,
      },
    ],
  };
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`, 'utf8');
  await writeFile(unsafeConfigPath, `${JSON.stringify({ ...config, blockExternalRequests: false }, null, 2)}\n`, 'utf8');
  const unsafeRun = await runNode(runner, ['--config', unsafeConfigPath, '--output-dir', path.join(workspace, 'unsafe-artifacts')]);
  assert(unsafeRun.code === 1, `Unsafe strict config exited ${unsafeRun.code}`);
  assert(
    `${unsafeRun.stdout}\n${unsafeRun.stderr}`.includes('strictE2E requires blockExternalRequests: true'),
    'Strict preflight did not reject open external network access',
  );
  const invalidStepConfig = structuredClone(config);
  invalidStepConfig.steps[0].preserveVisualDuringReload = true;
  const typeKeysIndex = invalidStepConfig.steps.findIndex((step) => step.action === 'typeKeys');
  const pressIndex = invalidStepConfig.steps.findIndex((step) => step.action === 'press');
  delete invalidStepConfig.steps[typeKeysIndex].text;
  delete invalidStepConfig.steps[pressIndex].target;
  await writeFile(invalidStepConfigPath, `${JSON.stringify(invalidStepConfig, null, 2)}\n`, 'utf8');
  const invalidStepRun = await runNode(runner, [
    '--config',
    invalidStepConfigPath,
    '--output-dir',
    path.join(workspace, 'invalid-step-artifacts'),
  ]);
  const invalidStepOutput = `${invalidStepRun.stdout}\n${invalidStepRun.stderr}`;
  assert(invalidStepRun.code === 1, `Invalid strict steps exited ${invalidStepRun.code}`);
  assert(
    invalidStepOutput.includes('preserveVisualDuringReload is only valid for reload steps'),
    'Strict preflight did not reject a reload guard on another action',
  );
  assert(invalidStepOutput.includes('typeKeys needs text or textFromEnv'), 'Strict preflight did not reject an empty typeKeys action');
  assert(
    invalidStepOutput.includes('press needs a stable target or scope "global"'),
    'Strict preflight did not reject an untargeted keyboard action',
  );

  const run = await runNode(runner, ['--config', configPath, '--output-dir', outputDir]);
  assert(run.code === 0, `Gesture runner failed:\n${run.stderr || run.stdout}`);
  const report = JSON.parse(await readFile(reportPath, 'utf8'));
  const drag = report.timeline.find((step) => step.action === 'drag');
  const keyboardPress = report.timeline.find((step) => step.action === 'press');
  assert(report.status === 'passed', `Gesture run status was ${report.status}`);
  assert(report.skill?.version === '2.8.0', `Unexpected skill version ${report.skill?.version}`);
  assert(
    report.timeline.some((step) => step.action === 'typeKeys' && step.metadata?.charactersTyped === 3),
    'Keyboard-driven text step was not recorded',
  );
  assert(
    report.timeline.some(
      (step) => step.action === 'reload' && step.metadata?.visualContinuityGuard?.kind === 'document-start-snapshot-bridge',
    ),
    'Reload continuity guard was not recorded',
  );
  assert(
    report.findings.some((finding) => finding.kind === 'expected-http-response' && finding.severity === 'info'),
    'Expected HTTP response was not recorded as informational evidence',
  );
  assert(drag?.ok === true, 'Drag step did not pass');
  assert(drag.metadata?.distancePx > 300, 'Drag distance was not recorded');
  assert(drag.metadata?.dragDurationMs >= 850, 'Drag duration was not paced');
  assert(
    report.pointerTrack.some((event) => event.kind === 'move' && event.pressed === true),
    'Pressed pointer movement was not recorded',
  );
  assert(
    keyboardPress?.metadata?.inputEvents?.[0]?.inputType === 'keyboard' &&
      keyboardPress.beforeUrl !== keyboardPress.afterUrl &&
      keyboardPress.metadata.inputEvents[0].focusConfirmed === true &&
      keyboardPress.metadata.inputEvents[0].pointerVisibleAtActivation === false &&
      keyboardPress.metadata.inputEvents[0].cue?.kind === 'keyboard',
    'Keyboard activation evidence was not recorded',
  );
  assert(
    report.pointerTrack.some((event) => event.kind === 'visibility' && event.visible === false) &&
      report.pointerTrack.some((event) => event.kind === 'visibility' && event.visible === true),
    'Keyboard cue did not hide and restore the pointer',
  );

  const review = await runNode(reviewer, [
    '--video',
    path.join(outputDir, 'gesture-smoke.webm'),
    '--timeline',
    reportPath,
    '--output-dir',
    reviewDir,
    '--report',
    reviewPath,
  ]);
  assert(cleanReviewCodes.includes(review.code), `Unapproved gesture review exited ${review.code}:\n${review.stderr || review.stdout}`);
  const reviewReport = JSON.parse(await readFile(reviewPath, 'utf8'));
  assert(cleanReviewStatuses.includes(reviewReport.status), `Unexpected review status ${reviewReport.status}`);
  assert(reviewReport.skill?.version === report.skill.version, 'Review did not preserve skill provenance');
  assert(reviewReport.reviewerSkill?.version === report.skill.version, 'Review tool version was not recorded');
  assert(
    unexpectedFindings(reviewReport).length === 0,
    `Gesture review found defects: ${JSON.stringify(unexpectedFindings(reviewReport))}`,
  );
  assert(reviewReport.gestureAudits?.length === 1, 'Gesture audit was not generated');
  if (slowCapture) {
    assert(reviewReport.gestureAudits[0].pressedMoveSegments > 0, 'Gesture audit lost the pressed pointer track');
  } else {
    assert(reviewReport.gestureAudits[0].smooth === true, 'Gesture audit did not pass');
  }
  assert(reviewReport.navigationAudits?.length === 1, 'Reload navigation audit was not generated');
  assert(
    reviewReport.inputAudits?.some((audit) => audit.step === keyboardPress.index && audit.passed === true),
    'Review did not pass the focused keyboard activation evidence',
  );
  assert(reviewReport.navigationAudits[0].clean === true, 'Guarded reload navigation audit did not pass');
  assert(
    reviewReport.navigationAudits[0].preNavigationMs === 80,
    'Guarded reload audit did not inspect the compositor handoff before navigation',
  );

  const ambiguousReport = structuredClone(report);
  const ambiguousPress = ambiguousReport.timeline.find((step) => step.action === 'press');
  ambiguousPress.metadata.inputEvents[0].pointerVisibleAtActivation = true;
  ambiguousPress.metadata.inputEvents[0].pointerPositionAtActivation = { x: 30, y: 30 };
  await writeFile(ambiguousReportPath, `${JSON.stringify(ambiguousReport, null, 2)}\n`, 'utf8');
  const ambiguousReview = await runNode(reviewer, [
    '--video',
    path.join(outputDir, 'gesture-smoke.webm'),
    '--timeline',
    ambiguousReportPath,
    '--output-dir',
    ambiguousReviewDir,
    '--report',
    ambiguousReviewPath,
  ]);
  assert(
    ambiguousReview.code === 1,
    `Ambiguous keyboard review exited ${ambiguousReview.code}:\n${ambiguousReview.stderr || ambiguousReview.stdout}`,
  );
  const ambiguousReviewReport = JSON.parse(await readFile(ambiguousReviewPath, 'utf8'));
  assert(
    ambiguousReviewReport.status === 'failed' &&
      ambiguousReviewReport.findings.some((finding) => finding.kind === 'ambiguous-keyboard-activation'),
    'Full review did not reject a page change while the pointer remained on another control',
  );

  const noOpReport = structuredClone(report);
  noOpReport.timeline[2] = {
    ...noOpReport.timeline[2],
    action: 'scroll',
    label: 'Reject a no-op target scroll',
    actionEndMs: noOpReport.timeline[2].startMs + 900,
    actionDurationMs: 900,
    metadata: {
      smoothTargetScroll: true,
      smoothScrollDurationMs: 0,
      scrollDistancePx: 0,
    },
  };
  await writeFile(noOpReportPath, `${JSON.stringify(noOpReport, null, 2)}\n`, 'utf8');
  const noOpReview = await runNode(reviewer, [
    '--video',
    path.join(outputDir, 'gesture-smoke.webm'),
    '--timeline',
    noOpReportPath,
    '--output-dir',
    noOpReviewDir,
    '--report',
    noOpReviewPath,
  ]);
  assert(noOpReview.code === 1, `No-op review exited ${noOpReview.code}:\n${noOpReview.stderr || noOpReview.stdout}`);
  const noOpReviewReport = JSON.parse(await readFile(noOpReviewPath, 'utf8'));
  assert(noOpReviewReport.status === 'failed', `No-op review status was ${noOpReviewReport.status}`);
  assert(
    noOpReviewReport.findings.some((finding) => finding.kind === 'scroll-no-op'),
    'No-op target scroll was not rejected',
  );
  documentLoads = 0;
  const proofDir = path.join(workspace, 'proof-artifacts-attempt-01');
  const proofConfigPath = path.join(workspace, 'proof-walkthrough.config.json');
  const proofReportPath = path.join(proofDir, 'gesture-smoke-proof-run-report.json');
  const proofReviewPath = path.join(proofDir, 'gesture-smoke-proof-review.json');
  const proofConfig = {
    ...config,
    name: 'gesture-smoke-proof',
    pointer: false,
    steps: [
      {
        action: 'goto',
        label: 'Open the ready gesture fixture',
        url: '/',
        holdMs: 900,
      },
      {
        action: 'click',
        label: 'Shift click a relative canvas point',
        target: { selector: '[data-gesture-surface]' },
        position: { xRatio: 0.35, yRatio: 0.35 },
        modifiers: ['Shift'],
        readySelector: "[data-shift-clicked='true']",
        holdMs: 900,
      },
      {
        action: 'assertText',
        label: 'Prove the modified click result',
        target: { selector: '#status' },
        text: 'Shift clicked',
        holdMs: 900,
      },
    ],
  };
  await writeFile(proofConfigPath, `${JSON.stringify(proofConfig, null, 2)}\n`, 'utf8');
  const proofRun = await runNode(runner, ['--config', proofConfigPath, '--output-dir', proofDir]);
  assert(proofRun.code === 0, `Proof-mode runner failed:\n${proofRun.stderr || proofRun.stdout}`);
  const proofReport = JSON.parse(await readFile(proofReportPath, 'utf8'));
  assert(proofReport.status === 'passed', `Proof-mode run status was ${proofReport.status}`);
  assert(proofReport.pointer?.enabled === false, 'Proof-mode run did not record the disabled pointer');
  const proofReview = await runNode(reviewer, [
    '--video',
    path.join(proofDir, 'gesture-smoke-proof.webm'),
    '--timeline',
    proofReportPath,
    '--output-dir',
    path.join(proofDir, 'video-review'),
    '--report',
    proofReviewPath,
  ]);
  assert(
    cleanReviewCodes.includes(proofReview.code),
    `Proof-mode review exited ${proofReview.code}:\n${proofReview.stderr || proofReview.stdout}`,
  );
  const proofReviewReport = JSON.parse(await readFile(proofReviewPath, 'utf8'));
  assert(cleanReviewStatuses.includes(proofReviewReport.status), `Proof-mode review status was ${proofReviewReport.status}`);
  assert(
    unexpectedFindings(proofReviewReport).length === 0,
    `Proof-mode review found defects: ${JSON.stringify(unexpectedFindings(proofReviewReport))}`,
  );

  succeeded = true;
  console.log(
    JSON.stringify(
      {
        status: 'passed',
        motionAssertions: slowCapture ? 'slow-capture' : 'full',
        dragDurationMs: drag.metadata.dragDurationMs,
        distancePx: drag.metadata.distancePx,
        gestureAudit: reviewReport.gestureAudits[0],
      },
      null,
      2,
    ),
  );
} finally {
  await new Promise((resolve) => server.close(resolve));
  if (succeeded || process.env.KEEP_WALKTHROUGH_TEST_ARTIFACTS !== '1') {
    await rm(workspace, { recursive: true, force: true });
  } else {
    console.error(`Gesture test artifacts retained at ${workspace}`);
  }
}
