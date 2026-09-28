import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
import process from 'node:process';
import {
  finiteNumber,
  getModifiers,
  getTarget,
  hasTargetDescriptor,
  redactedMessage,
  resolveUrl,
  safeSlug,
  safeUrl,
} from './walkthrough-config.mjs';
import { activateWithPointer, createKeyboardInputEvidence } from './walkthrough-input.mjs';
import {
  cubicBezier,
  navigationBridgeHostId,
  navigationBridgeStorageKey,
  navigationCoverHtml,
  showOverlayAboveTopLayer,
} from './walkthrough-pointer.mjs';

async function waitForAssets(page, timeoutMs) {
  await page.evaluate(async (assetTimeoutMs) => {
    const timeout = (promise) => Promise.race([promise, new Promise((resolve) => window.setTimeout(resolve, assetTimeoutMs))]);
    if (document.fonts?.ready) await timeout(document.fonts.ready);
    const images = Array.from(document.images).filter((image) => {
      const rect = image.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });
    await timeout(
      Promise.allSettled(
        images.map(async (image) => {
          if (!image.complete) {
            await new Promise((resolve) => {
              image.addEventListener('load', resolve, { once: true });
              image.addEventListener('error', resolve, { once: true });
            });
          }
          if (typeof image.decode === 'function') await image.decode().catch(() => {});
        }),
      ),
    );
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  }, timeoutMs);
}

async function waitForLayoutStability(page, stableMs, timeoutMs) {
  await page.evaluate(
    async ({ requiredStableMs, maximumMs }) => {
      const snapshot = () => {
        const root = document.documentElement;
        const body = document.body;
        return [
          window.scrollX,
          window.scrollY,
          root?.scrollWidth || 0,
          root?.scrollHeight || 0,
          body?.getBoundingClientRect().width || 0,
          body?.getBoundingClientRect().height || 0,
        ]
          .map((value) => Math.round(value * 10) / 10)
          .join(':');
      };
      const startedAt = performance.now();
      let last = snapshot();
      let stableSince = performance.now();
      while (performance.now() - startedAt < maximumMs) {
        await new Promise((resolve) => requestAnimationFrame(resolve));
        const next = snapshot();
        if (next !== last) {
          last = next;
          stableSince = performance.now();
        }
        if (performance.now() - stableSince >= requiredStableMs) return;
      }
      throw new Error(`Layout did not remain stable for ${requiredStableMs}ms`);
    },
    { requiredStableMs: stableMs, maximumMs: timeoutMs },
  );
}

async function waitForReady(page, config, step = {}) {
  const timeout = finiteNumber(step.timeoutMs ?? config.readyTimeoutMs, 30000, 1);
  await page.waitForLoadState(step.navigationWaitUntil || config.navigationWaitUntil || 'domcontentloaded', { timeout });
  const readySelector = step.readySelector || config.readySelector;
  if (readySelector) await page.locator(readySelector).waitFor({ state: 'visible', timeout });
  await waitForAssets(page, finiteNumber(config.assetReadyTimeoutMs, 2500, 0));
  await waitForLayoutStability(
    page,
    finiteNumber(config.visualStabilityMs, 300, 100),
    finiteNumber(config.visualStabilityTimeoutMs, 5000, 500),
  );
  const settleMs = finiteNumber(step.navigationSettleMs ?? config.settleMs, 0);
  if (settleMs > 0) await page.waitForTimeout(settleMs);
}

async function waitForBoxStability(locator, timeoutMs = 3000) {
  const startedAt = performance.now();
  let previous;
  let stableSamples = 0;
  while (performance.now() - startedAt < timeoutMs) {
    const box = await locator.boundingBox();
    if (!box) throw new Error('Target is not visible');
    const rounded = {
      x: Math.round(box.x * 10) / 10,
      y: Math.round(box.y * 10) / 10,
      width: Math.round(box.width * 10) / 10,
      height: Math.round(box.height * 10) / 10,
    };
    if (previous && Object.keys(rounded).every((key) => rounded[key] === previous[key])) stableSamples += 1;
    else stableSamples = 0;
    if (stableSamples >= 2) return box;
    previous = rounded;
    await new Promise((resolve) => setTimeout(resolve, 80));
  }
  throw new Error('Target position did not become stable');
}

async function revealLocator(locator, page, config) {
  const timeout = finiteNumber(config.actionTimeoutMs, 30000, 1);
  await locator.waitFor({ state: 'visible', timeout });
  let box = await locator.boundingBox();
  if (!box) throw new Error('Target is not visible');
  const viewport = page.viewportSize();
  const margin = finiteNumber(config.targetViewportMargin, 48, 0);
  const insideViewport =
    viewport &&
    box.x >= margin &&
    box.y >= margin &&
    box.x + box.width <= viewport.width - margin &&
    box.y + box.height <= viewport.height - margin;
  if (!insideViewport) {
    await locator.evaluate((element) =>
      element.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
        inline: 'center',
      }),
    );
    box = await waitForBoxStability(locator, finiteNumber(config.scrollSettleTimeoutMs, 3000, 500));
  }
  return box;
}

function pointWithinBox(box, spec, label) {
  let localX = box.width / 2;
  let localY = box.height / 2;
  if (spec?.xRatio !== undefined || spec?.yRatio !== undefined) {
    const xRatio = Number(spec.xRatio);
    const yRatio = Number(spec.yRatio);
    if (!Number.isFinite(xRatio) || !Number.isFinite(yRatio) || xRatio < 0 || xRatio > 1 || yRatio < 0 || yRatio > 1) {
      throw new Error(`${label} ratios must be finite numbers between 0 and 1`);
    }
    localX = box.width * xRatio;
    localY = box.height * yRatio;
  } else if (spec?.x !== undefined || spec?.y !== undefined) {
    localX = Number(spec.x);
    localY = Number(spec.y);
    if (!Number.isFinite(localX) || !Number.isFinite(localY)) {
      throw new Error(`${label} pixel offsets must be finite numbers`);
    }
  }
  if (localX < 0 || localX > box.width || localY < 0 || localY > box.height) {
    throw new Error(`${label} falls outside its stable target`);
  }
  return {
    x: box.x + localX,
    y: box.y + localY,
    localX,
    localY,
  };
}

function assertPointInViewport(point, page, label) {
  const viewport = page.viewportSize();
  if (!viewport || point.x < 0 || point.y < 0 || point.x > viewport.width || point.y > viewport.height) {
    throw new Error(`${label} is outside the viewport`);
  }
}

async function stableTargetPoint(locator, page, config, spec, label) {
  await revealLocator(locator, page, config);
  const box = await waitForBoxStability(locator, finiteNumber(config.actionTimeoutMs, 30000, 1));
  const point = pointWithinBox(box, spec, label);
  assertPointInViewport(point, page, label);
  return { box, ...point };
}

async function moveTo(locator, page, config, pointer, spec) {
  const point = await stableTargetPoint(locator, page, config, spec, 'Pointer target');
  const motion = await pointer.moveTo(point.x, point.y);
  return { ...point, motion };
}

async function preparePointerActivation(locator, page, config, pointer, timeout, position, modifiers) {
  let target = await moveTo(locator, page, config, pointer, position);
  await locator.click({
    trial: true,
    timeout,
    modifiers,
    position: { x: target.localX, y: target.localY },
  });
  const stableBox = await waitForBoxStability(locator, timeout);
  const stablePoint = pointWithinBox(stableBox, position, 'Pointer activation target');
  const moved = Math.hypot(stablePoint.x - target.x, stablePoint.y - target.y);
  if (moved > 2) {
    target = await moveTo(locator, page, config, pointer, position);
  } else {
    target = { box: stableBox, ...stablePoint, motion: target.motion };
  }
  return target;
}

async function smoothWheel(page, step, config) {
  const totalX = finiteNumber(step.x, 0, -100000, 100000);
  const totalY = finiteNumber(step.y ?? step.amount, 800, -100000, 100000);
  const durationMs = finiteNumber(step.durationMs ?? config.scrollDurationMs, 900, 0);
  const batches = Math.max(8, Math.ceil(durationMs / 32));
  let emittedX = 0;
  let emittedY = 0;
  const startedAt = performance.now();
  for (let batch = 1; batch <= batches; batch += 1) {
    const progress = batch / batches;
    const eased = cubicBezier(progress, 0.4, 0, 0.2, 1);
    const nextX = totalX * eased;
    const nextY = totalY * eased;
    await page.mouse.wheel(nextX - emittedX, nextY - emittedY);
    emittedX = nextX;
    emittedY = nextY;
    const targetElapsed = durationMs * progress;
    const remaining = targetElapsed - (performance.now() - startedAt);
    if (remaining > 0) await page.waitForTimeout(remaining);
  }
  await waitForLayoutStability(page, finiteNumber(config.scrollStableMs, 240, 80), finiteNumber(config.scrollSettleTimeoutMs, 3000, 500));
  return { smoothScrollDurationMs: performance.now() - startedAt, deltaX: totalX, deltaY: totalY };
}

async function runStep(page, step, config, outputDir, index, pointer, runtime = {}) {
  const timeout = finiteNumber(step.timeoutMs ?? config.actionTimeoutMs, 30000, 1);
  const action = step.action;
  if (action === 'goto') {
    await page.goto(resolveUrl(config.baseUrl, step.url || '/'), {
      waitUntil: step.navigationWaitUntil || config.navigationWaitUntil || 'domcontentloaded',
      timeout,
    });
    await waitForReady(page, config, step);
    return {};
  }
  if (action === 'pause') {
    await page.waitForTimeout(finiteNumber(step.ms ?? step.holdMs ?? config.stepHoldMs, 1200));
    return {};
  }
  if (action === 'reload') {
    let cover = null;
    let coverStartMs = null;
    let bridgeRemoved = false;
    let navigationStartMs = null;
    let navigationEndMs = null;
    try {
      if (step.preserveVisualDuringReload === true) {
        if (!runtime.lastCheckpointPath) {
          throw new Error(`Step "${step.label || index}" needs the previous checkpoint for visual reload continuity`);
        }
        const snapshot = await readFile(runtime.lastCheckpointPath);
        const imageDataUrl = `data:image/png;base64,${snapshot.toString('base64')}`;
        await page.evaluate(({ storageKey, payload }) => window.sessionStorage.setItem(storageKey, JSON.stringify(payload)), {
          storageKey: navigationBridgeStorageKey,
          payload: {
            version: 1,
            url: page.url(),
            imageDataUrl,
          },
        });
        cover = await showOverlayAboveTopLayer(
          page,
          navigationCoverHtml(imageDataUrl.slice('data:image/png;base64,'.length), pointer.snapshot()),
        );
        coverStartMs = pointer.time();
        await page.waitForTimeout(finiteNumber(step.visualGuardLeadMs, 500, 250, 2000));
      }
      navigationStartMs = pointer.time();
      await page.reload({ waitUntil: config.navigationWaitUntil || 'domcontentloaded', timeout });
      if (cover) {
        await page.waitForFunction((hostId) => Boolean(document.getElementById(hostId)), navigationBridgeHostId, {
          timeout: Math.min(timeout, 5000),
        });
      }
      await waitForReady(page, config, step);
      navigationEndMs = pointer.time();
      if (cover) {
        await page.waitForTimeout(finiteNumber(step.visualGuardSettleMs, 160, 0, 2000));
        await page.evaluate(
          ({ hostId, storageKey }) => {
            document.getElementById(hostId)?.remove();
            window.sessionStorage.removeItem(storageKey);
          },
          {
            hostId: navigationBridgeHostId,
            storageKey: navigationBridgeStorageKey,
          },
        );
        bridgeRemoved = true;
      }
    } finally {
      if (cover && !bridgeRemoved) {
        await page
          .evaluate(
            ({ hostId, storageKey }) => {
              document.getElementById(hostId)?.remove();
              window.sessionStorage.removeItem(storageKey);
            },
            {
              hostId: navigationBridgeHostId,
              storageKey: navigationBridgeStorageKey,
            },
          )
          .catch(() => {});
      }
      if (cover) await cover.dispose();
    }
    return cover
      ? {
          visualContinuityGuard: {
            kind: 'document-start-snapshot-bridge',
            sourceCheckpoint: path.basename(runtime.lastCheckpointPath),
            startMs: coverStartMs,
            endMs: pointer.time(),
          },
          navigationStartMs,
          navigationEndMs,
        }
      : {};
  }
  if (action === 'back' || action === 'forward') {
    const response =
      action === 'back'
        ? await page.goBack({
            waitUntil: config.navigationWaitUntil || 'domcontentloaded',
            timeout,
          })
        : await page.goForward({
            waitUntil: config.navigationWaitUntil || 'domcontentloaded',
            timeout,
          });
    if (!response && step.requireNavigation !== false) throw new Error(`${action} did not navigate`);
    await waitForReady(page, config, step);
    return {};
  }
  if (action === 'waitForText') {
    await page.getByText(step.text, { exact: Boolean(step.exact) }).waitFor({ state: 'visible', timeout });
    return {};
  }
  if (action === 'waitForSelector') {
    await getTarget(page, step).waitFor({ state: step.state || 'visible', timeout });
    return {};
  }
  if (action === 'waitForUrl') {
    await page.waitForURL(step.url, {
      timeout,
      waitUntil: step.navigationWaitUntil || 'domcontentloaded',
    });
    return {};
  }
  if (action === 'assertText') {
    const locator = step.target || step.selector ? getTarget(page, step) : page.locator('body');
    const actual = await locator.innerText({ timeout });
    if (!actual.includes(String(step.text))) {
      throw new Error(`Expected visible text was not found: ${redactedMessage(step.text)}`);
    }
    return {};
  }
  if (action === 'assertUrl') {
    const actual = page.url();
    if (step.url && actual !== resolveUrl(config.baseUrl, step.url)) {
      throw new Error(`Expected URL ${safeUrl(resolveUrl(config.baseUrl, step.url))}, received ${safeUrl(actual)}`);
    }
    if (step.urlIncludes && !actual.includes(String(step.urlIncludes))) {
      throw new Error(`Expected URL to include ${redactedMessage(step.urlIncludes)}, received ${safeUrl(actual)}`);
    }
    return {};
  }
  if (action === 'assertVisible') {
    await getTarget(page, step).waitFor({ state: 'visible', timeout });
    return {};
  }
  if (action === 'click' || action === 'hover') {
    const locator = getTarget(page, step);
    let target;
    if (action === 'click') {
      const modifiers = getModifiers(step);
      const preparedTarget = await preparePointerActivation(locator, page, config, pointer, timeout, step.position, modifiers);
      const activated = await activateWithPointer({
        target: preparedTarget,
        pointer,
        activate: (currentTarget) =>
          locator.click({
            timeout,
            modifiers,
            position: { x: currentTarget.localX, y: currentTarget.localY },
          }),
      });
      target = activated.target;
      await waitForReady(page, config, step);
      return {
        target: { x: target.x, y: target.y },
        inputEvents: [activated.input],
      };
    }
    target = await moveTo(locator, page, config, pointer, step.position);
    return { target: { x: target.x, y: target.y } };
  }
  if (action === 'drag') {
    const sourceLocator = getTarget(page, step);
    const destinationLocator = hasTargetDescriptor(step.toTarget)
      ? getTarget(page, { label: step.label, target: step.toTarget })
      : sourceLocator;
    await revealLocator(sourceLocator, page, config);
    if (destinationLocator !== sourceLocator) await revealLocator(destinationLocator, page, config);
    const sourceBox = await waitForBoxStability(sourceLocator, timeout);
    const destinationBox = destinationLocator === sourceLocator ? sourceBox : await waitForBoxStability(destinationLocator, timeout);
    const source = { box: sourceBox, ...pointWithinBox(sourceBox, step.from, 'Drag start') };
    const destination = {
      box: destinationBox,
      ...pointWithinBox(destinationBox, step.to, 'Drag destination'),
    };
    assertPointInViewport(source, page, 'Drag start');
    assertPointInViewport(destination, page, 'Drag destination');
    const distancePx = Math.hypot(destination.x - source.x, destination.y - source.y);
    if (distancePx < 4) throw new Error(`Step "${step.label || index}" drag distance is too small`);
    await pointer.moveTo(source.x, source.y);
    const modifiers = getModifiers(step);
    await sourceLocator.click({
      trial: true,
      timeout,
      modifiers,
      position: { x: source.localX, y: source.localY },
    });
    for (const modifier of modifiers) await page.keyboard.down(modifier);
    const button = String(step.button || 'left');
    let dragStartMs;
    let dragEndMs;
    try {
      await pointer.setPressed(true);
      await page.mouse.down({ button });
      dragStartMs = pointer.time();
      await pointer.moveTo(destination.x, destination.y, {
        durationMs: finiteNumber(step.durationMs ?? config.dragDurationMs, 900, 0, 5000),
        holdMs: 0,
        pressed: true,
      });
      dragEndMs = pointer.time();
    } finally {
      await page.mouse.up({ button }).catch(() => {});
      await pointer.setPressed(false).catch(() => {});
      for (const modifier of modifiers.reverse()) await page.keyboard.up(modifier).catch(() => {});
    }
    await waitForReady(page, config, step);
    return {
      dragStartMs,
      dragEndMs,
      dragDurationMs: dragEndMs - dragStartMs,
      distancePx,
      from: { x: source.x, y: source.y },
      to: { x: destination.x, y: destination.y },
    };
  }
  if (action === 'type') {
    const locator = getTarget(page, step);
    const value = step.textFromEnv ? process.env[step.textFromEnv] : step.text;
    if (value === undefined) throw new Error(`Step "${step.label || index}" has no text or textFromEnv value`);
    if (step.textFromEnv) {
      const field = await locator.evaluate((element) => ({
        tagName: element.tagName.toLowerCase(),
        type: element instanceof HTMLInputElement ? element.type.toLowerCase() : null,
      }));
      const maskedByBrowser = field.tagName === 'input' && field.type === 'password';
      if (!maskedByBrowser && step.allowVisibleEnvText !== true) {
        throw new Error(
          `Step "${step.label || index}" uses textFromEnv in a visible field; use a password input or set allowVisibleEnvText only for known non-sensitive fixture text`,
        );
      }
    }
    const target = await preparePointerActivation(locator, page, config, pointer, timeout);
    const activated = await activateWithPointer({
      target,
      pointer,
      activate: (target) =>
        locator.click({
          timeout,
          position: { x: target.localX, y: target.localY },
        }),
    });
    await locator.fill('');
    await locator.pressSequentially(String(value), {
      delay: finiteNumber(step.typeDelayMs ?? config.typeDelayMs, 45, 0),
      timeout,
    });
    return {
      target: { x: activated.target.x, y: activated.target.y },
      charactersTyped: String(value).length,
      inputEvents: [activated.input],
    };
  }
  if (action === 'typeKeys') {
    const value = step.textFromEnv ? process.env[step.textFromEnv] : step.text;
    if (value === undefined) throw new Error(`Step "${step.label || index}" has no text or textFromEnv value`);
    if (step.textFromEnv && step.allowVisibleEnvText !== true) {
      throw new Error(
        `Step "${step.label || index}" uses textFromEnv for keyboard input; set allowVisibleEnvText only for known non-sensitive fixture text`,
      );
    }
    await page.keyboard.type(String(value), {
      delay: finiteNumber(step.typeDelayMs ?? config.typeDelayMs, 45, 0),
    });
    await waitForReady(page, config, step);
    return { charactersTyped: String(value).length, keyboardInput: true };
  }
  if (action === 'select') {
    const locator = getTarget(page, step);
    const target = await preparePointerActivation(locator, page, config, pointer, timeout);
    const activated = await activateWithPointer({
      target,
      pointer,
      activate: () => locator.selectOption(step.value !== undefined ? { value: String(step.value) } : { label: String(step.option) }),
    });
    await waitForReady(page, config, step);
    return {
      target: { x: activated.target.x, y: activated.target.y },
      inputEvents: [activated.input],
    };
  }
  if (action === 'press') {
    const scope = step.scope === 'global' ? 'global' : 'target';
    const pointerPosition = pointer.snapshot().position;
    let locator = null;
    let targetBox = null;
    let focusBox = null;
    let focusConfirmed = false;
    if (scope === 'target') {
      locator = getTarget(page, step);
      await revealLocator(locator, page, config);
      targetBox = await waitForBoxStability(locator, timeout);
      await locator.focus({ timeout });
      focusConfirmed = await locator.evaluate((element) => element === document.activeElement || element.contains(document.activeElement));
      if (!focusConfirmed) throw new Error(`Step "${step.label || index}" target did not focus`);
      focusBox = await waitForBoxStability(locator, timeout);
    }
    const keyChord = String(step.key);
    const keyboardCue = await pointer.beginKeyboard(targetBox, keyChord, {
      leadMs: finiteNumber(step.keyboardCueLeadMs ?? config.keyboardCueLeadMs, 320, 0, 2000),
      holdMs: finiteNumber(step.keyboardCueHoldMs ?? config.keyboardCueHoldMs, 420, 0, 2500),
    });
    const activationTimeMs = pointer.markKeyboardActivation(keyboardCue);
    let cue;
    try {
      if (locator) await locator.press(keyChord, { timeout });
      else await page.keyboard.press(keyChord);
    } finally {
      cue = await pointer.finishKeyboard(keyboardCue);
    }
    await waitForReady(page, config, step);
    const input = createKeyboardInputEvidence({
      scope,
      targetBox,
      focusBox,
      focusConfirmed,
      pointerPosition,
      pointerVisibleAtActivation: false,
      settleMs: activationTimeMs - keyboardCue.shownAtMs,
      activationTimeMs,
      keyChord,
      cue,
    });
    return { inputEvents: [input] };
  }
  if (action === 'scroll') {
    if (step.target || step.selector) {
      const locator = getTarget(page, step);
      const before = await locator.boundingBox();
      const startedAt = performance.now();
      await locator.evaluate((element) =>
        element.scrollIntoView({
          behavior: 'smooth',
          block: 'center',
          inline: 'center',
        }),
      );
      const after = await waitForBoxStability(locator, finiteNumber(config.scrollSettleTimeoutMs, 3000, 500));
      const scrollDistancePx = before ? Math.hypot(after.x - before.x, after.y - before.y) : 0;
      return {
        smoothTargetScroll: true,
        smoothScrollDurationMs: performance.now() - startedAt,
        scrollDistancePx,
      };
    }
    return smoothWheel(page, step, config);
  }
  if (action === 'screenshot') {
    const filename = `${String(step.filename || `${String(index).padStart(3, '0')}-${safeSlug(step.label || action)}`)}.png`;
    await page.screenshot({
      path: path.join(outputDir, filename),
      fullPage: Boolean(step.fullPage),
    });
    return { screenshot: filename };
  }
  throw new Error(`Unsupported walkthrough action: ${action}`);
}

export { runStep, waitForReady };
