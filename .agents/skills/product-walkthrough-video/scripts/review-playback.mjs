import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const skillRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(skillRoot, 'package.json'));
const { chromium } = require('playwright');
function videoContentType(videoPath) {
  return path.extname(videoPath).toLowerCase() === '.webm' ? 'video/webm' : 'video/mp4';
}

async function startPlaybackServer(videoPath, videoBuffer) {
  const contentType = videoContentType(videoPath);
  const server = createServer((request, response) => {
    const requestPath = new URL(request.url || '/', 'http://127.0.0.1').pathname;
    if (requestPath === '/') {
      response.writeHead(200, {
        'Cache-Control': 'no-store',
        'Content-Type': 'text/html; charset=utf-8',
      });
      response.end(
        `<!doctype html><meta charset="utf-8"><title>Playback audit</title><video id="audit-video" muted playsinline preload="auto"><source src="/video" type="${contentType}"></video>`,
      );
      return;
    }
    if (requestPath !== '/video') {
      response.writeHead(404).end();
      return;
    }

    const commonHeaders = {
      'Accept-Ranges': 'bytes',
      'Cache-Control': 'no-store',
      'Content-Type': contentType,
    };
    const range = /^bytes=(\d*)-(\d*)$/.exec(request.headers.range || '');
    if (!range) {
      response.writeHead(200, {
        ...commonHeaders,
        'Content-Length': videoBuffer.length,
      });
      response.end(videoBuffer);
      return;
    }

    const requestedStart = range[1] ? Number(range[1]) : null;
    const requestedEnd = range[2] ? Number(range[2]) : null;
    const start = requestedStart === null ? Math.max(0, videoBuffer.length - Math.max(1, requestedEnd || 0)) : requestedStart;
    const end = requestedStart === null ? videoBuffer.length - 1 : Math.min(videoBuffer.length - 1, requestedEnd ?? videoBuffer.length - 1);
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || start > end || start >= videoBuffer.length) {
      response.writeHead(416, {
        ...commonHeaders,
        'Content-Range': `bytes */${videoBuffer.length}`,
      });
      response.end();
      return;
    }
    response.writeHead(206, {
      ...commonHeaders,
      'Content-Length': end - start + 1,
      'Content-Range': `bytes ${start}-${end}/${videoBuffer.length}`,
    });
    response.end(videoBuffer.subarray(start, end + 1));
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => resolve(undefined));
  });
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Playback audit server did not expose a TCP port');
  return {
    url: `http://127.0.0.1:${address.port}/`,
    close: () =>
      new Promise((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve(undefined)));
      }),
  };
}

async function auditRealTimePlayback(videoPath, videoBuffer, probe) {
  const server = await startPlaybackServer(videoPath, videoBuffer);
  let browser;
  const startedAt = new Date();
  try {
    browser = await chromium.launch({
      headless: true,
      args: ['--autoplay-policy=no-user-gesture-required'],
    });
    const page = await browser.newPage();
    const pageErrors = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    await page.goto(server.url, { waitUntil: 'domcontentloaded' });
    const video = page.locator('#audit-video');
    const metadata = await video.evaluate(
      (element) =>
        new Promise((resolve, reject) => {
          const read = () =>
            resolve({
              duration: element.duration,
              width: element.videoWidth,
              height: element.videoHeight,
              readyState: element.readyState,
            });
          if (element.readyState >= 1) {
            read();
            return;
          }
          const timeout = setTimeout(() => reject(new Error('Timed out waiting for video metadata')), 15000);
          element.addEventListener(
            'loadedmetadata',
            () => {
              clearTimeout(timeout);
              read();
            },
            { once: true },
          );
          element.addEventListener(
            'error',
            () => {
              clearTimeout(timeout);
              reject(new Error(element.error?.message || 'Browser could not load the video'));
            },
            { once: true },
          );
        }),
    );
    if (!Number.isFinite(metadata.duration) || metadata.duration <= 0) {
      throw new Error('Browser returned an invalid playback duration');
    }
    if (metadata.width !== probe.width || metadata.height !== probe.height) {
      throw new Error(`Browser playback dimensions ${metadata.width}x${metadata.height} do not match ${probe.width}x${probe.height}`);
    }
    if (Math.abs(metadata.duration * 1000 - probe.durationMs) > 120) {
      throw new Error(
        `Browser playback duration differs from FFprobe by ${Math.round(Math.abs(metadata.duration * 1000 - probe.durationMs))}ms`,
      );
    }

    await video.evaluate((element) => {
      const audit = {
        samples: [],
        seekingEvents: 0,
        rateChanges: [],
        interruptions: [],
        started: false,
        startedAt: null,
        endedAt: null,
        interval: null,
      };
      const sample = () =>
        audit.samples.push({
          mediaTime: element.currentTime,
          wallTime: performance.now(),
        });
      Reflect.set(window, '__walkthroughPlaybackAudit', audit);
      element.addEventListener('play', () => {
        if (audit.started) return;
        audit.started = true;
        audit.startedAt = performance.now();
        sample();
        audit.interval = setInterval(sample, 100);
      });
      element.addEventListener('seeking', () => {
        if (audit.started) audit.seekingEvents += 1;
      });
      element.addEventListener('ratechange', () => {
        if (audit.started)
          audit.rateChanges.push({
            at: performance.now(),
            playbackRate: element.playbackRate,
          });
      });
      for (const eventName of ['pause', 'waiting', 'stalled']) {
        element.addEventListener(eventName, () => {
          if (!audit.started || element.ended) return;
          if (eventName === 'pause' && element.currentTime >= element.duration - 0.05) return;
          audit.interruptions.push({
            event: eventName,
            at: performance.now(),
            mediaTime: element.currentTime,
          });
        });
      }
      element.addEventListener('ended', () => {
        sample();
        audit.endedAt = performance.now();
        clearInterval(audit.interval);
      });
    });

    const playbackStartedAtMs = Date.now();
    await video.evaluate(async (element) => {
      if (element.currentTime > 0.001) element.currentTime = 0;
      element.playbackRate = 1;
      await element.play();
    });
    await page.waitForFunction(
      () => {
        const element = document.querySelector('video');
        return element?.ended || Boolean(element?.error);
      },
      null,
      { timeout: Math.ceil(metadata.duration * 1000) + 30000 },
    );
    const wallClockElapsedMs = Date.now() - playbackStartedAtMs;
    const state = await video.evaluate((element) => {
      const audit = Reflect.get(window, '__walkthroughPlaybackAudit');
      const first = audit.samples[0] || null;
      const last = audit.samples.at(-1) || null;
      let nonMonotonicSamples = 0;
      let maxSampleWallGapMs = 0;
      let maxMediaWallDriftMs = 0;
      for (let index = 1; index < audit.samples.length; index += 1) {
        const previous = audit.samples[index - 1];
        const current = audit.samples[index];
        const mediaDeltaMs = (current.mediaTime - previous.mediaTime) * 1000;
        const wallDeltaMs = current.wallTime - previous.wallTime;
        if (mediaDeltaMs < -1) nonMonotonicSamples += 1;
        maxSampleWallGapMs = Math.max(maxSampleWallGapMs, wallDeltaMs);
        if (first) {
          const mediaElapsedMs = (current.mediaTime - first.mediaTime) * 1000;
          const wallElapsedMs = current.wallTime - first.wallTime;
          maxMediaWallDriftMs = Math.max(maxMediaWallDriftMs, Math.abs(mediaElapsedMs - wallElapsedMs));
        }
      }
      return {
        currentTime: element.currentTime,
        duration: element.duration,
        ended: element.ended,
        error: element.error ? { code: element.error.code, message: element.error.message } : null,
        playbackRate: element.playbackRate,
        readyState: element.readyState,
        width: element.videoWidth,
        height: element.videoHeight,
        seekingEvents: audit.seekingEvents,
        rateChanges: audit.rateChanges,
        interruptions: audit.interruptions,
        sampleCount: audit.samples.length,
        nonMonotonicSamples,
        maxSampleWallGapMs,
        maxMediaWallDriftMs,
        sampledMediaElapsedMs: first && last ? (last.mediaTime - first.mediaTime) * 1000 : 0,
        sampledWallElapsedMs: first && last ? last.wallTime - first.wallTime : 0,
        inPageElapsedMs: audit.startedAt !== null && audit.endedAt !== null ? audit.endedAt - audit.startedAt : null,
      };
    });

    const timingToleranceMs = Math.min(250, Math.max(100, probe.durationMs * 0.0025));
    const minimumElapsedMs = Math.max(0, probe.durationMs - timingToleranceMs);
    const maximumElapsedMs = probe.durationMs + timingToleranceMs;
    const minimumSamples = Math.max(3, Math.floor(probe.durationMs / 250));
    if (!state.ended || state.error) throw new Error(`Playback did not end cleanly: ${state.error?.message || 'ended event missing'}`);
    if (state.playbackRate !== 1 || state.rateChanges.length > 0) throw new Error('Playback rate changed during the 1x audit');
    if (state.seekingEvents > 0) throw new Error(`Playback seeked ${state.seekingEvents} time(s) after starting`);
    if (state.interruptions.length > 0) {
      throw new Error(`Playback was interrupted by: ${state.interruptions.map((event) => event.event).join(', ')}`);
    }
    if (state.nonMonotonicSamples > 0) throw new Error('Playback media time moved backwards');
    if (state.maxSampleWallGapMs > 500) {
      throw new Error(`Playback sampling stalled for ${Math.round(state.maxSampleWallGapMs)}ms`);
    }
    if (state.maxMediaWallDriftMs > 500) {
      throw new Error(`Playback media time drifted ${Math.round(state.maxMediaWallDriftMs)}ms from wall time`);
    }
    if (Math.abs(state.currentTime - state.duration) > 0.05) throw new Error('Playback did not reach the final media timestamp');
    if (wallClockElapsedMs < minimumElapsedMs || state.inPageElapsedMs < minimumElapsedMs) {
      throw new Error(`Playback completed too quickly (${wallClockElapsedMs}ms wall clock for ${Math.round(probe.durationMs)}ms media)`);
    }
    if (wallClockElapsedMs > maximumElapsedMs || state.inPageElapsedMs > maximumElapsedMs) {
      throw new Error(`Playback stalled (${wallClockElapsedMs}ms wall clock for ${Math.round(probe.durationMs)}ms media)`);
    }
    if (state.sampleCount < minimumSamples || state.sampledMediaElapsedMs < minimumElapsedMs) {
      throw new Error(`Playback sampling covered only ${Math.round(state.sampledMediaElapsedMs)}ms across ${state.sampleCount} samples`);
    }
    if (pageErrors.length > 0) throw new Error(`Playback page error: ${pageErrors.join('; ')}`);

    return {
      status: 'passed',
      schemaVersion: 2,
      exactVideo: {
        path: videoPath,
        sha256: probe.sha256,
        durationMs: probe.durationMs,
        width: probe.width,
        height: probe.height,
      },
      browser: {
        engine: 'chromium',
        headless: true,
      },
      playback: {
        rate: state.playbackRate,
        startedAtSeconds: 0,
        endedAtSeconds: state.currentTime,
        ended: state.ended,
        readyState: state.readyState,
        mediaError: state.error,
        seekingEvents: state.seekingEvents,
        rateChanges: state.rateChanges,
        interruptions: state.interruptions,
        sampleCount: state.sampleCount,
        nonMonotonicSamples: state.nonMonotonicSamples,
        maxSampleWallGapMs: state.maxSampleWallGapMs,
        maxMediaWallDriftMs: state.maxMediaWallDriftMs,
        sampledMediaElapsedMs: state.sampledMediaElapsedMs,
        sampledWallElapsedMs: state.sampledWallElapsedMs,
        inPageElapsedMs: state.inPageElapsedMs,
        wallClockElapsedMs,
      },
      startedAt: startedAt.toISOString(),
      completedAt: new Date().toISOString(),
    };
  } finally {
    if (browser) await browser.close();
    await server.close();
  }
}

export { auditRealTimePlayback, skillRoot };
