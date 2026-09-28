import { performance } from 'node:perf_hooks';
import { chromium } from 'playwright';
import { WalkthroughPointer } from '../scripts/walkthrough-pointer.mjs';

async function redPixelCount(page, png) {
  return page.evaluate(async (pngBase64) => {
    const image = new Image();
    image.src = `data:image/png;base64,${pngBase64}`;
    await image.decode();
    const canvas = document.createElement('canvas');
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    if (!context) throw new Error('canvas pixel inspection is unavailable');
    context.drawImage(image, 0, 0);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let count = 0;
    for (let index = 0; index < pixels.length; index += 4) {
      const red = pixels[index];
      const green = pixels[index + 1];
      const blue = pixels[index + 2];
      if (red > 200 && green < 120 && blue < 120) count += 1;
    }
    return count;
  }, png.toString('base64'));
}

const browser = await chromium.launch({ headless: true });
let pointer;
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.setContent(`
    <style>
      @keyframes fade-overlay { to { opacity: 0; } }
      @keyframes slide-page { from { transform: translateX(100%); } }
      html, body { margin: 0; background: #fff; }
      html { view-transition-name: root; }
      main { min-height: 100vh; background: #fff; view-transition-name: app-page; }
      dialog { inset: auto 0 0; width: 100vw; height: 240px; max-width: none; margin: 0; border: 0; background: #ddd; }
      dialog::backdrop { background: rgba(0, 0, 0, .4); }
      ::view-transition-group(root), ::view-transition-group(app-page) { animation: none; }
      ::view-transition-group(root) { z-index: 3; }
      ::view-transition-old(root) { animation: fade-overlay 200ms linear both; }
      ::view-transition-new(root) { opacity: 0; animation: none; }
      ::view-transition-new(app-page) { animation: slide-page 300ms linear both; }
    </style>
    <main>Old page</main>
    <dialog>Native sheet</dialog>
  `);
  pointer = new WalkthroughPointer(page, {
    color: '#ff3b30',
    enabled: true,
    moveDurationMs: 0,
    moveHoldMs: 0,
    rippleMs: 520,
    rippleSize: 38,
    size: 20,
    startX: 40,
    startY: 40,
  });
  pointer.setClock(() => performance.now());
  await pointer.start();
  await page.locator('dialog').evaluate((dialog) => dialog.showModal());
  await pointer.moveTo(48, 48, { durationMs: 0, holdMs: 0 });
  await page.evaluate(() => {
    const dialog = document.querySelector('dialog');
    const main = document.querySelector('main');
    const transition = document.startViewTransition(() => {
      dialog?.close();
      if (main) main.textContent = 'New page';
    });
    Reflect.set(window, '__walkthroughPointerTransition', transition);
  });
  const counts = [];
  for (let sample = 0; sample < 9; sample += 1) {
    await page.waitForTimeout(40);
    counts.push(await redPixelCount(page, await page.screenshot()));
  }
  await page.evaluate(() => Reflect.get(window, '__walkthroughPointerTransition')?.finished);
  const minimum = Math.min(...counts);
  if (minimum < 50) {
    throw new Error(`pointer disappeared during the document view transition: ${counts.join(',')}`);
  }
  console.log(`view-transition-pointer-smoke: PASS min=${minimum} samples=${counts.join(',')}`);
} finally {
  await pointer?.dispose();
  await browser.close();
}
