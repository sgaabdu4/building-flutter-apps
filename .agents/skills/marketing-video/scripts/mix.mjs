import { spawnSync } from 'node:child_process';
import { join, resolve } from 'node:path';
import { readJson, seconds } from './media.mjs';

const [workArg, music, video, out] = process.argv.slice(2);
const work = resolve(workArg);
const { total, clips: lines } = readJson(work, 'audio/placement.json');
const volume = readJson(work, 'storyboard.json').music?.volume ?? 0.42;
const copies = Math.max(1, Math.ceil((total + 4) / Math.max(seconds(music) - 4, 1)));
const inputs = ['-i', video, ...Array(copies).fill(['-i', music]).flat(), ...lines.flatMap((c) => ['-i', join(work, c.file)])];
const graph = Array.from({ length: copies }, (_, i) => `[${i + 1}:a]aresample=48000,aformat=channel_layouts=stereo[m${i}]`);
let bed = '[m0]';
for (let i = 1; i < copies; i++) {
  graph.push(`${bed}[m${i}]acrossfade=d=4[x${i}]`);
  bed = `[x${i}]`;
}
graph.push(`${bed}atrim=0:${total.toFixed(2)},volume=${volume},afade=t=in:d=1.5,afade=t=out:st=${(total - 3.5).toFixed(2)}:d=3.5[bed]`);
lines.forEach((c, i) => {
  const ms = Math.round(c.at * 1000);
  graph.push(`[${copies + 1 + i}:a]aresample=48000,aformat=channel_layouts=stereo,adelay=${ms}|${ms}[v${i}]`);
});
graph.push(`${lines.map((_, i) => `[v${i}]`).join('')}amix=inputs=${lines.length}:normalize=0,apad,atrim=0:${total.toFixed(2)}[vo]`);
graph.push('[vo]asplit[vo1][vo2]');
graph.push('[bed][vo1]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=450:makeup=1[duck]');
graph.push('[duck][vo2]amix=inputs=2:normalize=0[pre]');
const ffmpeg = (tail, extra) =>
  spawnSync('ffmpeg', ['-hide_banner', '-nostats', '-y', ...inputs, '-filter_complex', [...graph, tail].join(';'), ...extra], {
    encoding: 'utf8',
    maxBuffer: 1 << 26,
  });
const measured = ffmpeg('[pre]loudnorm=I=-14:TP=-1.5:print_format=json[a]', ['-map', '[a]', '-f', 'null', '-']);
const loudness = Number(measured.stderr.match(/"input_i" : "(-?[\d.]+)"/)?.[1]);
if (!Number.isFinite(loudness)) throw new Error(`loudness measurement failed:\n${measured.stderr.slice(-2000)}`);
const encode = ['-map', '0:v', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', out];
const mixed = ffmpeg(`[pre]volume=${(-14 - loudness).toFixed(2)}dB,alimiter=limit=0.84:level=0[a]`, encode);
if (mixed.status !== 0) throw new Error(mixed.stderr.slice(-2000));
console.log('mixed', out, `${total.toFixed(2)}s`, lines.length, 'lines', copies, 'music copies');
