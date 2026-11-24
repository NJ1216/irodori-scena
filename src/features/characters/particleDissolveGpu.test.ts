// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { createParticleGpuLayer } from "./particleDissolveGpu";
import type { CastSnapshot } from "./castSnapshot";
import { createCastParticles } from "./castParticles";

afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

function setup(alpha: number, renderer = "Hardware") {
  const shaders: string[] = [];
  const uniforms: Array<[string, number]> = [];
  const parent = document.createElement("div");
  const target = document.createElement("canvas");
  parent.append(target);
  document.body.append(parent);
  vi.spyOn(target, "getBoundingClientRect").mockReturnValue({ width: 40, height: 40 } as DOMRect);
  const source = document.createElement("canvas");
  source.width = 1;
  source.height = 1;
  const image: CastSnapshot = { canvas: source, width: 10, height: 10, left: 10, top: 10 };
  const pixels = new Uint8ClampedArray([255, 0, 0, 255]);
  const gl = new Proxy(
    {
      VERTEX_SHADER: 1,
      FRAGMENT_SHADER: 2,
      COMPILE_STATUS: 3,
      LINK_STATUS: 4,
      ARRAY_BUFFER: 5,
      STATIC_DRAW: 6,
      FLOAT: 7,
      BLEND: 8,
      SRC_ALPHA: 9,
      ONE_MINUS_SRC_ALPHA: 10,
      COLOR_BUFFER_BIT: 11,
      TRIANGLE_STRIP: 12,
      RGBA: 13,
      UNSIGNED_BYTE: 14,
      NO_ERROR: 0,
      getExtension: () => ({ UNMASKED_RENDERER_WEBGL: 15 }),
      getParameter: () => renderer,
      createShader: () => ({}),
      shaderSource: (_shader: unknown, source: string) => shaders.push(source),
      createProgram: () => ({}),
      createBuffer: () => ({}),
      createVertexArray: () => ({}),
      getShaderParameter: () => true,
      getProgramParameter: () => true,
      getUniformLocation: (_program: unknown, name: string) => name,
      uniform1f: (location: string, value: number) => uniforms.push([location, value]),
      getError: () => 0,
      isContextLost: () => false,
      readPixels: (_x: number, _y: number, _w: number, _h: number, _format: number, _type: number, result: Uint8Array) => {
        result[3] = alpha;
      },
    },
    { get: (object, property) => Reflect.get(object, property) ?? (() => undefined) },
  );
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(function (this: HTMLCanvasElement, type) {
    return type === "webgl2" ? (gl as unknown as WebGL2RenderingContext) : null;
  });
  return { target, shaders, uniforms, group: { snapshot: image, particles: createCastParticles(pixels, 1, 1, () => 0) } };
}

it("draws 3 CSS pixel grains with individual motion and releases the GPU layer", () => {
  const { target, group, shaders, uniforms } = setup(255);
  const layer = createParticleGpuLayer(target, [group]);
  expect(layer?.count).toBe(1);
  expect(shaders[0]).toContain("corner * 1.5");
  expect(layer?.draw(500, 1, 1, 1, 0.5)).toBe(true);
  expect(uniforms).toContainEqual(["uMotionScale", 0.5]);
  expect(document.querySelector(".particle-deletion-gpu")).toBeTruthy();
  layer?.dispose();
  expect(document.querySelector(".particle-deletion-gpu")).toBeNull();
});

it("rejects transparent shader output and software WebGL", () => {
  const transparent = setup(0);
  expect(createParticleGpuLayer(transparent.target, [transparent.group])).toBeNull();
  document.body.replaceChildren();
  vi.restoreAllMocks();
  const software = setup(255, "SwiftShader");
  expect(createParticleGpuLayer(software.target, [software.group])).toBeNull();
  expect(document.querySelector(".particle-deletion-gpu")).toBeNull();
});
