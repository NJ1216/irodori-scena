import type { CastSnapshot } from "./castSnapshot";
import { castDeletionDurationMs, castParticleLimit, castParticlePose, createCastParticles, particleGrainSizeCssPx } from "./castParticles";
import { createParticleGpuLayer, type ParticleGroup, type ParticleGpu } from "./particleDissolveGpu";
import "../../styles/particle-deletion.css";

export const gpuParticleLimit = castParticleLimit;
export const maximumGpuParticleLimit = 10_000;
export type DissolveMetrics = { preparationMs: number; particleCount: number; initialParticleCount: number; renderer: "webgl2" | "canvas2d" | "dom"; fallbackReason?: string; drawMedianMs: number; drawP95Ms: number; frameMedianMs: number; frameP95Ms: number };
/** inkOnly: grains come from text, icons and lines, not from the flat paper they sit on (the paper still fades). */
type DissolveOptions = { particleLimit?: number; tintParticles?: boolean; inkOnly?: boolean; onMetrics?: (metrics: DissolveMetrics) => void };
function brandTint(reference: HTMLCanvasElement): [number, number, number] | undefined {
  const match = /^#([\da-f]{6})$/i.exec(getComputedStyle(reference).getPropertyValue("--scena-brand").trim());
  if (!match) return undefined;
  return [0, 2, 4].map((offset) => parseInt(match[1].slice(offset, offset + 2), 16)) as [number, number, number];
}
function percentile(values: number[], fraction: number) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.ceil(sorted.length * fraction) - 1];
}

function prepareGroups(snapshots: CastSnapshot[], limit: number, tint?: readonly [number, number, number], inkOnly = false): ParticleGroup[] {
  const totalPixels = snapshots.reduce((sum, image) => sum + image.canvas.width * image.canvas.height, 0);
  let remaining = limit;
  return snapshots.map((snapshot, index) => {
    const source = snapshot.canvas.getContext("2d");
    if (!source) throw new Error("Canvas unavailable");
    const allocation = index === snapshots.length - 1 ? remaining : Math.min(remaining, Math.floor((limit * snapshot.canvas.width * snapshot.canvas.height) / totalPixels));
    remaining -= allocation;
    return { snapshot, particles: createCastParticles(source.getImageData(0, 0, snapshot.canvas.width, snapshot.canvas.height).data, snapshot.canvas.width, snapshot.canvas.height, Math.random, allocation, tint, inkOnly) };
  });
}

function thinGroups(groups: ParticleGroup[], limit: number): ParticleGroup[] {
  const total = groups.reduce((sum, group) => sum + group.particles.length, 0);
  if (total <= limit) return groups;
  let index = 0;
  return groups.map(({ snapshot, particles }) => ({
    snapshot,
    particles: particles.filter(() => {
      const chosen = Math.floor(((index + 1) * limit) / total) > Math.floor((index * limit) / total);
      index++;
      return chosen;
    }),
  }));
}

function attachBackgrounds(reference: HTMLCanvasElement, snapshots: CastSnapshot[], durationMs: number) {
  if (!reference.parentElement) return [];
  const backgrounds: HTMLCanvasElement[] = [];
  for (const snapshot of snapshots) {
    const image = snapshot.canvas;
    image.classList.add("particle-deletion-background");
    image.style.left = `${snapshot.left}px`;
    image.style.top = `${snapshot.top}px`;
    image.style.width = `${snapshot.width}px`;
    image.style.height = `${snapshot.height}px`;
    image.style.animationDuration = `${durationMs * 0.65}ms`;
    reference.parentElement.insertBefore(image, reference);
    backgrounds.push(image);
  }
  return backgrounds;
}

function drawCanvasParticles(context: CanvasRenderingContext2D, canvas: HTMLCanvasElement, groups: ParticleGroup[], backgrounds: HTMLCanvasElement[], elapsed: number, realElapsed: number, durationMs: number, pose: { x: number; y: number; alpha: number }) {
  context.setTransform(1, 0, 0, 1, 0, 0);
  context.clearRect(0, 0, canvas.width, canvas.height);
  if (!backgrounds.length) {
    const alpha = Math.max(0, 1 - realElapsed / (durationMs * 0.65));
    for (const { snapshot } of groups)
      if (alpha > 0) {
        context.globalAlpha = alpha;
        context.drawImage(snapshot.canvas, snapshot.left, snapshot.top, snapshot.width, snapshot.height);
      }
  }
  for (const { snapshot, particles } of groups) {
    const sx = snapshot.width / snapshot.canvas.width;
    const sy = snapshot.height / snapshot.canvas.height;
    for (const particle of particles) {
      castParticlePose(particle, elapsed, pose, durationMs / castDeletionDurationMs);
      if (pose.alpha <= 0) continue;
      context.globalAlpha = pose.alpha;
      context.fillStyle = particle.color;
      context.fillRect(snapshot.left + (pose.x + 0.5) * sx - particleGrainSizeCssPx / 2, snapshot.top + (pose.y + 0.5) * sy - particleGrainSizeCssPx / 2, particleGrainSizeCssPx, particleGrainSizeCssPx);
    }
  }
}

/** A single RAF serves one deletion. WebGL batches individually moving grains; 2D remains the fallback. */
export function renderCastDissolve(canvas: HTMLCanvasElement, input: CastSnapshot | CastSnapshot[], onFailure?: () => void, durationMs = castDeletionDurationMs, options: DissolveOptions = {}) {
  const preparationStarted = performance.now();
  const snapshots = Array.isArray(input) ? input : [input];
  const backgrounds = attachBackgrounds(canvas, snapshots, durationMs);
  const maxParticles = Math.min(maximumGpuParticleLimit, options.particleLimit ?? gpuParticleLimit);
  let groups: ParticleGroup[];
  let gpu: ParticleGpu | null = null;
  try {
    groups = prepareGroups(snapshots, maxParticles, options.tintParticles ? brandTint(canvas) : undefined, options.inkOnly);
    gpu = createParticleGpuLayer(canvas, groups);
  } catch (error) {
    backgrounds.forEach((background) => background.remove());
    throw error;
  }
  let renderer: "webgl2" | "canvas2d" | "dom" = gpu ? "webgl2" : "canvas2d";
  let fallbackReason = gpu ? undefined : "webgl2-unavailable";
  let context: CanvasRenderingContext2D | null = null;
  if (!gpu) {
    groups = thinGroups(groups, Math.min(castParticleLimit, maxParticles));
    context = canvas.getContext("2d");
    if (!context) {
      if (!backgrounds.length) throw new Error("Canvas unavailable");
      renderer = "dom";
      fallbackReason = "canvas-unavailable";
    }
  }
  const bounds = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.floor(bounds.width));
  canvas.height = Math.max(1, Math.floor(bounds.height));
  if (gpu) canvas.style.display = "none";
  const preparationMs = performance.now() - preparationStarted;
  const initialParticleCount = groups.reduce((sum, group) => sum + group.particles.length, 0);
  let activeCount = renderer === "dom" ? 0 : initialParticleCount;
  let retiringFrom = activeCount;
  let retireStarted = 0;
  let slowWindows = 0;
  let frame = 0;
  let reported = false;
  let stopped = false;
  let lastFrame: number | null = null;
  const intervals: number[] = [];
  const draws: number[] = [];
  const pose = { x: 0, y: 0, alpha: 1 };
  const started = performance.now();
  function reportMetrics() {
    if (reported || !options.onMetrics) return;
    reported = true;
    options.onMetrics({ preparationMs, initialParticleCount, particleCount: activeCount, renderer, fallbackReason, drawMedianMs: percentile(draws, 0.5), drawP95Ms: percentile(draws, 0.95), frameMedianMs: percentile(intervals, 0.5), frameP95Ms: percentile(intervals, 0.95) });
  }
  function switchTo2d() {
    gpu?.dispose();
    gpu = null;
    canvas.style.display = "";
    context = canvas.getContext("2d");
    if (!context) {
      renderer = "dom";
      fallbackReason = "canvas-unavailable";
      activeCount = 0;
      return;
    }
    groups = thinGroups(groups, Math.min(castParticleLimit, maxParticles));
    activeCount = groups.reduce((sum, group) => sum + group.particles.length, 0);
    renderer = "canvas2d";
    fallbackReason = "webgl2-render-failed";
  }
  function adapt(now: number) {
    if (!gpu || retireStarted || intervals.length < 4 || intervals.length % 4 !== 0) return;
    const recent = intervals.slice(-4);
    slowWindows = percentile(recent, 0.5) > 20 ? slowWindows + 1 : 0;
    if (slowWindows < 2 || activeCount <= Math.min(castParticleLimit, initialParticleCount)) return;
    retiringFrom = Math.max(Math.min(castParticleLimit, initialParticleCount), Math.floor(activeCount * 0.75));
    retireStarted = now;
    slowWindows = 0;
  }
  function draw(now: number) {
    if (stopped) return;
    const drawStarted = performance.now();
    try {
      if (lastFrame !== null) intervals.push(now - lastFrame);
      lastFrame = now;
      adapt(now);
      const realElapsed = now - started;
      const elapsed = Math.min(castDeletionDurationMs, (realElapsed * castDeletionDurationMs) / durationMs);
      if (gpu) {
        const alpha = retireStarted ? Math.max(0, 1 - (now - retireStarted) / 100) : 1;
        if (!gpu.draw(elapsed, activeCount, retiringFrom, alpha, durationMs / castDeletionDurationMs)) switchTo2d();
        if (retireStarted && alpha <= 0) {
          activeCount = retiringFrom;
          retireStarted = 0;
        }
      }
      if (context && !gpu) drawCanvasParticles(context, canvas, groups, backgrounds, elapsed, realElapsed, durationMs, pose);
      draws.push(performance.now() - drawStarted);
      if (realElapsed < durationMs) frame = requestAnimationFrame(draw);
      else reportMetrics();
    } catch {
      stopped = true;
      reportMetrics();
      gpu?.dispose();
      backgrounds.forEach((background) => background.remove());
      canvas.width = canvas.height = 0;
      onFailure?.();
    }
  }
  draw(started);
  return () => {
    stopped = true;
    cancelAnimationFrame(frame);
    reportMetrics();
    gpu?.dispose();
    backgrounds.forEach((background) => background.remove());
    canvas.style.display = "";
    canvas.width = canvas.height = 0;
  };
}
