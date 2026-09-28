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
  await page.setContent(
    '<style>html,body{margin:0;background:#fff}dialog{inset:0;width:100vw;height:100vh;max-width:none;max-height:none;margin:0;border:0;background:#fff}dialog::backdrop{background:#fff}</style><dialog>Native dialog</dialog>',
  );
  pointer = new WalkthroughPointer(page, {
    color: '#ff3b30',
    enabled: true,
    moveDurationMs: 0,
    moveHoldMs: 0,
    rippleMs: 520,
    rippleSize: 38,
    size: 20,
    startX: 20,
    startY: 20,
  });
  pointer.setClock(() => performance.now());
  await pointer.start();
  const beforeDialog = await redPixelCount(page, await page.screenshot());
  await page.locator('dialog').evaluate((dialog) => dialog.showModal());
  await pointer.moveTo(30, 30, { durationMs: 0, holdMs: 0 });
  const overDialog = await redPixelCount(page, await page.screenshot());
  if (beforeDialog < 50) throw new Error('pointer was not visible before the native dialog opened');
  if (overDialog < 50) throw new Error('pointer disappeared behind the native dialog');
  console.log(`native-dialog-pointer-smoke: PASS before=${beforeDialog} modal=${overDialog}`);
} finally {
  await pointer?.dispose();
  await browser.close();
}
