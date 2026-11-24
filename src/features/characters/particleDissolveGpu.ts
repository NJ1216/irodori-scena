import type { CastSnapshot } from "./castSnapshot";
import { particleGrainSizeCssPx, type CastParticle } from "./castParticles";

export type ParticleGroup = { snapshot: CastSnapshot; particles: CastParticle[] };
export type ParticleGpu = { canvas: HTMLCanvasElement; count: number; draw: (elapsedMs: number, visible: number, retireFrom: number, retireAlpha: number, motionScale: number) => boolean; dispose: () => void };

const vertexSource = `#version 300 es
precision highp float;
layout(location=0) in vec2 aOrigin;
layout(location=1) in vec2 aScale;
layout(location=2) in vec2 aVelocity;
layout(location=3) in vec3 aMotion;
layout(location=4) in float aDelay;
layout(location=5) in vec4 aColor;
uniform vec2 uViewport;
uniform float uSeconds;
uniform float uMotionScale;
uniform int uRetireFrom;
uniform float uRetireAlpha;
out vec4 vColor;
void main() {
  float t = max(0.0, uSeconds - aDelay);
  float progress = min(1.0, t / (2.0 - aDelay));
  float motionTime = t * uMotionScale;
  float travel = motionTime * motionTime / (motionTime + 0.15);
  float flutter = aMotion.x * min(1.0, motionTime * 4.0);
  float phase = aMotion.y + motionTime * aMotion.z;
  float gust = sin(motionTime * 3.0) * 12.0 * motionTime;
  vec2 shift = vec2(aVelocity.x * travel + flutter * (sin(phase) - sin(aMotion.y)) + gust,
    -aVelocity.y * travel + flutter * 0.65 * (cos(phase) - cos(aMotion.y)) + gust * 0.4);
  vec2 corner = vec2((gl_VertexID == 1 || gl_VertexID == 3) ? 1.0 : -1.0,
    gl_VertexID >= 2 ? 1.0 : -1.0);
  vec2 position = aOrigin + shift * aScale + corner * ${particleGrainSizeCssPx / 2};
  gl_Position = vec4(position.x / uViewport.x * 2.0 - 1.0, 1.0 - position.y / uViewport.y * 2.0, 0.0, 1.0);
  float alpha = 1.0 - max(0.0, progress - 0.55) / 0.45;
  if (gl_InstanceID >= uRetireFrom) alpha *= uRetireAlpha;
  vColor = vec4(aColor.rgb, aColor.a * max(0.0, alpha));
}`;
const fragmentSource = `#version 300 es
precision highp float;
in vec4 vColor;
out vec4 outputColor;
void main() { outputColor = vColor; }`;
const stride = 14;

function shader(gl: WebGL2RenderingContext, type: number, source: string) {
  const result = gl.createShader(type);
  if (!result) throw new Error("WebGL shader unavailable");
  gl.shaderSource(result, source);
  gl.compileShader(result);
  if (!gl.getShaderParameter(result, gl.COMPILE_STATUS)) {
    const message = gl.getShaderInfoLog(result);
    gl.deleteShader(result);
    throw new Error(`Particle shader failed: ${message}`);
  }
  return result;
}

function program(gl: WebGL2RenderingContext) {
  const vertex = shader(gl, gl.VERTEX_SHADER, vertexSource);
  const fragment = shader(gl, gl.FRAGMENT_SHADER, fragmentSource);
  const result = gl.createProgram();
  if (!result) throw new Error("WebGL program unavailable");
  gl.attachShader(result, vertex);
  gl.attachShader(result, fragment);
  gl.linkProgram(result);
  gl.deleteShader(vertex);
  gl.deleteShader(fragment);
  if (!gl.getProgramParameter(result, gl.LINK_STATUS)) {
    const message = gl.getProgramInfoLog(result);
    gl.deleteProgram(result);
    throw new Error(`Particle program failed: ${message}`);
  }
  return result;
}

function particleData(groups: ParticleGroup[]) {
  const entries = groups.flatMap(({ snapshot, particles }) => particles.map((particle) => ({ snapshot, particle })));
  // A prefix must remain spread across the whole scene when adaptive thinning occurs.
  entries.sort((left, right) => {
    const a = left.particle,
      b = right.particle;
    const key = (x: number, y: number) => (Math.imul(x | 0, 73856093) ^ Math.imul(y | 0, 19349663)) >>> 0;
    return key(a.x, a.y) - key(b.x, b.y);
  });
  const data = new Float32Array(entries.length * stride);
  entries.forEach(({ snapshot, particle }, index) => {
    const sx = snapshot.width / snapshot.canvas.width;
    const sy = snapshot.height / snapshot.canvas.height;
    data.set([snapshot.left + (particle.x + 0.5) * sx, snapshot.top + (particle.y + 0.5) * sy, sx, sy, particle.vx, particle.vy, particle.sway, particle.phase, particle.frequency, particle.delay, ...particle.rgba], index * stride);
  });
  return data;
}

function isSoftwareWebGl(gl: WebGL2RenderingContext) {
  const info = gl.getExtension("WEBGL_debug_renderer_info");
  const name = info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : "";
  return /SwiftShader|llvmpipe|softpipe|Software|WARP/i.test(name);
}

export function createParticleGpuLayer(reference: HTMLCanvasElement, groups: ParticleGroup[]): ParticleGpu | null {
  const parent = reference.parentElement;
  if (!parent || !groups.some((group) => group.particles.length)) return null;
  const canvas = document.createElement("canvas");
  canvas.className = "particle-deletion-gpu";
  const bounds = reference.getBoundingClientRect();
  canvas.width = Math.max(1, Math.floor(bounds.width));
  canvas.height = Math.max(1, Math.floor(bounds.height));
  const gl = canvas.getContext("webgl2", { alpha: true, antialias: false, depth: false, stencil: false });
  if (!gl) return null;
  if (isSoftwareWebGl(gl)) {
    canvas.width = canvas.height = 0;
    return null;
  }
  let graphics: WebGLProgram | null = null;
  let buffer: WebGLBuffer | null = null;
  let array: WebGLVertexArrayObject | null = null;
  try {
    graphics = program(gl);
    buffer = gl.createBuffer();
    array = gl.createVertexArray();
    if (!buffer || !array) throw new Error("WebGL particle buffer unavailable");
    const data = particleData(groups);
    gl.bindVertexArray(array);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    for (const [location, size, offset] of [
      [0, 2, 0],
      [1, 2, 2],
      [2, 2, 4],
      [3, 3, 6],
      [4, 1, 9],
      [5, 4, 10],
    ]) {
      gl.enableVertexAttribArray(location);
      gl.vertexAttribPointer(location, size, gl.FLOAT, false, stride * 4, offset * 4);
      gl.vertexAttribDivisor(location, 1);
    }
    gl.useProgram(graphics);
    gl.uniform2f(gl.getUniformLocation(graphics, "uViewport"), bounds.width, bounds.height);
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    const seconds = gl.getUniformLocation(graphics, "uSeconds");
    const motionScaleUniform = gl.getUniformLocation(graphics, "uMotionScale");
    const retireFrom = gl.getUniformLocation(graphics, "uRetireFrom");
    const retireAlpha = gl.getUniformLocation(graphics, "uRetireAlpha");
    const draw = (elapsedMs: number, visible: number, retiring: number, alpha: number, motionScale: number) => {
      if (gl.isContextLost()) return false;
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform1f(seconds, Math.min(2, elapsedMs / 1000));
      gl.uniform1f(motionScaleUniform, motionScale);
      gl.uniform1i(retireFrom, retiring);
      gl.uniform1f(retireAlpha, alpha);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, visible);
      return gl.getError() === gl.NO_ERROR;
    };
    // Test the actual shader output before the source UI is hidden.
    const visible = Array.from({ length: data.length / stride }, (_, index) => index * stride).find((offset) => data[offset] >= 1 && data[offset] < bounds.width - 1 && data[offset + 1] >= 1 && data[offset + 1] < bounds.height - 1 && data[offset + 13] > 0);
    if (visible === undefined) throw new Error("No visible particle for WebGL verification");
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform1f(seconds, 0);
    gl.uniform1f(motionScaleUniform, 1);
    gl.uniform1i(retireFrom, data.length / stride);
    gl.uniform1f(retireAlpha, 1);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, data.length / stride);
    const probe = new Uint8Array(4);
    gl.readPixels(Math.floor(data[visible]), canvas.height - Math.floor(data[visible + 1]) - 1, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, probe);
    if (probe[3] === 0 || gl.getError() !== gl.NO_ERROR) throw new Error("WebGL particles rendered transparent pixels");
    const dispose = () => {
      gl.deleteVertexArray(array);
      gl.deleteBuffer(buffer);
      gl.deleteProgram(graphics);
      canvas.remove();
      canvas.width = canvas.height = 0;
    };
    parent.insertBefore(canvas, reference.nextSibling);
    return { canvas, count: data.length / stride, draw, dispose };
  } catch {
    if (array) gl.deleteVertexArray(array);
    if (buffer) gl.deleteBuffer(buffer);
    if (graphics) gl.deleteProgram(graphics);
    canvas.width = canvas.height = 0;
    return null;
  }
}
