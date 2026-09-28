import { spawn } from 'node:child_process';
import { mkdir, readdir, rm } from 'node:fs/promises';
import path from 'node:path';

function command(commandName, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(commandName, args, { stdio: ['ignore', 'pipe', 'pipe'], ...options });
    const stdout = [];
    const stderr = [];
    child.stdout.on('data', (chunk) => stdout.push(chunk));
    child.stderr.on('data', (chunk) => stderr.push(chunk));
    child.on('error', reject);
    child.on('close', (code) => {
      const result = {
        code,
        stdout: Buffer.concat(stdout).toString('utf8'),
        stderr: Buffer.concat(stderr).toString('utf8'),
      };
      if (code !== 0) reject(new Error(result.stderr.trim() || `${commandName} exited with ${code}`));
      else resolve(result);
    });
  });
}

function finiteNumber(value, fallback, minimum = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(minimum, parsed) : fallback;
}

function runDuration(startFrame, endFrame, fps) {
  return ((endFrame - startFrame + 1) / fps) * 1000;
}

function parseHexColor(value) {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(String(value || ''));
  if (!match) return null;
  return {
    r: Number.parseInt(match[1], 16),
    g: Number.parseInt(match[2], 16),
    b: Number.parseInt(match[3], 16),
  };
}

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

function expectedPointerPosition(pointerAudit, timeMs) {
  let position = {
    x: pointerAudit.startX,
    y: pointerAudit.startY,
  };
  let visible = true;
  for (const event of pointerAudit.track) {
    if (event.kind === 'visibility') {
      if (event.atMs > timeMs) break;
      visible = event.visible !== false;
      continue;
    }
    if (event.kind === 'static') {
      if (event.atMs > timeMs) break;
      position = { x: event.x, y: event.y };
      continue;
    }
    if (event.kind !== 'move') continue;
    if (timeMs < event.startMs) break;
    if (timeMs <= event.endMs) {
      const duration = Math.max(1, event.endMs - event.startMs);
      const linearProgress = Math.max(0, Math.min(1, (timeMs - event.startMs) / duration));
      const progress = cubicBezier(linearProgress, 0.4, 0, 0.2, 1);
      return {
        x: event.from.x + (event.to.x - event.from.x) * progress,
        y: event.from.y + (event.to.y - event.from.y) * progress,
        moving: true,
        visible,
        from: event.from,
        to: event.to,
      };
    }
    position = { ...event.to };
  }
  return { ...position, moving: false, visible };
}

function pointerColorMatches(red, green, blue, target) {
  const distance = Math.hypot(red - target.r, green - target.g, blue - target.b);
  return distance <= 125 && red >= 135 && red >= green + 35 && red >= blue + 35;
}

function distanceToSegment(x, y, segment) {
  const deltaX = segment.toX - segment.fromX;
  const deltaY = segment.toY - segment.fromY;
  const lengthSquared = deltaX * deltaX + deltaY * deltaY;
  if (lengthSquared === 0) return Math.hypot(x - segment.fromX, y - segment.fromY);
  const progress = Math.max(0, Math.min(1, ((x - segment.fromX) * deltaX + (y - segment.fromY) * deltaY) / lengthSquared));
  return Math.hypot(x - (segment.fromX + deltaX * progress), y - (segment.fromY + deltaY * progress));
}

function findRingCandidate(frame, scanWidth, scanHeight, target, expectedX, expectedY, renderedSize, movementSegment) {
  const pixelCount = scanWidth * scanHeight;
  const mask = new Uint8Array(pixelCount);
  for (let index = 0; index < pixelCount; index += 1) {
    const offset = index * 3;
    if (pointerColorMatches(frame[offset], frame[offset + 1], frame[offset + 2], target)) mask[index] = 1;
  }
  const visited = new Uint8Array(pixelCount);
  const minimumDiameter = Math.max(4, renderedSize * 0.65);
  const maximumDiameter = Math.max(12, renderedSize * 1.8);
  const maximumDistance = Math.max(28, renderedSize * 10);
  let best = null;
  for (let index = 0; index < pixelCount; index += 1) {
    if (!mask[index] || visited[index]) continue;
    const stack = [index];
    visited[index] = 1;
    let count = 0;
    let minX = scanWidth;
    let maxX = 0;
    let minY = scanHeight;
    let maxY = 0;
    const points = [];
    while (stack.length > 0) {
      const current = stack.pop();
      const x = current % scanWidth;
      const y = Math.floor(current / scanWidth);
      points.push({ x, y });
      count += 1;
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
      for (let deltaY = -1; deltaY <= 1; deltaY += 1) {
        for (let deltaX = -1; deltaX <= 1; deltaX += 1) {
          if (deltaX === 0 && deltaY === 0) continue;
          const nextX = x + deltaX;
          const nextY = y + deltaY;
          if (nextX < 0 || nextX >= scanWidth || nextY < 0 || nextY >= scanHeight) continue;
          const next = nextY * scanWidth + nextX;
          if (!mask[next] || visited[next]) continue;
          visited[next] = 1;
          stack.push(next);
        }
      }
    }
    const width = maxX - minX + 1;
    const height = maxY - minY + 1;
    if (count < 6 || width < minimumDiameter || height < minimumDiameter) continue;
    if (width > maximumDiameter || height > maximumDiameter || Math.abs(width - height) > 4) continue;
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    const quadrants = [0, 0, 0, 0];
    let centerPixels = 0;
    for (const point of points) {
      const quadrant = (point.y >= centerY ? 2 : 0) + (point.x >= centerX ? 1 : 0);
      quadrants[quadrant] += 1;
      if (Math.abs(point.x - centerX) <= 1 && Math.abs(point.y - centerY) <= 1) centerPixels += 1;
    }
    if (quadrants.some((value) => value === 0) || centerPixels > 2) continue;
    const distance = Math.hypot(centerX - expectedX, centerY - expectedY);
    const pathDistance = movementSegment ? distanceToSegment(centerX, centerY, movementSegment) : distance;
    const allowedPathDistance = movementSegment ? Math.max(18, renderedSize * 4) : maximumDistance;
    if (pathDistance > allowedPathDistance) continue;
    const score = movementSegment ? pathDistance * 4 + distance * 0.05 : distance;
    if (!best || score < best.score) {
      best = {
        centerX,
        centerY,
        width,
        height,
        matchingPixels: count,
        distance,
        pathDistance,
        score,
      };
    }
  }
  return best;
}

function inspectFrame(frame, previous, pointerAudit, frameTimeMs, scanWidth, scanHeight) {
  let sum = 0;
  let min = 255;
  let max = 0;
  let lightPixels = 0;
  let darkPixels = 0;
  let difference = 0;
  const pixelCount = scanWidth * scanHeight;
  for (let offset = 0; offset < frame.length; offset += 3) {
    const red = frame[offset];
    const green = frame[offset + 1];
    const blue = frame[offset + 2];
    const luminance = (red * 77 + green * 150 + blue * 29) >> 8;
    sum += luminance;
    if (luminance < min) min = luminance;
    if (luminance > max) max = luminance;
    if (luminance >= 248) lightPixels += 1;
    if (luminance <= 7) darkPixels += 1;
    if (previous) {
      const prior = (previous[offset] * 77 + previous[offset + 1] * 150 + previous[offset + 2] * 29) >> 8;
      difference += Math.abs(luminance - prior);
    }
  }
  const mean = sum / pixelCount;
  const lightRatio = lightPixels / pixelCount;
  const darkRatio = darkPixels / pixelCount;
  let pointer = null;
  if (pointerAudit?.enabled && pointerAudit.color) {
    const expected = expectedPointerPosition(pointerAudit, frameTimeMs);
    const scaleX = scanWidth / pointerAudit.viewport.width;
    const scaleY = scanHeight / pointerAudit.viewport.height;
    const centerX = expected.x * scaleX;
    const centerY = expected.y * scaleY;
    const movementSegment = expected.moving
      ? {
          fromX: expected.from.x * scaleX,
          fromY: expected.from.y * scaleY,
          toX: expected.to.x * scaleX,
          toY: expected.to.y * scaleY,
        }
      : null;
    const baseRadius = Math.max(6, pointerAudit.size * Math.max(scaleX, scaleY) * 1.4);
    // Keep the movement tolerance narrow enough that unrelated red UI cannot satisfy it.
    const radius = expected.moving ? baseRadius * 3 : baseRadius;
    const left = Math.max(0, Math.floor(centerX - radius));
    const right = Math.min(scanWidth - 1, Math.ceil(centerX + radius));
    const top = Math.max(0, Math.floor(centerY - radius));
    const bottom = Math.min(scanHeight - 1, Math.ceil(centerY + radius));
    let matchingPixels = 0;
    for (let y = top; y <= bottom; y += 1) {
      for (let x = left; x <= right; x += 1) {
        const offset = (y * scanWidth + x) * 3;
        if (pointerColorMatches(frame[offset], frame[offset + 1], frame[offset + 2], pointerAudit.color)) {
          matchingPixels += 1;
        }
      }
    }
    const minimumMatchingPixels = Math.max(4, Math.round(pointerAudit.size * Math.max(scaleX, scaleY) * 0.75));
    let corridorMatchingPixels = 0;
    if (movementSegment) {
      const corridorRadius = baseRadius * 2;
      const corridorLeft = Math.max(0, Math.floor(Math.min(movementSegment.fromX, movementSegment.toX) - corridorRadius));
      const corridorRight = Math.min(scanWidth - 1, Math.ceil(Math.max(movementSegment.fromX, movementSegment.toX) + corridorRadius));
      const corridorTop = Math.max(0, Math.floor(Math.min(movementSegment.fromY, movementSegment.toY) - corridorRadius));
      const corridorBottom = Math.min(scanHeight - 1, Math.ceil(Math.max(movementSegment.fromY, movementSegment.toY) + corridorRadius));
      for (let y = corridorTop; y <= corridorBottom; y += 1) {
        for (let x = corridorLeft; x <= corridorRight; x += 1) {
          if (distanceToSegment(x, y, movementSegment) > corridorRadius) continue;
          const offset = (y * scanWidth + x) * 3;
          if (pointerColorMatches(frame[offset], frame[offset + 1], frame[offset + 2], pointerAudit.color)) {
            corridorMatchingPixels += 1;
          }
        }
      }
    }
    const ringCandidate = expected.moving
      ? findRingCandidate(
          frame,
          scanWidth,
          scanHeight,
          pointerAudit.color,
          centerX,
          centerY,
          pointerAudit.size * Math.max(scaleX, scaleY),
          movementSegment,
        )
      : null;
    pointer = {
      expectedX: expected.x,
      expectedY: expected.y,
      expectedVisible: expected.visible,
      moving: expected.moving,
      matchingPixels,
      corridorMatchingPixels,
      minimumMatchingPixels,
      ringCandidate,
      present: matchingPixels >= minimumMatchingPixels || corridorMatchingPixels >= minimumMatchingPixels || Boolean(ringCandidate),
    };
  }
  return {
    mean,
    range: max - min,
    lightRatio,
    darkRatio,
    blank: lightRatio >= 0.997 ? 'near-white' : darkRatio >= 0.997 ? 'near-black' : null,
    diff: previous ? difference / pixelCount : null,
    pointer,
  };
}

async function scanFrames(videoPath, probe, pointerAudit) {
  const sourceWidth = Number(probe.width);
  const sourceHeight = Number(probe.height);
  const scanWidth = Math.min(sourceWidth, pointerAudit?.enabled ? 480 : 360);
  const scanHeight = Math.max(1, Math.round((sourceHeight / sourceWidth) * scanWidth));
  const frameSize = scanWidth * scanHeight * 3;
  const fps = Number(probe.fps);
  const ffmpeg = spawn('ffmpeg', [
    '-hide_banner',
    '-loglevel',
    'error',
    '-i',
    videoPath,
    '-vf',
    `scale=${scanWidth}:${scanHeight}:flags=fast_bilinear`,
    '-pix_fmt',
    'rgb24',
    '-f',
    'rawvideo',
    '-fps_mode',
    'passthrough',
    '-',
  ]);
  const blankRuns = [];
  const staticRuns = [];
  const abruptTransitions = [];
  const pointerMissingRuns = [];
  const unexpectedPointerRuns = [];
  const diffSeries = [];
  let pending = Buffer.alloc(0);
  let frameIndex = 0;
  let previous = null;
  let blankKind = null;
  let blankStart = 0;
  let staticStart = 0;
  let staticActive = false;
  let pointerMissingStart = 0;
  let pointerMissingActive = false;
  let unexpectedPointerStart = 0;
  let unexpectedPointerActive = false;
  let pointerMotionFrames = 0;
  let maxDiff = 0;

  const inspect = (frame) => {
    frameIndex += 1;
    const frameTimeMs = ((frameIndex - 1) / fps) * 1000;
    const metrics = inspectFrame(frame, previous, pointerAudit, frameTimeMs, scanWidth, scanHeight);
    const diff = metrics.diff;
    if (diff !== null) {
      diffSeries.push({
        frame: frameIndex,
        timeMs: frameTimeMs,
        diff,
        lightRatio: metrics.lightRatio,
        darkRatio: metrics.darkRatio,
        blank: metrics.blank,
        pointerPresent: metrics.pointer?.expectedVisible ? metrics.pointer.present : null,
        unexpectedPointer: metrics.pointer?.expectedVisible === false ? metrics.pointer.present : false,
      });
      maxDiff = Math.max(maxDiff, diff);
    }
    if (metrics.blank && blankKind === metrics.blank) {
      // Continue the current blank run.
    } else if (metrics.blank) {
      if (blankKind) blankRuns.push({ kind: blankKind, startFrame: blankStart, endFrame: frameIndex - 1 });
      blankKind = metrics.blank;
      blankStart = frameIndex;
    } else if (blankKind) {
      blankRuns.push({ kind: blankKind, startFrame: blankStart, endFrame: frameIndex - 1 });
      blankKind = null;
    }
    const pointerMotion = Boolean(metrics.pointer?.moving && metrics.pointer.present);
    if (pointerMotion) pointerMotionFrames += 1;
    if (diff !== null && diff <= 1.5 && !pointerMotion) {
      if (!staticActive) {
        staticActive = true;
        staticStart = frameIndex - 1;
      }
    } else if (staticActive) {
      staticRuns.push({ startFrame: staticStart, endFrame: frameIndex - 1 });
      staticActive = false;
    }
    if (diff !== null && diff >= 55) {
      abruptTransitions.push({ frame: frameIndex, timeMs: frameTimeMs, diff });
    }
    if (metrics.pointer?.expectedVisible && !metrics.pointer.present) {
      if (!pointerMissingActive) {
        pointerMissingActive = true;
        pointerMissingStart = frameIndex;
      }
    } else if (pointerMissingActive) {
      pointerMissingRuns.push({ startFrame: pointerMissingStart, endFrame: frameIndex - 1 });
      pointerMissingActive = false;
    }
    if (metrics.pointer && !metrics.pointer.expectedVisible && metrics.pointer.present) {
      if (!unexpectedPointerActive) {
        unexpectedPointerActive = true;
        unexpectedPointerStart = frameIndex;
      }
    } else if (unexpectedPointerActive) {
      unexpectedPointerRuns.push({
        startFrame: unexpectedPointerStart,
        endFrame: frameIndex - 1,
      });
      unexpectedPointerActive = false;
    }
    previous = frame;
  };

  ffmpeg.stdout.on('data', (chunk) => {
    pending = Buffer.concat([pending, chunk]);
    while (pending.length >= frameSize) {
      const frame = pending.subarray(0, frameSize);
      inspect(frame);
      pending = pending.subarray(frameSize);
    }
  });
  const stderr = [];
  ffmpeg.stderr.on('data', (chunk) => stderr.push(chunk));
  const exitCode = await new Promise((resolve, reject) => {
    ffmpeg.on('error', reject);
    ffmpeg.on('close', resolve);
  });
  if (exitCode !== 0) throw new Error(Buffer.concat(stderr).toString('utf8') || 'FFmpeg could not decode the video');
  if (pending.length !== 0) throw new Error(`Video ended with an incomplete frame (${pending.length} bytes)`);
  if (blankKind) blankRuns.push({ kind: blankKind, startFrame: blankStart, endFrame: frameIndex });
  if (staticActive) staticRuns.push({ startFrame: staticStart, endFrame: frameIndex });
  if (pointerMissingActive) pointerMissingRuns.push({ startFrame: pointerMissingStart, endFrame: frameIndex });
  if (unexpectedPointerActive) unexpectedPointerRuns.push({ startFrame: unexpectedPointerStart, endFrame: frameIndex });
  return {
    summary: {
      scannedEveryFrame: true,
      framesScanned: frameIndex,
      scanResolution: `${scanWidth}x${scanHeight}`,
      blankRuns,
      staticRuns: staticRuns.map((run) => ({
        ...run,
        durationMs: runDuration(run.startFrame, run.endFrame, fps),
      })),
      abruptTransitionCount: abruptTransitions.length,
      abruptTransitions: abruptTransitions.slice(0, 200),
      pointerMissingRuns: pointerMissingRuns.map((run) => ({
        ...run,
        durationMs: runDuration(run.startFrame, run.endFrame, fps),
      })),
      unexpectedPointerRuns: unexpectedPointerRuns.map((run) => ({
        ...run,
        durationMs: runDuration(run.startFrame, run.endFrame, fps),
      })),
      pointerMotionFrames,
      maxFrameDiff: maxDiff,
    },
    diffSeries,
  };
}

async function createContactSheets(videoPath, outputDir, contactFps) {
  const existingFiles = await readdir(outputDir);
  await Promise.all(
    existingFiles.filter((name) => /^contact-sheet-\d+\.jpg$/.test(name)).map((name) => rm(path.join(outputDir, name), { force: true })),
  );
  const pattern = path.join(outputDir, 'contact-sheet-%03d.jpg');
  await command('ffmpeg', [
    '-y',
    '-hide_banner',
    '-loglevel',
    'error',
    '-i',
    videoPath,
    '-vf',
    `fps=${contactFps},scale=360:-1:flags=lanczos,tile=4x5`,
    '-q:v',
    '3',
    '-f',
    'image2',
    pattern,
  ]);
  return pattern;
}

async function createOpeningSheet(videoPath, outputDir, durationMs) {
  const output = path.join(outputDir, 'opening-review-10fps.jpg');
  await command('ffmpeg', [
    '-y',
    '-hide_banner',
    '-loglevel',
    'error',
    '-t',
    String(Math.max(1, durationMs / 1000)),
    '-i',
    videoPath,
    '-vf',
    'fps=10,scale=432:-1:flags=lanczos,tile=5x6',
    '-frames:v',
    '1',
    output,
  ]);
  return output;
}

async function createActionSheets(videoPath, outputDir, timeline) {
  const actionDir = path.join(outputDir, 'action-review-10fps');
  await rm(actionDir, { recursive: true, force: true });
  await mkdir(actionDir, { recursive: true });
  const sheets = [];
  for (const step of timeline) {
    const startMs = Math.max(0, finiteNumber(step.startMs, 0) - 200);
    const actionEndMs = Math.max(startMs, finiteNumber(step.actionEndMs, startMs));
    const stepEndMs = Math.max(actionEndMs, finiteNumber(step.endMs, actionEndMs));
    const endMs = Math.min(stepEndMs, actionEndMs + 600);
    const durationMs = Math.max(500, endMs - startMs);
    const expectedFrames = Math.max(1, Math.ceil(durationMs / 100));
    const columns = Math.min(5, expectedFrames);
    const rows = expectedFrames <= 30 ? Math.ceil(expectedFrames / columns) : 6;
    const prefix = `step-${String(step.index).padStart(3, '0')}`;
    const pattern = path.join(actionDir, `${prefix}-%03d.jpg`);
    await command('ffmpeg', [
      '-y',
      '-hide_banner',
      '-loglevel',
      'error',
      '-ss',
      String(startMs / 1000),
      '-t',
      String(durationMs / 1000),
      '-i',
      videoPath,
      '-vf',
      `fps=10,scale=432:-1:flags=lanczos,tile=${columns}x${rows}:padding=4:margin=4:color=white`,
      '-q:v',
      '3',
      '-f',
      'image2',
      pattern,
    ]);
    sheets.push({
      step: step.index,
      label: step.label,
      startMs,
      endMs: startMs + durationMs,
      pattern,
    });
  }
  return {
    directory: actionDir,
    fps: 10,
    sheets,
  };
}

async function probeTimestamps(videoPath) {
  const result = await command('ffprobe', [
    '-v',
    'error',
    '-select_streams',
    'v:0',
    '-show_entries',
    'frame=best_effort_timestamp_time',
    '-of',
    'csv=p=0',
    videoPath,
  ]);
  const timestamps = result.stdout
    .split(/\r?\n/)
    .map((value) => value.trim())
    .filter(Boolean)
    .map(Number)
    .filter(Number.isFinite);
  let monotonic = true;
  for (let index = 1; index < timestamps.length; index += 1) {
    if (timestamps[index] < timestamps[index - 1]) {
      monotonic = false;
      break;
    }
  }
  return {
    framesWithTimestamps: timestamps.length,
    monotonic,
    firstTimestamp: timestamps[0] ?? null,
    lastTimestamp: timestamps.at(-1) ?? null,
  };
}

export {
  command,
  createActionSheets,
  createContactSheets,
  createOpeningSheet,
  finiteNumber,
  parseHexColor,
  probeTimestamps,
  runDuration,
  scanFrames,
};
