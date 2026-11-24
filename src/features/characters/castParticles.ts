export const castParticleLimit = 2500;
export const particleGrainSizeCssPx = 3;
export const castDeletionDurationMs = 2000;
export type CastParticle = { x: number; y: number; color: string; rgba: [number, number, number, number]; delay: number; vx: number; vy: number; sway: number; phase: number; frequency: number };
type Pose = { x: number; y: number; alpha: number };

/** Reserve grains across the image, then fill the budget from all remaining opaque pixels. */
export function createCastParticles(pixels: Uint8ClampedArray, width: number, height: number, random = Math.random, limit = castParticleLimit, tint?: readonly [number, number, number]): CastParticle[] {
  if (width <= 0 || height <= 0 || limit <= 0) return [];
  const coarseLimit = Math.max(1, Math.floor(limit / 4));
  const columns = Math.max(1, Math.min(width, Math.floor(Math.sqrt((coarseLimit * width) / height))));
  const rows = Math.max(1, Math.min(height, Math.floor(coarseLimit / columns)));
  const cellSamples = new Int32Array(columns * rows).fill(-1);
  const cellCounts = new Uint32Array(cellSamples.length);
  let opaqueCount = 0;
  for (let y = 0; y < height; y++)
    for (let x = 0; x < width; x++) {
      const pixel = y * width + x;
      if (pixels[pixel * 4 + 3] === 0) continue;
      opaqueCount++;
      const cell = Math.min(rows - 1, Math.floor((y * rows) / height)) * columns + Math.min(columns - 1, Math.floor((x * columns) / width));
      if (random() * ++cellCounts[cell] < 1) cellSamples[cell] = pixel;
    }
  const seeds = Array.from(cellSamples).filter((pixel) => pixel >= 0);
  const remaining = Math.min(limit - seeds.length, opaqueCount - seeds.length);
  const extras = new Int32Array(remaining);
  const seedSet = new Set(seeds);
  let candidates = 0;
  for (let pixel = 0; pixel < width * height; pixel++) {
    if (pixels[pixel * 4 + 3] === 0 || seedSet.has(pixel)) continue;
    if (candidates < remaining) extras[candidates] = pixel;
    else {
      const slot = Math.floor(random() * (candidates + 1));
      if (slot < remaining) extras[slot] = pixel;
    }
    candidates++;
  }
  return [...seeds, ...extras].map((pixel) => {
    const offset = pixel * 4;
    const color = tint ? [0, 1, 2].map((channel) => Math.round(pixels[offset + channel] * 0.75 + tint[channel] * 0.25)) : [pixels[offset], pixels[offset + 1], pixels[offset + 2]];
    return {
      x: pixel % width,
      y: Math.floor(pixel / width),
      color: `rgba(${color[0]},${color[1]},${color[2]},${pixels[offset + 3] / 255})`,
      rgba: [color[0] / 255, color[1] / 255, color[2] / 255, pixels[offset + 3] / 255] as [number, number, number, number],
      delay: random() * 0.6,
      vx: 90 + random() * 110,
      vy: 55 + random() * 75,
      sway: 10 + random() * 24,
      phase: random() * Math.PI * 2,
      frequency: 3 + random() * 5,
    };
  });
}

export function castParticlePose(particle: CastParticle, elapsedMs: number, result = {} as Pose, motionScale = 1): Pose {
  const t = Math.max(0, elapsedMs / 1000 - particle.delay);
  const progress = Math.min(1, t / (2 - particle.delay));
  const motionTime = t * motionScale;
  const travel = (motionTime * motionTime) / (motionTime + 0.15);
  const flutter = particle.sway * Math.min(1, motionTime * 4);
  const phase = particle.phase + motionTime * particle.frequency;
  const gust = Math.sin(motionTime * 3) * 12 * motionTime;
  result.x = particle.x + particle.vx * travel + flutter * (Math.sin(phase) - Math.sin(particle.phase)) + gust;
  result.y = particle.y - particle.vy * travel + flutter * 0.65 * (Math.cos(phase) - Math.cos(particle.phase)) + gust * 0.4;
  result.alpha = 1 - Math.max(0, progress - 0.55) / 0.45;
  return result;
}
