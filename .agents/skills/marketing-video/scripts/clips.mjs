import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { clipSource, grayFrames, readJson, run, size } from './media.mjs';

const work = resolve(process.argv[2]);
const board = readJson(work, 'storyboard.json');
const fps = 30;

function extract(video, clip, folder, count) {
  const speed = clip.speed ?? 1;
  const stamp = JSON.stringify([video, clip.from, clip.to, speed]);
  if (existsSync(join(folder, 'stamp')) && readFileSync(join(folder, 'stamp'), 'utf8') === stamp) return;
  rmSync(folder, { recursive: true, force: true });
  mkdirSync(folder, { recursive: true });
  const window = ['-ss', String(clip.from), '-t', String(clip.to - clip.from + 0.2), '-i', video];
  run('ffmpeg', [
    '-v',
    'error',
    ...window,
    '-vf',
    `setpts=PTS/${speed},fps=${fps}`,
    '-frames:v',
    String(count),
    '-q:v',
    '2',
    join(folder, '%05d.jpg'),
  ]);
  writeFileSync(join(folder, 'stamp'), stamp);
}

function inkRatios(folder, [x, y, w, h]) {
  return grayFrames(join(folder, '%05d.jpg'), `crop=${w}:${h}:${x}:${y}`, 300, 200).map((f) => f.filter((v) => v < 225).length / f.length);
}

function camera(clip, keep, [vw, vh]) {
  const speed = clip.speed ?? 1;
  const raw = keep.map((i) => {
    const src = clip.from + (i / fps) * speed;
    const focus = clip.focus;
    if (!focus || src < focus.from || src > focus.to) return [1, vw / 2, vh / 2];
    const [x, y, w, h] = focus.box;
    return [Math.min(1.45, vw / (w + 80), vh / (h + 80)), x + w / 2, y + h / 2];
  });
  const a = 1 - Math.exp(-1 / (fps * 0.22));
  for (const order of [raw.keys(), [...raw.keys()].reverse()]) {
    let prev = null;
    for (const f of order) {
      if (prev) raw[f] = raw[f].map((v, j) => prev[j] + (v - prev[j]) * a);
      prev = raw[f];
    }
  }
  return raw.map(([z, cx, cy]) => {
    const hw = vw / 2 / z;
    const hh = vh / 2 / z;
    return [+z.toFixed(4), +Math.min(vw - hw, Math.max(hw, cx)).toFixed(1), +Math.min(vh - hh, Math.max(hh, cy)).toFixed(1)];
  });
}

const out = {};
for (const scene of board.scenes) {
  (scene.clips ?? []).forEach((clip, i) => {
    const id = `${scene.id}-${i + 1}`;
    const video = join(work, clip.video);
    const dims = size(video);
    const folder = join(work, 'clips', id);
    extract(video, clip, folder, Math.ceil(((clip.to - clip.from) / (clip.speed ?? 1)) * fps));
    const total = readdirSync(folder).filter((f) => f.endsWith('.jpg')).length;
    const ratios = inkRatios(folder, board.blankCrop ?? [0, 0, ...dims]);
    const blank = new Set(ratios.flatMap((r, f) => (r < (board.blankInk ?? 0.012) ? [f] : [])));
    const keep = [...Array(total).keys()].filter((f) => ![f - 1, f, f + 1].some((n) => blank.has(n)));
    out[id] = {
      frames: keep.length,
      dur: keep.length / fps,
      size: dims,
      cam: camera(clip, keep, dims),
      files: keep.map((f) => f + 1),
      source: clipSource(board, clip),
    };
    console.log(
      id,
      clip.video,
      `${clip.from}-${clip.to}`,
      `x${clip.speed ?? 1}`,
      `${(keep.length / fps).toFixed(1)}s`,
      `dropped ${total - keep.length}`,
    );
  });
}
mkdirSync(join(work, 'clips'), { recursive: true });
writeFileSync(join(work, 'clips/index.json'), JSON.stringify(out));
