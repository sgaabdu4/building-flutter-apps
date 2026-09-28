import { createHash } from 'node:crypto';
import { access, mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import {
  command,
  createActionSheets,
  createContactSheets,
  createOpeningSheet,
  finiteNumber,
  parseHexColor,
  probeTimestamps,
  runDuration,
  scanFrames,
} from './review-frames.mjs';
import { auditRealTimePlayback, skillRoot } from './review-playback.mjs';
import { auditStepInputEvidence } from './walkthrough-input.mjs';

const skillPackage = JSON.parse(await readFile(path.join(skillRoot, 'package.json'), 'utf8'));

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith('--')) continue;
    const key = token.slice(2);
    const next = argv[index + 1];
    args[key] = next && !next.startsWith('--') ? next : true;
    if (args[key] !== true) index += 1;
  }
  return args;
}

function assertPlaybackEvidence(evidence, expectedVideo, label = 'Playback evidence') {
  if (evidence?.status !== 'passed' || evidence.schemaVersion !== 2) {
    throw new Error(`${label} is missing passed schema-version-2 playback evidence`);
  }
  const exactVideo = evidence.exactVideo;
  if (
    exactVideo?.sha256 !== expectedVideo.sha256 ||
    exactVideo.width !== expectedVideo.width ||
    exactVideo.height !== expectedVideo.height ||
    !Number.isFinite(exactVideo.durationMs) ||
    Math.abs(exactVideo.durationMs - expectedVideo.durationMs) > 1
  ) {
    throw new Error(`${label} is not bound to the reviewed video's hash, dimensions, and duration`);
  }
  const playback = evidence.playback;
  if (
    playback?.rate !== 1 ||
    playback.ended !== true ||
    playback.mediaError !== null ||
    playback.seekingEvents !== 0 ||
    !Array.isArray(playback.rateChanges) ||
    playback.rateChanges.length !== 0 ||
    !Array.isArray(playback.interruptions) ||
    playback.interruptions.length !== 0 ||
    playback.nonMonotonicSamples !== 0
  ) {
    throw new Error(`${label} does not prove uninterrupted, no-seek playback at 1x through ended`);
  }
}

function parseRate(value) {
  const [numerator, denominator] = String(value || '0/1')
    .split('/')
    .map(Number);
  return denominator ? numerator / denominator : 0;
}

function analyzeOpening(diffSeries, openingStableMs, fps) {
  const samples = diffSeries.filter((sample) => sample.timeMs <= openingStableMs);
  const unstable = samples.filter((sample) => sample.diff >= 8);
  const minimumComparedFrames = Math.max(1, Math.floor((openingStableMs / 1000) * fps * 0.9));
  return {
    durationMs: openingStableMs,
    comparedFrames: samples.length,
    minimumComparedFrames,
    highChangeFrames: unstable.length,
    maxDiff: samples.reduce((maximum, sample) => Math.max(maximum, sample.diff), 0),
    stable: samples.length >= minimumComparedFrames && unstable.length === 0,
  };
}

function analyzeScroll(step, diffSeries) {
  const samples = diffSeries.filter((sample) => sample.timeMs >= step.startMs && sample.timeMs <= step.actionEndMs);
  const active = samples.filter((sample) => sample.diff > 1.5);
  const maximum = samples.reduce((value, sample) => Math.max(value, sample.diff), 0);
  const noOp = step.metadata?.smoothTargetScroll === true && finiteNumber(step.metadata?.scrollDistancePx, 0) < 4;
  return {
    step: step.index,
    label: step.label,
    durationMs: step.actionDurationMs,
    frames: samples.length,
    activeFrames: active.length,
    activeRatio: samples.length ? active.length / samples.length : 0,
    maxDiff: maximum,
    noOp,
    smooth: !noOp && step.actionDurationMs >= 600 && active.length >= Math.max(4, Math.floor(samples.length * 0.35)),
  };
}

function analyzeDrag(step, diffSeries, pointerTrack, pointerMissingFailMs) {
  const dragStartMs = finiteNumber(step.metadata?.dragStartMs, step.startMs);
  const dragEndMs = finiteNumber(step.metadata?.dragEndMs, step.actionEndMs);
  const samples = diffSeries.filter((sample) => sample.timeMs >= dragStartMs && sample.timeMs <= dragEndMs);
  const active = samples.filter((sample) => sample.diff > 0.35);
  const pointerMissing = samples.filter((sample) => sample.pointerPresent === false);
  const durationMs = Math.max(0, dragEndMs - dragStartMs);
  const distancePx = finiteNumber(step.metadata?.distancePx, 0);
  const pressedMoves = (pointerTrack || []).filter(
    (event) => event.kind === 'move' && event.pressed === true && event.startMs <= dragEndMs + 20 && event.endMs >= dragStartMs - 20,
  );
  const trackedDistancePx = pressedMoves.reduce(
    (total, event) => total + Math.hypot(event.to.x - event.from.x, event.to.y - event.from.y),
    0,
  );
  const trackedDurationMs = pressedMoves.reduce((total, event) => total + Math.max(0, event.endMs - event.startMs), 0);
  const minimumFrames = Math.max(4, Math.floor((durationMs / 1000) * 20));
  const sampleIntervalMs = samples.length > 1 ? (samples.at(-1).timeMs - samples[0].timeMs) / (samples.length - 1) : 40;
  const pointerMissingDurationMs = pointerMissing.length * sampleIntervalMs;
  return {
    step: step.index,
    label: step.label,
    durationMs,
    distancePx,
    frames: samples.length,
    minimumFrames,
    activeFrames: active.length,
    activeRatio: samples.length ? active.length / samples.length : 0,
    pressedMoveSegments: pressedMoves.length,
    trackedDurationMs,
    trackedDistancePx,
    pointerMissingFrames: pointerMissing.map(({ frame, timeMs }) => ({ frame, timeMs })),
    pointerMissingDurationMs,
    pointerMissingFailMs,
    smooth:
      durationMs >= 600 &&
      distancePx >= 4 &&
      samples.length >= minimumFrames &&
      pressedMoves.length > 0 &&
      trackedDurationMs >= durationMs * 0.9 &&
      trackedDistancePx >= distancePx * 0.9 &&
      pointerMissingDurationMs < pointerMissingFailMs,
  };
}

function analyzeNavigation(step, diffSeries) {
  const navigationStartMs = finiteNumber(step.metadata?.navigationStartMs, step.startMs);
  const navigationEndMs = finiteNumber(step.metadata?.navigationEndMs, step.actionEndMs);
  const preNavigationMs = step.metadata?.visualContinuityGuard ? 80 : 250;
  const windowStartMs = Math.max(0, navigationStartMs - preNavigationMs);
  const windowEndMs = Math.max(windowStartMs, navigationEndMs + 300);
  const samples = diffSeries.filter((sample) => sample.timeMs >= windowStartMs && sample.timeMs <= windowEndMs);
  const abruptFrames = samples.filter((sample) => sample.diff >= 55);
  const blankFrames = samples.filter((sample) => sample.blank);
  const pointerMissingFrames = samples.filter((sample) => sample.pointerPresent === false);
  const allowedAbruptFrames = step.action === 'reload' ? 0 : 1;
  return {
    step: step.index,
    label: step.label,
    action: step.action,
    navigationStartMs,
    navigationEndMs,
    preNavigationMs,
    windowStartMs,
    windowEndMs,
    frames: samples.length,
    abruptFrames: abruptFrames.map(({ frame, timeMs, diff }) => ({ frame, timeMs, diff })),
    blankFrames: blankFrames.map(({ frame, timeMs, blank }) => ({ frame, timeMs, blank })),
    pointerMissingFrames: pointerMissingFrames.map(({ frame, timeMs }) => ({ frame, timeMs })),
    allowedAbruptFrames,
    clean: abruptFrames.length <= allowedAbruptFrames && blankFrames.length === 0 && pointerMissingFrames.length === 0,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.video || args.video === true || !args.timeline || args.timeline === true) {
    throw new Error(
      'Usage: review-video.mjs --video /path/video.webm --timeline /path/run-report.json [--derived-from /path/passed-source-review.json] [--report /path/report.json] [--approve --reviewer NAME --notes TEXT]',
    );
  }
  const videoPath = path.resolve(String(args.video));
  const outputDir = path.resolve(String(args['output-dir'] || path.join(path.dirname(videoPath), 'video-review')));
  const reportPath = path.resolve(String(args.report || path.join(outputDir, 'video-review.json')));
  const timelinePath = path.resolve(String(args.timeline));
  const derivedFromPath = args['derived-from'] && args['derived-from'] !== true ? path.resolve(String(args['derived-from'])) : null;
  const humanApproved = Boolean(args.approve);
  const reviewer = args.reviewer && args.reviewer !== true ? String(args.reviewer).trim() : '';
  const approvalNotes = args.notes && args.notes !== true ? String(args.notes).trim() : '';
  if (humanApproved && (!reviewer || approvalNotes.length < 20)) {
    throw new Error('--approve requires --reviewer and descriptive --notes of at least 20 characters');
  }
  await mkdir(outputDir, { recursive: true });

  const runReportBuffer = await readFile(timelinePath);
  const runReportSha256 = createHash('sha256').update(runReportBuffer).digest('hex');
  const runReport = JSON.parse(runReportBuffer.toString('utf8'));
  if (Array.isArray(runReport) || !Array.isArray(runReport.timeline)) {
    throw new Error(`--timeline must point to the complete run report, not a bare timeline: ${timelinePath}`);
  }
  if (runReport.error) throw new Error(`Run report contains an error: ${runReport.error}`);
  if (runReport.findings?.some((finding) => finding.severity === 'error')) {
    throw new Error('Run report contains error findings; refusing video approval');
  }
  const timeline = runReport.timeline;

  const probeResult = await command('ffprobe', [
    '-v',
    'error',
    '-select_streams',
    'v:0',
    '-show_entries',
    'format=duration,size:stream=codec_name,width,height,pix_fmt,avg_frame_rate,nb_frames',
    '-of',
    'json',
    videoPath,
  ]);
  const probeJson = JSON.parse(probeResult.stdout);
  const stream = (probeJson.streams || [])[0];
  if (!stream) throw new Error('No video stream found');
  const videoBuffer = await readFile(videoPath);
  const probe = {
    durationMs: Number(probeJson.format?.duration || 0) * 1000,
    sizeBytes: Number(probeJson.format?.size || 0),
    sha256: createHash('sha256').update(videoBuffer).digest('hex'),
    codec: stream.codec_name,
    pixelFormat: stream.pix_fmt || null,
    width: Number(stream.width),
    height: Number(stream.height),
    fps: parseRate(stream.avg_frame_rate),
    declaredFrames: stream.nb_frames ? Number(stream.nb_frames) : null,
  };
  if (!probe.fps || !probe.width || !probe.height) throw new Error('Video probe returned invalid dimensions or frame rate');

  const recordedSourcePath = runReport.videoPath ? path.resolve(runReport.videoPath) : null;
  const reviewingRecordedSource = recordedSourcePath === videoPath;
  let derivedFrom = null;
  if (!reviewingRecordedSource) {
    if (!derivedFromPath) {
      throw new Error('Reviewing a derived video requires --derived-from pointing to the passed source-WebM review');
    }
    const sourceReview = JSON.parse(await readFile(derivedFromPath, 'utf8'));
    if (
      sourceReview.status !== 'passed' ||
      sourceReview.humanReviewApproved !== true ||
      sourceReview.playbackEvidence?.status !== 'passed'
    ) {
      throw new Error('Derived video review requires a passed source review with exact-file real-time playback evidence');
    }
    if (!recordedSourcePath) throw new Error('Run report does not identify the recorded source video');
    const recordedSourceHash = createHash('sha256')
      .update(await readFile(recordedSourcePath))
      .digest('hex');
    if (sourceReview.video?.sha256 !== recordedSourceHash) {
      throw new Error("Approved source review does not match the run report's recorded WebM");
    }
    assertPlaybackEvidence(sourceReview.playbackEvidence, sourceReview.video, 'Approved source review');
    if (sourceReview.runReportSha256 !== runReportSha256) {
      throw new Error('Approved source review is not bound to the current journey run report');
    }
    if (!sourceReview.runReport) throw new Error('Approved source review does not reference its complete run report');
    const sourceRunReportHash = createHash('sha256')
      .update(await readFile(path.resolve(sourceReview.runReport)))
      .digest('hex');
    if (sourceRunReportHash !== sourceReview.runReportSha256) {
      throw new Error("Approved source review's journey run report no longer matches its recorded hash");
    }
    derivedFrom = {
      reviewPath: derivedFromPath,
      sourceVideoPath: recordedSourcePath,
      sourceVideoSha256: recordedSourceHash,
      runReportSha256,
      skill: runReport.skill || null,
    };
  } else if (derivedFromPath) {
    throw new Error('--derived-from is only valid when reviewing a converted or otherwise derived video');
  }

  if (runReport.status !== 'passed') throw new Error(`Run report status is ${runReport.status || 'missing'}; refusing video approval`);
  if (runReport.sensitiveFindings?.length) throw new Error('Run report contains sensitive-data findings; refusing video approval');
  if (runReport.pointer?.enabled && (!Array.isArray(runReport.pointerTrack) || runReport.pointerTrack.length === 0)) {
    throw new Error('Run report enables the pointer but does not contain a pointer trajectory');
  }

  const pointerAudit = runReport?.pointer?.enabled
    ? {
        enabled: true,
        color: parseHexColor(runReport.pointer.color),
        size: Number(runReport.pointer.size || 20),
        startX: Number(runReport.pointer.startX || 0),
        startY: Number(runReport.pointer.startY || 0),
        viewport: runReport.recording?.viewport || { width: probe.width, height: probe.height },
        track: Array.isArray(runReport.pointerTrack) ? runReport.pointerTrack : [],
      }
    : null;
  const { summary: frameScan, diffSeries } = await scanFrames(videoPath, probe, pointerAudit);
  const timestampAudit = await probeTimestamps(videoPath);

  const minReadableHoldMs = finiteNumber(args['min-readable-hold-ms'] ?? runReport?.thresholds?.minReadableHoldMs, 900);
  const maxStaticMs = finiteNumber(args['max-static-ms'] ?? runReport?.thresholds?.maxStaticMs, 7000);
  const pointerMissingFailMs = finiteNumber(runReport?.thresholds?.pointerMissingFailMs, 160);
  const openingStableMs = finiteNumber(runReport?.thresholds?.openingStableMs, 800);
  const findings = [];
  const addFinding = (severity, kind, detail) => findings.push({ severity, kind, detail });

  if (!timestampAudit.monotonic) addFinding('error', 'non-monotonic-timestamps', 'Video frame timestamps are not monotonic');
  const expectedJourneyEndMs = finiteNumber(runReport.recording?.journeyEndMs, timeline.at(-1)?.endMs || 0);
  if (probe.durationMs + 80 < expectedJourneyEndMs) {
    addFinding(
      'error',
      'truncated-video',
      `Video ends at ${Math.round(probe.durationMs)}ms but the journey reaches ${Math.round(expectedJourneyEndMs)}ms`,
    );
  }
  const expectedDecodedFrames = Math.floor((probe.durationMs / 1000) * probe.fps);
  if (frameScan.framesScanned < expectedDecodedFrames * 0.98) {
    addFinding(
      'error',
      'incomplete-frame-decode',
      `Decoded ${frameScan.framesScanned} of approximately ${expectedDecodedFrames} expected frames`,
    );
  }
  for (const run of frameScan.blankRuns) {
    const durationMs = runDuration(run.startFrame, run.endFrame, probe.fps);
    addFinding('error', 'blank-frame-run', `${run.kind} from frame ${run.startFrame} to ${run.endFrame} (${Math.round(durationMs)}ms)`);
  }
  for (const run of frameScan.staticRuns) {
    if (run.durationMs >= maxStaticMs)
      addFinding(
        'error',
        'long-static-run',
        `Frames ${run.startFrame}-${run.endFrame} show no page or pointer motion for ${Math.round(run.durationMs)}ms`,
      );
  }
  for (const run of frameScan.pointerMissingRuns) {
    if (run.durationMs >= pointerMissingFailMs) {
      addFinding(
        'error',
        'pointer-missing-run',
        `Expected pointer was not detected from frame ${run.startFrame} to ${run.endFrame} (${Math.round(run.durationMs)}ms)`,
      );
    }
  }
  for (const run of frameScan.unexpectedPointerRuns || []) {
    if (run.durationMs >= pointerMissingFailMs) {
      addFinding(
        'error',
        'unexpected-pointer-during-keyboard',
        `Pointer remained visible while keyboard evidence hid it from frame ${run.startFrame} to ${run.endFrame} (${Math.round(run.durationMs)}ms)`,
      );
    }
  }
  if (frameScan.abruptTransitionCount > 20) {
    addFinding('warning', 'high-transition-count', `${frameScan.abruptTransitionCount} high-motion transitions were detected`);
  }

  const openingAudit = analyzeOpening(diffSeries, openingStableMs, probe.fps);
  if (!openingAudit.stable) {
    addFinding(
      'error',
      'unstable-opening',
      `Opening compared ${openingAudit.comparedFrames}/${openingAudit.minimumComparedFrames} required frames and found ${openingAudit.highChangeFrames} high-change frames`,
    );
  }

  const scrollAudits = [];
  const gestureAudits = [];
  const navigationAudits = [];
  const inputAudits = [];
  if (timeline) {
    for (const step of timeline) {
      if (!step.ok) addFinding('error', 'scenario-step-failed', `Step ${step.index}: ${step.error || step.label}`);
      if (step.holdMs < minReadableHoldMs && step.action !== 'pause') {
        addFinding('error', 'unreadable-step-hold', `Step ${step.index} "${step.label}" held for ${step.holdMs}ms`);
      }
      const inputAudit = auditStepInputEvidence(step, {
        pointerEnabled: runReport.pointer?.enabled === true,
      });
      if (inputAudit.required) {
        inputAudits.push(inputAudit);
        for (const finding of inputAudit.findings) {
          addFinding('error', finding.kind, `Step ${step.index} "${step.label}": ${finding.detail}`);
        }
      }
      if (step.action === 'scroll') {
        const audit = analyzeScroll(step, diffSeries);
        scrollAudits.push(audit);
        if (audit.noOp) {
          addFinding('error', 'scroll-no-op', `Step ${step.index} "${step.label}" produced no visible scroll or zoom result`);
        } else if (!audit.smooth) {
          addFinding(
            'error',
            'non-smooth-scroll',
            `Step ${step.index} "${step.label}" changed across ${audit.activeFrames}/${audit.frames} frames in ${Math.round(audit.durationMs)}ms`,
          );
        }
      }
      if (step.action === 'drag') {
        const audit = analyzeDrag(step, diffSeries, pointerAudit?.track, pointerMissingFailMs);
        gestureAudits.push(audit);
        if (!audit.smooth) {
          addFinding(
            'error',
            'non-smooth-gesture',
            `Step ${step.index} "${step.label}" moved ${Math.round(audit.distancePx)}px across ${audit.frames} frames in ${Math.round(audit.durationMs)}ms with ${Math.round(audit.pointerMissingDurationMs)}ms of pointer-detection gaps`,
          );
        }
      }
      if (['goto', 'reload', 'back', 'forward'].includes(step.action) && step.bootstrappedBeforeRecording !== true) {
        const audit = analyzeNavigation(step, diffSeries);
        navigationAudits.push(audit);
        if (!audit.clean) {
          addFinding(
            'error',
            'navigation-flash',
            `Step ${step.index} "${step.label}" contained ${audit.abruptFrames.length} abrupt, ${audit.blankFrames.length} blank, and ${audit.pointerMissingFrames.length} pointer-missing frame(s) around navigation`,
          );
        }
      }
      if (!step.checkpoint) {
        addFinding('error', 'checkpoint-missing', `Step ${step.index} does not declare a checkpoint`);
      } else {
        const checkpointPath = path.join(runReport.outputDir, 'step-checkpoints', step.checkpoint);
        try {
          await access(checkpointPath);
        } catch {
          addFinding('error', 'checkpoint-missing', `Step ${step.index} checkpoint is missing: ${step.checkpoint}`);
        }
      }
    }
  }

  let contactSheetPattern;
  let openingSheet;
  let actionSheets;
  try {
    contactSheetPattern = await createContactSheets(videoPath, outputDir, finiteNumber(args['contact-fps'], 2, 0.1));
    openingSheet = await createOpeningSheet(videoPath, outputDir, Math.max(3000, openingStableMs));
    actionSheets = await createActionSheets(videoPath, outputDir, timeline);
  } catch (error) {
    addFinding('error', 'inspection-sheet-failed', error.message);
  }

  let playbackEvidence = null;
  if (humanApproved && !findings.some((finding) => finding.severity === 'error')) {
    try {
      playbackEvidence = await auditRealTimePlayback(videoPath, videoBuffer, probe);
      assertPlaybackEvidence(playbackEvidence, probe);
    } catch (error) {
      playbackEvidence = {
        status: 'failed',
        exactVideo: {
          path: videoPath,
          sha256: probe.sha256,
        },
        error: error.message,
        completedAt: new Date().toISOString(),
      };
      addFinding('error', 'real-time-playback-failed', error.message);
    }
  }
  const hasErrors = findings.some((finding) => finding.severity === 'error');
  const approvalSucceeded = humanApproved && !hasErrors && playbackEvidence?.status === 'passed';
  const report = {
    status: hasErrors ? 'failed' : approvalSucceeded ? 'passed' : 'review-required',
    skill: runReport.skill || null,
    reviewerSkill: {
      name: skillPackage.name,
      version: skillPackage.version,
    },
    video: probe,
    runReport: timelinePath,
    runReportSha256,
    reviewingRecordedSource,
    derivedFrom,
    timestamps: timestampAudit,
    frameScan,
    openingAudit,
    scrollAudits,
    gestureAudits,
    navigationAudits,
    inputAudits,
    thresholds: {
      minReadableHoldMs,
      maxStaticMs,
      blankRunFailMs: Math.round(1000 / probe.fps),
      pointerMissingFailMs,
      openingStableMs,
      minSmoothScrollMs: 600,
      maxReloadAbruptFrames: 0,
      maxRouteNavigationAbruptFrames: 1,
    },
    findings,
    playbackEvidence,
    contactSheetPattern: contactSheetPattern || null,
    openingSheet: openingSheet || null,
    actionSheets: actionSheets || null,
    stepCheckpointDirectory: runReport ? path.join(runReport.outputDir, 'step-checkpoints') : null,
    humanReviewRequested: humanApproved,
    humanReviewRequired: !approvalSucceeded,
    humanReviewApproved: approvalSucceeded,
    reviewer: approvalSucceeded ? reviewer : null,
    approvalNotes: approvalSucceeded ? approvalNotes : null,
    humanReviewChecklist: [
      'Watch the final deliverable from the first frame through the end at 1x without timestamp skipping; approval independently proves exact-file real-time playback.',
      'Inspect the 10fps opening sheet and confirm the first frame is fully rendered with no flash, reload, or layout shift.',
      'Inspect every generated contact sheet, every 10fps action sheet, and every per-step checkpoint.',
      'Confirm the pointer remains the same size, style, and position across every full-document navigation.',
      'Confirm every pointer activation lands on its control and every keyboard activation shows focus and a key cue without an unrelated pointer.',
      'Confirm each scroll is gradual, single-direction, and free from jumps, bounce, or dancing.',
      'Confirm each visible state follows the intended product journey and every action has a visible result.',
      'Confirm no unexpected popups, downloads, external navigation, data exposure, or visual glitches are present.',
    ],
    reviewedAt: new Date().toISOString(),
  };
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(report, null, 2));
  if (report.status === 'failed') process.exitCode = 1;
  else if (report.status === 'review-required') process.exitCode = 2;
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
