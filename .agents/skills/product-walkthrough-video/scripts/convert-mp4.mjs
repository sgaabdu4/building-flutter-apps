import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

const skillRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
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

function sha256(buffer) {
  return createHash('sha256').update(buffer).digest('hex');
}

function assertPlaybackEvidence(review) {
  const evidence = review.playbackEvidence;
  const exactVideo = evidence?.exactVideo;
  const expectedVideo = review.video;
  if (
    evidence?.status !== 'passed' ||
    evidence.schemaVersion !== 2 ||
    !expectedVideo ||
    exactVideo?.sha256 !== expectedVideo.sha256 ||
    exactVideo.width !== expectedVideo.width ||
    exactVideo.height !== expectedVideo.height ||
    !Number.isFinite(exactVideo.durationMs) ||
    Math.abs(exactVideo.durationMs - expectedVideo.durationMs) > 1
  ) {
    throw new Error("Source playback evidence is not bound to the approved video's hash, dimensions, and duration");
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
    throw new Error('Source playback evidence does not prove uninterrupted, no-seek playback at 1x through ended');
  }
  if (!/^[a-f0-9]{64}$/.test(review.runReportSha256 || '')) {
    throw new Error('Source review is not bound to a journey run-report hash');
  }
}

async function probe(videoPath) {
  const result = await command('ffprobe', [
    '-v',
    'error',
    '-select_streams',
    'v:0',
    '-show_entries',
    'format=duration,size:stream=codec_name,width,height,pix_fmt,avg_frame_rate',
    '-of',
    'json',
    videoPath,
  ]);
  const payload = JSON.parse(result.stdout);
  const stream = (payload.streams || [])[0];
  if (!stream) throw new Error(`No video stream found in ${videoPath}`);
  return {
    codec: stream.codec_name,
    pixelFormat: stream.pix_fmt || null,
    width: Number(stream.width),
    height: Number(stream.height),
    frameRate: stream.avg_frame_rate,
    durationMs: Number(payload.format?.duration || 0) * 1000,
    sizeBytes: Number(payload.format?.size || 0),
  };
}

async function validateRunReportBinding(review, inputPath) {
  if (!review.runReport || !/^[a-f0-9]{64}$/.test(review.runReportSha256 || '')) {
    throw new Error('Source review is not bound to a complete journey run report');
  }
  const runReportPath = path.resolve(review.runReport);
  const runReportBuffer = await readFile(runReportPath);
  if (sha256(runReportBuffer) !== review.runReportSha256) {
    throw new Error("Source review's journey run report no longer matches its recorded hash");
  }
  const runReport = JSON.parse(runReportBuffer.toString('utf8'));
  if (runReport.status !== 'passed' || runReport.error) {
    throw new Error('Source journey run report is not passed and error-free');
  }
  if (runReport.findings?.some((finding) => finding.severity === 'error')) {
    throw new Error('Source journey run report contains error findings');
  }
  if (runReport.sensitiveFindings?.length) {
    throw new Error('Source journey run report contains sensitive-data findings');
  }
  if (!runReport.videoPath || path.resolve(runReport.videoPath) !== inputPath) {
    throw new Error('Source journey run report does not identify the input WebM');
  }
  return runReport;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.input || !args.output || !args.review || args.input === true || args.output === true || args.review === true) {
    throw new Error('Usage: convert-mp4.mjs --input /path/input.webm --review /path/passed-video-review.json --output /path/output.mp4');
  }
  const inputPath = path.resolve(String(args.input));
  const outputPath = path.resolve(String(args.output));
  const reviewPath = path.resolve(String(args.review));
  const review = JSON.parse(await readFile(reviewPath, 'utf8'));
  if (review.status !== 'passed' || review.humanReviewApproved !== true || review.reviewingRecordedSource !== true) {
    throw new Error(
      'Source video review must be passed, explicitly approved, and backed by exact-file real-time playback evidence before MP4 conversion',
    );
  }
  assertPlaybackEvidence(review);
  const runReport = await validateRunReportBinding(review, inputPath);
  const inputBuffer = await readFile(inputPath);
  const inputHash = sha256(inputBuffer);
  if (!review.video?.sha256 || review.video.sha256 !== inputHash) {
    throw new Error('Source video does not match the approved review SHA-256');
  }
  const source = await probe(inputPath);
  if (
    source.width !== review.video.width ||
    source.height !== review.video.height ||
    Math.abs(source.durationMs - review.video.durationMs) > 1
  ) {
    throw new Error('Source video metadata does not match the approved review');
  }
  await command('ffmpeg', [
    '-y',
    '-hide_banner',
    '-loglevel',
    'error',
    '-i',
    inputPath,
    '-map',
    '0:v:0',
    '-c:v',
    'libx264',
    '-preset',
    'slow',
    '-crf',
    '18',
    '-pix_fmt',
    'yuv420p',
    '-movflags',
    '+faststart',
    '-an',
    outputPath,
  ]);
  await command('ffmpeg', ['-v', 'error', '-i', outputPath, '-f', 'null', '-']);
  const output = await probe(outputPath);
  if (output.codec !== 'h264') throw new Error(`Expected H.264 output, received ${output.codec}`);
  if (output.pixelFormat !== 'yuv420p') throw new Error(`Expected yuv420p output, received ${output.pixelFormat}`);
  if (output.width !== source.width || output.height !== source.height) {
    throw new Error(`Output dimensions ${output.width}x${output.height} do not match source ${source.width}x${source.height}`);
  }
  if (Math.abs(output.durationMs - source.durationMs) > 120) {
    throw new Error(`Output duration differs from source by ${Math.round(Math.abs(output.durationMs - source.durationMs))}ms`);
  }
  const outputBuffer = await readFile(outputPath);
  const manifest = {
    status: 'converted',
    skill: runReport.skill || review.skill || null,
    converterSkill: {
      name: skillPackage.name,
      version: skillPackage.version,
    },
    source: {
      path: inputPath,
      sha256: inputHash,
      approvedReview: reviewPath,
      video: source,
    },
    output: {
      path: outputPath,
      sha256: sha256(outputBuffer),
      video: output,
    },
    settings: {
      codec: 'libx264',
      preset: 'slow',
      crf: 18,
      pixelFormat: 'yuv420p',
      faststart: true,
      audio: false,
    },
    finalReviewRequired: true,
    completedAt: new Date().toISOString(),
  };
  const manifestPath = `${outputPath.replace(/\.mp4$/i, '')}-delivery.json`;
  await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(manifest, null, 2));
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
