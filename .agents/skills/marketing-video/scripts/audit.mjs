import { mkdirSync, readdirSync, rmSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { grayFrames, run } from './media.mjs';

const [video, folderArg] = process.argv.slice(2);
const folder = resolve(folderArg);
mkdirSync(folder, { recursive: true });
for (const f of readdirSync(folder).filter((n) => n.startsWith('sheet-'))) rmSync(join(folder, f));
run('ffmpeg', ['-v', 'error', '-i', video, '-vf', 'fps=1,scale=320:-1,tile=6x5:padding=4:color=white', join(folder, 'sheet-%02d.jpg')]);
const flat = grayFrames(video, 'fps=10', 192, 108).flatMap((frame, i) => {
  const mean = frame.reduce((a, v) => a + v, 0) / frame.length;
  const spread = Math.sqrt(frame.reduce((a, v) => a + (v - mean) ** 2, 0) / frame.length);
  return spread < 6 ? [i] : [];
});
const runs = [];
for (const i of flat) {
  if (runs.length && runs.at(-1)[1] === i) runs.at(-1)[1] = i + 1;
  else runs.push([i, i + 1]);
}
console.log('sheets', readdirSync(folder).filter((n) => n.startsWith('sheet-')).length, '(30 s each, one frame per second)');
console.log('flat frame runs:', runs.map(([s, e]) => `${(s / 10).toFixed(1)}-${(e / 10).toFixed(1)}s`).join(', ') || 'none');
