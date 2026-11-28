export const castParticleLimit = 2500;
export const particleGrainSizeCssPx = 3;
export const castDeletionDurationMs = 2000;
export type CastParticle = { x: number; y: number; color: string; rgba: [number, number, number, number]; delay: number; vx: number; vy: number; sway: number; phase: number; frequency: number };
type Pose = { x: number; y: number; alpha: number };

/** A flat colour covering this share of the opaque pixels is a surface (a card's paper), not ink. */
export const backgroundColorShare = 0.15;
/** Below this many ink pixels the surface itself is the only content, so it stays a particle source. */
const minimumInkPixels = 64;
const colorKey = (pixels: Uint8ClampedArray, offset: number) => ((pixels[offset] >> 3) << 10) | ((pixels[offset + 1] >> 3) << 5) | (pixels[offset + 2] >> 3);

/** Mark the pixels that may become grains: opaque ones, minus large flat surfaces when only ink should fly. */
function particleSources(pixels: Uint8ClampedArray, count: number, inkOnly: boolean) {
  const sources = new Uint8Array(count);
  let opaque = 0;
  for (let pixel = 0; pixel < count; pixel++)
    if (pixels[pixel * 4 + 3] !== 0) {
      sources[pixel] = 1;
      opaque++;
    }
  if (!inkOnly || !opaque) return sources;
  const counts = new Map<number, number>();
  for (let pixel = 0; pixel < count; pixel++) {
    if (!sources[pixel] || pixels[pixel * 4 + 3] !== 255) continue;
    const key = colorKey(pixels, pixel * 4);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const surfaces = new Set([...counts].filter(([, total]) => total >= opaque * backgroundColorShare).map(([key]) => key));
  if (!surfaces.size) return sources;
  const ink = sources.slice();
  let inkCount = 0;
  for (let pixel = 0; pixel < count; pixel++) {
    if (ink[pixel] && pixels[pixel * 4 + 3] === 255 && surfaces.has(colorKey(pixels, pixel * 4))) ink[pixel] = 0;
    inkCount += ink[pixel];
  }
  return inkCount >= minimumInkPixels ? ink : sources;
}

function particleAt(pixels: Uint8ClampedArray, pixel: number, width: number, random: () => number, tint?: readonly [number, number, number]): CastParticle {
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
}

/** Reservoir-sample the budget left after the seeds from every other source pixel. */
function sampleRemaining(sources: Uint8Array, seeds: Set<number>, remaining: number, random: () => number) {
  const extras = new Int32Array(Math.max(0, remaining));
  let candidates = 0;
  for (let pixel = 0; pixel < sources.length; pixel++) {
    if (!sources[pixel] || seeds.has(pixel)) continue;
    if (candidates < extras.length) extras[candidates] = pixel;
    else {
      const slot = Math.floor(random() * (candidates + 1));
      if (slot < extras.length) extras[slot] = pixel;
    }
    candidates++;
  }
  return extras;
}

/** Reserve grains across the image, then fill the budget from all remaining source pixels. */
export function createCastParticles(pixels: Uint8ClampedArray, width: number, height: number, random = Math.random, limit = castParticleLimit, tint?: readonly [number, number, number], inkOnly = false): CastParticle[] {
  if (width <= 0 || height <= 0 || limit <= 0) return [];
  const sources = particleSources(pixels, width * height, inkOnly);
  const coarseLimit = Math.max(1, Math.floor(limit / 4));
  const columns = Math.max(1, Math.min(width, Math.floor(Math.sqrt((coarseLimit * width) / height))));
  const rows = Math.max(1, Math.min(height, Math.floor(coarseLimit / columns)));
  const cellSamples = new Int32Array(columns * rows).fill(-1);
  const cellCounts = new Uint32Array(cellSamples.length);
  let opaqueCount = 0;
  for (let y = 0; y < height; y++)
    for (let x = 0; x < width; x++) {
      const pixel = y * width + x;
      if (!sources[pixel]) continue;
      opaqueCount++;
      const cell = Math.min(rows - 1, Math.floor((y * rows) / height)) * columns + Math.min(columns - 1, Math.floor((x * columns) / width));
      if (random() * ++cellCounts[cell] < 1) cellSamples[cell] = pixel;
    }
  const seeds = Array.from(cellSamples).filter((pixel) => pixel >= 0);
  const remaining = Math.min(limit - seeds.length, opaqueCount - seeds.length);
  const extras = sampleRemaining(sources, new Set(seeds), remaining, random);
  return [...seeds, ...extras].map((pixel) => particleAt(pixels, pixel, width, random, tint));
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
