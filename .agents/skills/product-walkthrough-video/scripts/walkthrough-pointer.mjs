import { performance } from 'node:perf_hooks';
import { finiteNumber } from './walkthrough-config.mjs';

const navigationBridgeStorageKey = '__prd_walkthrough_reload_bridge_v1';
const navigationBridgeHostId = '__prd-walkthrough-reload-bridge';
const viewTransitionOverlayName = 'prd-walkthrough-overlay';
const viewTransitionStyleId = '__prd-walkthrough-view-transition-style';

function cubicBezier(progress, x1, y1, x2, y2) {
  const sample = (time, first, second) => {
    const inverse = 1 - time;
    return 3 * inverse * inverse * time * first + 3 * inverse * time * time * second + time * time * time;
  };
  let lower = 0;
  let upper = 1;
  for (let iteration = 0; iteration < 16; iteration += 1) {
    const midpoint = (lower + upper) / 2;
    if (sample(midpoint, x1, x2) < progress) lower = midpoint;
    else upper = midpoint;
  }
  return sample((lower + upper) / 2, y1, y2);
}

async function moveMouseWithDuration(page, from, to, durationMs) {
  if (durationMs <= 0) {
    await page.mouse.move(to.x, to.y, { steps: 12 });
    return;
  }
  const batches = Math.max(6, Math.ceil(durationMs / 64));
  const startedAt = performance.now();
  for (let batch = 1; batch <= batches; batch += 1) {
    const progress = batch / batches;
    const eased = cubicBezier(progress, 0.4, 0, 0.2, 1);
    const x = from.x + (to.x - from.x) * eased;
    const y = from.y + (to.y - from.y) * eased;
    await page.mouse.move(x, y, { steps: 4 });
    const targetElapsed = durationMs * progress;
    const remaining = targetElapsed - (performance.now() - startedAt);
    if (remaining > 0) await page.waitForTimeout(remaining);
  }
}

function pointerHtml(options, from, to, durationMs, pressed = false) {
  const animation = durationMs > 0 ? `animation: walkthrough-pointer-move ${durationMs}ms cubic-bezier(.4,0,.2,1) forwards;` : '';
  return `
        <style>
            @keyframes walkthrough-pointer-move {
                from { left: ${from.x}px; top: ${from.y}px; }
                to { left: ${to.x}px; top: ${to.y}px; }
            }
            .walkthrough-pointer {
                position: fixed;
                z-index: 2147483647;
                left: ${durationMs > 0 ? from.x : to.x}px;
                top: ${durationMs > 0 ? from.y : to.y}px;
                width: ${options.size}px;
                height: ${options.size}px;
                border: 3px solid ${options.color};
                border-radius: 50%;
                box-sizing: content-box;
                pointer-events: none;
                transform: translate(-50%, -50%) scale(${pressed ? 0.72 : 1});
                background: ${pressed ? 'rgba(255,59,48,.28)' : 'transparent'};
                box-shadow: 0 0 0 3px rgba(255,255,255,.85);
                ${animation}
            }
        </style>
        <div class="walkthrough-pointer" aria-hidden="true"></div>
    `;
}

function rippleHtml(options, position) {
  return `
        <style>
            @keyframes walkthrough-pointer-ripple {
                from { opacity: .95; transform: translate(-50%, -50%) scale(.45); }
                to { opacity: 0; transform: translate(-50%, -50%) scale(1.6); }
            }
            .walkthrough-pointer-ripple {
                position: fixed;
                z-index: 2147483646;
                left: ${position.x}px;
                top: ${position.y}px;
                width: ${options.rippleSize}px;
                height: ${options.rippleSize}px;
                border: 3px solid ${options.color};
                border-radius: 50%;
                box-sizing: content-box;
                pointer-events: none;
                transform: translate(-50%, -50%);
                animation: walkthrough-pointer-ripple ${options.rippleMs}ms ease-out forwards;
            }
        </style>
        <div class="walkthrough-pointer-ripple" aria-hidden="true"></div>
    `;
}

function escapeHtml(value) {
  return String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}

function keyboardCueHtml(targetBox, keyChord) {
  const focus = targetBox ? `<div class="walkthrough-keyboard-focus" aria-hidden="true"></div>` : '';
  const focusStyle = targetBox
    ? `
            .walkthrough-keyboard-focus {
                position: fixed;
                z-index: 2147483647;
                left: ${Math.max(0, targetBox.x - 6)}px;
                top: ${Math.max(0, targetBox.y - 6)}px;
                width: ${targetBox.width + 12}px;
                height: ${targetBox.height + 12}px;
                border: 3px solid #0a84ff;
                border-radius: 10px;
                box-sizing: border-box;
                pointer-events: none;
                box-shadow: 0 0 0 3px rgba(255,255,255,.92), 0 8px 24px rgba(0,0,0,.18);
            }
        `
    : '';
  const keys = escapeHtml(String(keyChord).slice(0, 48))
    .split('+')
    .map((key) => `<kbd>${key.trim()}</kbd>`)
    .join('<span aria-hidden="true">+</span>');
  return `
        <style>
            ${focusStyle}
            .walkthrough-keyboard-cue {
                position: fixed;
                z-index: 2147483647;
                left: 50%;
                bottom: 28px;
                display: flex;
                align-items: center;
                gap: 8px;
                transform: translateX(-50%);
                padding: 10px 14px;
                border: 2px solid #0a84ff;
                border-radius: 14px;
                box-sizing: border-box;
                color: #fff;
                background: rgba(20,20,24,.94);
                box-shadow: 0 8px 28px rgba(0,0,0,.28);
                font: 600 16px/1 system-ui, sans-serif;
                pointer-events: none;
            }
            .walkthrough-keyboard-cue kbd {
                min-width: 28px;
                padding: 6px 8px;
                border: 1px solid rgba(255,255,255,.72);
                border-radius: 7px;
                box-sizing: border-box;
                color: #fff;
                background: rgba(255,255,255,.14);
                font: inherit;
                text-align: center;
            }
        </style>
        ${focus}
        <div class="walkthrough-keyboard-cue" aria-hidden="true">${keys}</div>
    `;
}

function navigationCoverHtml(pngBase64, pointerSnapshot) {
  return `
        <style>
            .walkthrough-navigation-cover {
                position: fixed;
                inset: 0;
                z-index: 2147483645;
                width: 100vw;
                height: 100vh;
                object-fit: fill;
                pointer-events: none;
                user-select: none;
            }
            .walkthrough-navigation-cover-pointer {
                position: fixed;
                z-index: 2147483647;
                left: ${pointerSnapshot.position.x}px;
                top: ${pointerSnapshot.position.y}px;
                width: ${pointerSnapshot.options.size}px;
                height: ${pointerSnapshot.options.size}px;
                border: 3px solid ${pointerSnapshot.options.color};
                border-radius: 50%;
                box-sizing: content-box;
                pointer-events: none;
                transform: translate(-50%, -50%);
                background: transparent;
                box-shadow: 0 0 0 3px rgba(255,255,255,.85);
            }
        </style>
        <img class="walkthrough-navigation-cover" src="data:image/png;base64,${pngBase64}" alt="">
        <div class="walkthrough-navigation-cover-pointer" aria-hidden="true"></div>
    `;
}

function installNavigationBridge({ storageKey, hostId }) {
  if (window.top !== window) return;
  let payload;
  try {
    const raw = window.sessionStorage.getItem(storageKey);
    if (!raw) return;
    window.sessionStorage.removeItem(storageKey);
    payload = JSON.parse(raw);
  } catch {
    return;
  }
  if (
    payload?.version !== 1 ||
    payload.url !== window.location.href ||
    typeof payload.imageDataUrl !== 'string' ||
    !payload.imageDataUrl.startsWith('data:image/png;base64,')
  ) {
    return;
  }
  const mount = () => {
    if (!document.documentElement || document.getElementById(hostId)) return;
    const host = document.createElement('x-prd-walkthrough-reload-bridge');
    host.id = hostId;
    host.setAttribute('aria-hidden', 'true');
    host.setAttribute('data-recorder-owned', 'true');
    for (const [property, value] of Object.entries({
      position: 'fixed',
      inset: '0',
      width: '100vw',
      height: '100vh',
      margin: '0',
      padding: '0',
      border: '0',
      overflow: 'hidden',
      'pointer-events': 'none',
      'user-select': 'none',
      contain: 'strict',
      isolation: 'isolate',
      'z-index': '2147483647',
    })) {
      host.style.setProperty(property, value, 'important');
    }
    const root = host.attachShadow({ mode: 'closed' });
    const image = document.createElement('img');
    image.alt = '';
    image.decoding = 'sync';
    image.loading = 'eager';
    image.fetchPriority = 'high';
    image.src = payload.imageDataUrl;
    for (const [property, value] of Object.entries({
      display: 'block',
      width: '100%',
      height: '100%',
      margin: '0',
      padding: '0',
      border: '0',
      'object-fit': 'fill',
      'pointer-events': 'none',
      'user-select': 'none',
    })) {
      image.style.setProperty(property, value, 'important');
    }
    root.append(image);
    document.documentElement.append(host);
  };
  if (document.documentElement) {
    mount();
    return;
  }
  const observer = new MutationObserver(() => {
    if (!document.documentElement) return;
    observer.disconnect();
    mount();
  });
  observer.observe(document, { childList: true, subtree: true });
}

async function showOverlayAboveTopLayer(page, html) {
  const overlay = await page.screencast.showOverlay(html);
  await page.evaluate(
    ({ overlayName, styleId }) => {
      const glass = document.querySelector('x-pw-glass[popover]');
      if (!(glass instanceof HTMLElement) || typeof glass.hidePopover !== 'function' || typeof glass.showPopover !== 'function') {
        throw new Error('Playwright overlay popover is unavailable');
      }
      glass.style.setProperty('view-transition-name', overlayName, 'important');
      let style = document.getElementById(styleId);
      if (!style) {
        style = document.createElement('style');
        style.id = styleId;
        style.setAttribute('data-recorder-owned', 'true');
        (document.head ?? document.documentElement).append(style);
      }
      if (!(style instanceof HTMLStyleElement)) {
        throw new Error('Walkthrough view transition style is unavailable');
      }
      style.textContent = `
        ::view-transition-group(${overlayName}) {
          z-index: 2147483647;
          animation: none !important;
        }
        ::view-transition-old(${overlayName}),
        ::view-transition-new(${overlayName}) {
          animation: none !important;
          mix-blend-mode: normal;
        }
      `;
      if (glass.matches(':popover-open')) glass.hidePopover();
      glass.showPopover();
    },
    {
      overlayName: viewTransitionOverlayName,
      styleId: viewTransitionStyleId,
    },
  );
  return overlay;
}

class WalkthroughPointer {
  constructor(page, options) {
    this.page = page;
    this.options = options;
    this.position = { x: options.startX, y: options.startY };
    this.overlay = null;
    this.clock = () => 0;
    this.track = [];
  }

  setClock(clock) {
    this.clock = clock;
    this.track.push({ kind: 'static', atMs: this.clock(), x: this.position.x, y: this.position.y });
  }

  async start() {
    if (!this.options.enabled) return;
    this.overlay = await showOverlayAboveTopLayer(this.page, pointerHtml(this.options, this.position, this.position, 0));
    await this.page.mouse.move(this.position.x, this.position.y);
  }

  async swap(html) {
    const next = await showOverlayAboveTopLayer(this.page, html);
    const previous = this.overlay;
    this.overlay = next;
    if (previous) await previous.dispose();
  }

  async moveTo(x, y, options = {}) {
    const to = { x, y };
    const durationMs = finiteNumber(options.durationMs, this.options.moveDurationMs, 0, 5000);
    const pressed = options.pressed === true;
    const moveStartedAtMs = this.clock();
    if (!this.options.enabled) {
      await moveMouseWithDuration(this.page, this.position, to, durationMs);
      this.position = to;
      const moveEndedAtMs = this.clock();
      const holdMs = finiteNumber(options.holdMs, this.options.moveHoldMs, 0, 3000);
      if (holdMs > 0) await this.page.waitForTimeout(holdMs);
      const settledAtMs = this.clock();
      return {
        moveStartedAtMs,
        moveEndedAtMs,
        settledAtMs,
        settleMs: settledAtMs - moveEndedAtMs,
      };
    }
    const from = { ...this.position };
    const movingOverlay = await showOverlayAboveTopLayer(this.page, pointerHtml(this.options, from, to, durationMs, pressed));
    const previous = this.overlay;
    this.overlay = movingOverlay;
    const animationStartMs = this.clock();
    await Promise.all([moveMouseWithDuration(this.page, from, to, durationMs), previous ? previous.dispose() : Promise.resolve()]);
    const expectedAnimationEndMs = animationStartMs + durationMs;
    const remainingAnimationMs = expectedAnimationEndMs - this.clock();
    if (remainingAnimationMs > 0) await this.page.waitForTimeout(remainingAnimationMs);
    const staticOverlay = await showOverlayAboveTopLayer(this.page, pointerHtml(this.options, to, to, 0, pressed));
    this.overlay = staticOverlay;
    await movingOverlay.dispose();
    this.position = to;
    this.track.push({
      kind: 'move',
      startMs: animationStartMs,
      endMs: expectedAnimationEndMs,
      from,
      to,
      pressed,
    });
    const holdMs = finiteNumber(options.holdMs, this.options.moveHoldMs, 0, 3000);
    if (holdMs > 0) await this.page.waitForTimeout(holdMs);
    const settledAtMs = this.clock();
    return {
      moveStartedAtMs,
      moveEndedAtMs: expectedAnimationEndMs,
      settledAtMs,
      settleMs: settledAtMs - expectedAnimationEndMs,
    };
  }

  async setPressed(pressed) {
    if (!this.options.enabled) return;
    await this.swap(pointerHtml(this.options, this.position, this.position, 0, pressed));
    this.track.push({
      kind: pressed ? 'press' : 'release',
      atMs: this.clock(),
      x: this.position.x,
      y: this.position.y,
    });
  }

  time() {
    return this.clock();
  }

  snapshot() {
    return {
      position: { ...this.position },
      options: {
        color: this.options.color,
        enabled: this.options.enabled,
        size: this.options.size,
      },
    };
  }

  async beginClick() {
    if (!this.options.enabled) return null;
    await this.swap(pointerHtml(this.options, this.position, this.position, 0, true));
    await this.page.waitForTimeout(80);
    await this.swap(pointerHtml(this.options, this.position, this.position, 0));
    const ripple = await showOverlayAboveTopLayer(this.page, rippleHtml(this.options, this.position));
    const shownAtMs = this.clock();
    this.track.push({ kind: 'click', atMs: shownAtMs, x: this.position.x, y: this.position.y });
    const clickCue = {
      ripple,
      startedAt: performance.now(),
      shownAtMs,
      disposed: false,
      disposePromise: null,
      navigationHandler: null,
    };
    clickCue.navigationHandler = (frame) => {
      if (frame !== this.page.mainFrame() || clickCue.disposed) return;
      clickCue.disposed = true;
      clickCue.disposePromise = clickCue.ripple.dispose();
    };
    this.page.on('framenavigated', clickCue.navigationHandler);
    return clickCue;
  }

  async finishClick(clickCue) {
    if (!clickCue) return;
    this.page.off('framenavigated', clickCue.navigationHandler);
    if (clickCue.disposePromise) {
      await clickCue.disposePromise;
    } else if (!clickCue.disposed) {
      const remaining = this.options.rippleMs - (performance.now() - clickCue.startedAt);
      if (remaining > 0) await this.page.waitForTimeout(remaining);
      clickCue.disposed = true;
      await clickCue.ripple.dispose();
    }
    return {
      kind: 'click-ripple',
      shownAtMs: clickCue.shownAtMs,
      hiddenAtMs: this.clock(),
    };
  }

  async beginKeyboard(targetBox, keyChord, options = {}) {
    await this.swap(keyboardCueHtml(targetBox, keyChord));
    const shownAtMs = this.clock();
    if (this.options.enabled) {
      this.track.push({ kind: 'visibility', atMs: shownAtMs, visible: false });
    }
    const trackEvent = {
      kind: 'keyboard-cue',
      startMs: shownAtMs,
      activationAtMs: null,
      endMs: null,
      targetBox: targetBox || null,
    };
    this.track.push(trackEvent);
    const leadMs = finiteNumber(options.leadMs, 320, 0, 2000);
    if (leadMs > 0) await this.page.waitForTimeout(leadMs);
    return {
      shownAtMs,
      activationAtMs: null,
      holdMs: finiteNumber(options.holdMs, 420, 0, 2500),
      trackEvent,
    };
  }

  markKeyboardActivation(cue) {
    const activationAtMs = this.clock();
    cue.activationAtMs = activationAtMs;
    cue.trackEvent.activationAtMs = activationAtMs;
    return activationAtMs;
  }

  async finishKeyboard(cue) {
    const holdStartMs = cue.activationAtMs ?? this.clock();
    const remaining = cue.holdMs - (this.clock() - holdStartMs);
    if (remaining > 0) await this.page.waitForTimeout(remaining);
    if (this.options.enabled) {
      await this.swap(pointerHtml(this.options, this.position, this.position, 0));
    } else if (this.overlay) {
      await this.overlay.dispose();
      this.overlay = null;
    }
    const hiddenAtMs = this.clock();
    cue.trackEvent.endMs = hiddenAtMs;
    if (this.options.enabled) {
      this.track.push({ kind: 'visibility', atMs: hiddenAtMs, visible: true });
    }
    return {
      kind: 'keyboard',
      shownAtMs: cue.shownAtMs,
      activationAtMs: cue.activationAtMs,
      hiddenAtMs,
    };
  }

  async dispose() {
    if (this.overlay) await this.overlay.dispose();
    this.overlay = null;
  }
}

export {
  cubicBezier,
  installNavigationBridge,
  navigationBridgeHostId,
  navigationBridgeStorageKey,
  navigationCoverHtml,
  showOverlayAboveTopLayer,
  WalkthroughPointer,
};
