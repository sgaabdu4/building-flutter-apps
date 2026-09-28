import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

export const run = (cmd, args, options = {}) => execFileSync(cmd, args, { maxBuffer: 1 << 30, ...options });

export const seconds = (file) =>
  parseFloat(run('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file]).toString());

export const size = (file) =>
  run('ffprobe', ['-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', file])
    .toString()
    .trim()
    .split(',')
    .slice(0, 2)
    .map(Number);

export const clipSource = (board, clip) =>
  JSON.stringify([clip.video, clip.from, clip.to, clip.speed ?? 1, clip.focus ?? null, board.blankCrop ?? null, board.blankInk ?? null]);

export const readJson = (work, path, fallback) => {
  const file = join(work, path);
  if (existsSync(file)) return JSON.parse(readFileSync(file, 'utf8'));
  if (fallback === undefined) throw new Error(`${file} is missing`);
  return fallback;
};

export const grayFrames = (input, filter, width, height) => {
  const raw = run('ffmpeg', ['-v', 'error', '-i', input, '-vf', `${filter},scale=${width}:${height},format=gray`, '-f', 'rawvideo', '-']);
  const frame = width * height;
  return Array.from({ length: raw.length / frame }, (_, i) => raw.subarray(i * frame, (i + 1) * frame));
};
