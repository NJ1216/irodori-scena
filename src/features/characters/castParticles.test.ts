import { expect, it } from "vitest";
import { castParticleLimit, castParticlePose, createCastParticles } from "./castParticles";

it("samples opaque pixel colors across the source and ignores transparency", () => {
  const width = 20,
    height = 10;
  const pixels = new Uint8ClampedArray(width * height * 4);
  for (let x = 5; x < 17; x++) pixels.set([255, 240, 200, 255], (4 * width + x) * 4);
  const particles = createCastParticles(pixels, width, height);
  expect(particles).toHaveLength(12);
  expect(particles.every((particle) => particle.y === 4 && particle.x >= 5 && particle.x < 17 && particle.color === "rgba(255,240,200,1)")).toBe(true);
  expect(createCastParticles(new Uint8ClampedArray(400), 10, 10)).toEqual([]);
});

it("tints only selected particle colors while preserving alpha", () => {
  const particles = createCastParticles(new Uint8ClampedArray([255, 255, 255, 128, 0, 0, 0, 0]), 2, 1, () => 0, 2, [119, 114, 176]);
  expect(particles).toHaveLength(1);
  expect(particles[0].color).toBe("rgba(221,220,235,0.5019607843137255)");
  expect(particles[0].rgba).toEqual([221 / 255, 220 / 255, 235 / 255, 128 / 255]);
});

it("bounds particles to 2500 while sampling both ends of a large opaque source", () => {
  const particles = createCastParticles(new Uint8ClampedArray(1000 * 1000 * 4).fill(255), 1000, 1000, () => 0);
  expect(particles.length).toBeLessThanOrEqual(castParticleLimit);
  expect(Math.min(...particles.map((particle) => particle.x))).toBeLessThan(20);
  expect(Math.max(...particles.map((particle) => particle.x))).toBeGreaterThan(980);
  expect(Math.min(...particles.map((particle) => particle.y))).toBeLessThan(20);
  expect(Math.max(...particles.map((particle) => particle.y))).toBeGreaterThan(980);
});

it("respects a smaller operation budget", () => {
  const pixels = new Uint8ClampedArray(300 * 300 * 4).fill(255);
  expect(createCastParticles(pixels, 300, 300, Math.random, 500).length).toBeLessThanOrEqual(500);
});

it("moves continuously and fades by the end without changing grain size", () => {
  const particle = createCastParticles(new Uint8ClampedArray(4).fill(255), 1, 1, () => 0)[0];
  expect(castParticlePose(particle, 0)).toMatchObject({ x: 0, y: 0, alpha: 1 });
  const mid = castParticlePose(particle, 1200);
  const next = castParticlePose(particle, 1201);
  expect(Math.hypot(next.x - mid.x, next.y - mid.y)).toBeLessThan(1);
  expect(castParticlePose(particle, 2000).alpha).toBeCloseTo(0);
});

it("halves movement without slowing the one-second fade", () => {
  const particle = createCastParticles(new Uint8ClampedArray(4).fill(255), 1, 1, () => 0)[0];
  const normal = castParticlePose(particle, 1000);
  const slowed = castParticlePose(particle, 2000, undefined, 0.5);
  expect(slowed.x).toBeCloseTo(normal.x);
  expect(slowed.y).toBeCloseTo(normal.y);
  expect(slowed.alpha).toBeCloseTo(0);
  expect(normal.alpha).toBeGreaterThan(0);
});

it("fills the budget for sparse text-like ink while reaching every row band", () => {
  const width = 500,
    height = 500;
  const pixels = new Uint8ClampedArray(width * height * 4);
  const bands = Array.from({ length: 20 }, (_, index) => index * 25 + 5);
  for (const y of bands) for (let dy = 0; dy < 2; dy++) for (let x = 0; x < 500; x++) pixels.set([60, 40, 20, 255], ((y + dy) * width + x) * 4);
  const particles = createCastParticles(pixels, width, height, () => 0.37, 10_000);
  expect(particles).toHaveLength(10_000);
  expect(new Set(particles.map((particle) => `${particle.x},${particle.y}`)).size).toBe(10_000);
  for (const y of bands) expect(particles.some((particle) => particle.y === y || particle.y === y + 1)).toBe(true);
});
