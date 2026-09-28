import { access, mkdir, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import {
  findSensitive,
  finiteNumber,
  includesAllowedSubstring,
  isAllowedHttpResponse,
  parseArgs,
  redactedMessage,
  resolveUrl,
  safeSlug,
  safeUrl,
  validateConfig,
} from './walkthrough-config.mjs';
import { installNavigationBridge, navigationBridgeHostId, navigationBridgeStorageKey, WalkthroughPointer } from './walkthrough-pointer.mjs';
import { runStep, waitForReady } from './walkthrough-steps.mjs';

const skillRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(skillRoot, 'package.json'));
const { chromium } = require('playwright');
const skillPackage = require(path.join(skillRoot, 'package.json'));

async function run() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.config || args.config === true) throw new Error('Usage: run-walkthrough.mjs --config /path/walkthrough.config.json');
  const configPath = path.resolve(String(args.config));
  const config = JSON.parse(await readFile(configPath, 'utf8'));
  const configDir = path.dirname(configPath);
  const outputDir = path.resolve(String(args['output-dir'] || config.outputDir || path.join(configDir, 'artifacts')));
  const name = safeSlug(config.name);
  const baseUrl = String(args['base-url'] || config.baseUrl || '');
  const configProblems = validateConfig(config, baseUrl);
  if (configProblems.length > 0) throw new Error(`Walkthrough config failed preflight:\n- ${configProblems.join('\n- ')}`);
  config.baseUrl = baseUrl;
  const plannedVideoPath = path.join(outputDir, `${name}.webm`);
  try {
    await access(plannedVideoPath);
    throw new Error(`Refusing to overwrite an existing attempt: ${plannedVideoPath}`);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  await mkdir(outputDir, { recursive: true });
  const checkpointDir = path.join(outputDir, 'step-checkpoints');
  if (config.captureStepScreenshots !== false) await mkdir(checkpointDir, { recursive: true });

  const findings = [];
  const sensitiveFindings = [];
  const timeline = [];
  const recordFinding = (kind, detail, severity = 'error') => {
    findings.push({
      kind,
      detail: redactedMessage(detail),
      severity,
      recordedAt: new Date().toISOString(),
    });
  };
  const recordSensitive = (location, types) => {
    for (const type of types) {
      const key = `${location}:${type}`;
      if (!sensitiveFindings.some((item) => item.key === key)) sensitiveFindings.push({ key, location, type });
    }
  };

  const allowedOrigins = new Set([new URL(baseUrl).origin, ...(config.allowedOrigins || []).map((value) => new URL(value).origin)]);
  const viewport = config.viewport || { width: 1440, height: 1000 };
  const pointerSource = config.pointer === false ? { enabled: false } : config.pointer || {};
  const color = /^#[0-9a-f]{6}$/i.test(String(pointerSource.color || '')) ? String(pointerSource.color) : '#ff3b30';
  const pointerConfig = {
    enabled: pointerSource.enabled !== false,
    color,
    size: finiteNumber(pointerSource.size, 20, 8, 64),
    rippleSize: finiteNumber(pointerSource.rippleSize, 38, 16, 120),
    rippleMs: finiteNumber(pointerSource.rippleMs, 520, 120, 2000),
    moveDurationMs: finiteNumber(pointerSource.moveDurationMs, 900, 0, 5000),
    moveHoldMs: finiteNumber(pointerSource.moveHoldMs, 320, 0, 3000),
    startX: finiteNumber(pointerSource.startX, Math.max(30, Math.round(viewport.width * 0.08)), 0, viewport.width),
    startY: finiteNumber(pointerSource.startY, Math.max(30, Math.round(viewport.height * 0.08)), 0, viewport.height),
    implementation: 'playwright-screencast-overlay',
  };

  const executablePath = config.executablePath || process.env.PLAYWRIGHT_EXECUTABLE_PATH || undefined;
  const browser = await chromium.launch({ headless: !args.headed, executablePath });
  let context;
  let page;
  let pointer;
  let runError;
  let screencastStarted = false;
  let recordingStartedAt;
  let journeyEndMs = 0;
  const finalHoldMs = finiteNumber(config.finalHoldMs, 2000);
  const videoPath = plannedVideoPath;
  const openingFramePath = path.join(outputDir, `${name}-opening.png`);
  const captureCheckpoint = async (index, step) => {
    if (config.captureStepScreenshots === false) return null;
    const filename = `${String(index + 1).padStart(3, '0')}-${safeSlug(step.label || step.action)}.png`;
    await page.screenshot({ path: path.join(checkpointDir, filename), animations: 'disabled' });
    return filename;
  };
  let lastCheckpointPath = null;

  try {
    context = await browser.newContext({
      viewport,
      colorScheme: config.colorScheme || 'light',
      reducedMotion: config.reducedMotion || 'reduce',
      serviceWorkers: 'block',
      permissions: [],
      acceptDownloads: false,
      storageState: config.storageState ? path.resolve(configDir, config.storageState) : undefined,
    });
    await context.addInitScript(installNavigationBridge, {
      storageKey: navigationBridgeStorageKey,
      hostId: navigationBridgeHostId,
    });
    await context.route('**/*', async (route) => {
      const request = route.request();
      const url = request.url();
      if (config.blockEventStreams && request.resourceType() === 'eventsource') {
        recordFinding('event-stream-blocked', safeUrl(url), 'info');
        await route.abort();
        return;
      }
      if (/^https?:/i.test(url)) {
        const origin = new URL(url).origin;
        const sensitiveInRequest = findSensitive(`${url}\n${request.postData() || ''}`);
        if (sensitiveInRequest.length > 0) recordSensitive('request metadata', sensitiveInRequest);
        if (!allowedOrigins.has(origin)) {
          recordFinding('external-request', safeUrl(url), config.blockExternalRequests === false ? 'warning' : 'error');
          if (config.blockExternalRequests !== false) {
            await route.abort();
            return;
          }
        }
      }
      await route.continue();
    });

    page = await context.newPage();
    context.on('page', async (childPage) => {
      if (childPage === page) return;
      recordFinding('unexpected-popup', safeUrl(childPage.url()), 'error');
      await childPage.close();
    });
    page.on('download', async (download) => {
      recordFinding('download-triggered', path.extname(download.suggestedFilename()) || '[unknown extension]', 'error');
      await download.cancel();
    });
    page.on('filechooser', () => recordFinding('file-chooser', 'A file chooser was opened', 'error'));
    page.on('dialog', async (dialog) => {
      recordFinding('dialog', dialog.type(), 'error');
      await dialog.dismiss();
    });
    page.on('console', (message) => {
      if (message.type() !== 'error' && message.type() !== 'warning') return;
      const text = message.text();
      const sensitive = findSensitive(text);
      if (sensitive.length > 0) recordSensitive('console message', sensitive);
      const allowed = includesAllowedSubstring(text, config.allowedConsoleMessageSubstrings);
      const severity = allowed ? 'info' : message.type() === 'error' ? 'error' : 'warning';
      recordFinding(`console-${message.type()}`, sensitive.length > 0 ? '[redacted]' : text, severity);
    });
    page.on('pageerror', (error) => {
      const allowed = includesAllowedSubstring(error.message, config.allowedPageErrorSubstrings);
      recordFinding('page-error', error.message, allowed ? 'info' : 'error');
    });
    page.on('requestfailed', (request) => {
      const failure = request.failure()?.errorText || '';
      const detail = `${request.method()} ${safeUrl(request.url())} ${failure}`.trim();
      const allowed = includesAllowedSubstring(request.url(), config.allowedFailedRequestUrlSubstrings);
      const navigationAbort = /ERR_ABORTED|NS_BINDING_ABORTED/i.test(failure);
      recordFinding('request-failed', detail, allowed ? 'info' : navigationAbort ? 'warning' : 'error');
    });
    page.on('response', (response) => {
      const status = response.status();
      if (status < 400) return;
      const detail = `${status} ${safeUrl(response.url())}`;
      if (isAllowedHttpResponse(response.url(), status, config.allowedHttpResponses)) {
        recordFinding('expected-http-response', detail, 'info');
      } else if (status >= 500) {
        recordFinding('server-error', detail, 'error');
      } else {
        recordFinding('http-error', detail, 'warning');
      }
    });

    const firstStep = config.steps[0];
    await page.goto(resolveUrl(baseUrl, firstStep.url || '/'), {
      waitUntil: firstStep.navigationWaitUntil || config.navigationWaitUntil || 'domcontentloaded',
      timeout: finiteNumber(firstStep.timeoutMs ?? config.readyTimeoutMs, 30000, 1),
    });
    await waitForReady(page, config, firstStep);

    pointer = new WalkthroughPointer(page, pointerConfig);
    await pointer.start();
    await page.screenshot({ path: openingFramePath, animations: 'disabled' });

    await page.screencast.start({
      path: videoPath,
      size: viewport,
      quality: finiteNumber(config.videoQuality, 90, 0, 100),
    });
    screencastStarted = true;
    recordingStartedAt = performance.now();
    const clock = () => Math.max(0, performance.now() - recordingStartedAt);
    pointer.setClock(clock);

    const openingHoldMs = finiteNumber(firstStep.holdMs ?? config.openingHoldMs ?? config.stepHoldMs, 1500);
    await page.waitForTimeout(openingHoldMs);
    const firstCheckpoint = await captureCheckpoint(0, firstStep);
    if (firstCheckpoint) lastCheckpointPath = path.join(checkpointDir, firstCheckpoint);
    timeline.push({
      index: 1,
      label: firstStep.label,
      action: firstStep.action,
      beforeUrl: safeUrl(page.url()),
      afterUrl: safeUrl(page.url()),
      startMs: 0,
      actionEndMs: 0,
      endMs: clock(),
      durationMs: clock(),
      actionDurationMs: 0,
      holdMs: openingHoldMs,
      checkpoint: firstCheckpoint,
      bootstrappedBeforeRecording: true,
      ok: true,
    });

    for (let index = 1; index < config.steps.length; index += 1) {
      const step = config.steps[index];
      const startedAt = performance.now();
      const startMs = clock();
      const beforeUrl = page.url();
      try {
        const metadata = await runStep(page, step, config, outputDir, index, pointer, {
          lastCheckpointPath,
        });
        const actionEndMs = clock();
        const [visibleText, formValues] = await Promise.all([
          page.locator('body').innerText({ timeout: 3000 }),
          page.locator('input, textarea').evaluateAll((elements) =>
            elements.map((element) => {
              if (element instanceof HTMLInputElement && element.type.toLowerCase() === 'password') return '';
              return 'value' in element ? String(element.value || '') : '';
            }),
          ),
        ]);
        const sensitive = findSensitive(`${visibleText}\n${formValues.join('\n')}`);
        if (sensitive.length > 0) recordSensitive(`visible text after step ${index + 1}`, sensitive);
        const holdMs = step.action === 'pause' ? 0 : finiteNumber(step.holdMs ?? config.stepHoldMs, 1200);
        if (holdMs > 0) await page.waitForTimeout(holdMs);
        const checkpoint = await captureCheckpoint(index, step);
        if (checkpoint) lastCheckpointPath = path.join(checkpointDir, checkpoint);
        const endMs = clock();
        timeline.push({
          index: index + 1,
          label: step.label,
          action: step.action,
          beforeUrl: safeUrl(beforeUrl),
          afterUrl: safeUrl(page.url()),
          startMs,
          actionEndMs,
          endMs,
          durationMs: performance.now() - startedAt,
          actionDurationMs: actionEndMs - startMs,
          holdMs,
          checkpoint,
          metadata,
          ok: true,
        });
      } catch (error) {
        timeline.push({
          index: index + 1,
          label: step.label,
          action: step.action,
          beforeUrl: safeUrl(beforeUrl),
          afterUrl: safeUrl(page.url()),
          startMs,
          actionEndMs: clock(),
          endMs: clock(),
          durationMs: performance.now() - startedAt,
          actionDurationMs: clock() - startMs,
          holdMs: 0,
          checkpoint: null,
          ok: false,
          error: redactedMessage(error.message),
        });
        recordFinding('scenario-error', `Step ${index + 1}: ${error.message}`, 'error');
        throw error;
      }
    }
    await page.waitForTimeout(finalHoldMs);
    journeyEndMs = clock();
  } catch (error) {
    runError = error;
  } finally {
    if (screencastStarted) {
      try {
        await page.screencast.stop();
      } catch (error) {
        runError ||= error;
        recordFinding('screencast-stop-error', error.message, 'error');
      }
    }
    if (pointer) {
      try {
        await pointer.dispose();
      } catch (error) {
        runError ||= error;
        recordFinding('pointer-cleanup-error', error.message, 'error');
      }
    }
    if (context) {
      try {
        await context.close();
      } catch (error) {
        runError ||= error;
        recordFinding('context-close-error', error.message, 'error');
      }
    }
    try {
      await browser.close();
    } catch (error) {
      runError ||= error;
      recordFinding('browser-close-error', error.message, 'error');
    }
  }

  const report = {
    status: runError || findings.some((finding) => finding.severity === 'error') || sensitiveFindings.length > 0 ? 'failed' : 'passed',
    skill: {
      name: skillPackage.name,
      version: skillPackage.version,
    },
    name,
    repository: config.repository || null,
    baseUrl,
    videoPath: screencastStarted ? videoPath : null,
    outputDir,
    recording: {
      engine: 'page.screencast',
      startedAfterReady: true,
      openingFramePath,
      viewport,
      quality: finiteNumber(config.videoQuality, 90, 0, 100),
      journeyEndMs,
      finalHoldMs,
      clockOrigin: 'screencast-start-resolved',
    },
    pointer: pointerConfig,
    pointerTrack: pointer?.track || [],
    timeline,
    findings,
    sensitiveFindings: sensitiveFindings.map(({ key, ...item }) => item),
    thresholds: {
      minReadableHoldMs: finiteNumber(config.minReadableHoldMs, 900),
      maxStaticMs: finiteNumber(config.maxStaticMs, 7000),
      minSmoothScrollMs: 600,
      minSmoothDragMs: 600,
      pointerMissingFailMs: finiteNumber(config.pointerMissingFailMs, 160),
      openingStableMs: finiteNumber(config.openingStableMs, 800),
    },
    error: runError ? redactedMessage(runError.message) : null,
    completedAt: new Date().toISOString(),
  };
  await writeFile(path.join(outputDir, `${name}-run-report.json`), `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  await writeFile(path.join(outputDir, `${name}-timeline.json`), `${JSON.stringify(timeline, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(report, null, 2));
  if (report.status === 'failed') process.exitCode = 1;
}

run().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
