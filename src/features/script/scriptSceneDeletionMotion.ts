import type { StudioProject } from "../../types";
import { disposeCastSnapshot } from "../characters/castSnapshot";
import { gpuParticleLimit, maximumGpuParticleLimit, renderCastDissolve } from "../characters/renderCastDissolve";
import { particleRenderFields, recordParticleDeletionDiagnostic } from "../shared/particleDeletionDiagnostics";
import { clearPreparedScriptSceneSnapshots, takeScriptSceneSnapshot } from "./scriptSceneCapture";
import "../../styles/script-deletion.css";

const collapseDurationMs = 220;
const deletionDurationMs = 1000;
const compactionDelayMs = 700;
// One text line with a generated take: 290 screenshot pixels at 2x display scale.
export const oneLineCardHeightCssPx = 145;
export const sceneParticleLimit = maximumGpuParticleLimit;
let hidden = new Set<string>();
const listeners = new Set<() => void>();
let beforePositions: Map<string, DOMRect> | null = null;
type DeletionOperation = { id: string; completed: boolean; seenMissing: boolean; animations: Animation[]; cleanup: () => void };
const active = new Set<DeletionOperation>();
let compactionOwner: DeletionOperation | null = null;

export function subscribeScriptSceneDeletion(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
export function hiddenScriptSceneIds() {
  return hidden;
}
const emit = () => listeners.forEach((listener) => listener());

function currentPositions() {
  const root = document.querySelector<HTMLElement>(".script-canvas");
  return new Map(Array.from(root?.querySelectorAll<HTMLElement>(".scene-box[data-scene-id]") ?? []).map((scene) => [scene.dataset.sceneId!, scene.getBoundingClientRect()]));
}

export function sceneParticleBudget(visibleHeight: number) {
  return Math.min(sceneParticleLimit, Math.max(gpuParticleLimit, Math.round((gpuParticleLimit * visibleHeight) / oneLineCardHeightCssPx)));
}

export function beginScriptSceneDeletion(id: string) {
  const started = performance.now();
  const snapshot = takeScriptSceneSnapshot(id);
  if (!snapshot) throw new Error("シーンの粒子画像が見つかりません");
  const overlay = document.createElement("div");
  overlay.className = "script-deletion-overlay";
  overlay.inert = true;
  overlay.setAttribute("aria-hidden", "true");
  const canvas = document.createElement("canvas");
  canvas.className = "script-deletion-canvas";
  overlay.append(canvas);
  document.body.append(overlay);
  let stop: () => void;
  try {
    stop = renderCastDissolve(canvas, snapshot, undefined, deletionDurationMs, {
      tintParticles: true,
      inkOnly: true,
      particleLimit: sceneParticleBudget(snapshot.height),
      onMetrics: (metrics) =>
        recordParticleDeletionDiagnostic({
          target: "scene",
          itemId: id,
          phase: "render-metrics",
          durationMs: metrics.preparationMs,
          count: 1,
          outcome: "ready",
          imageWidth: snapshot.canvas.width,
          imageHeight: snapshot.canvas.height,
          ...particleRenderFields(metrics),
        }),
    });
  } catch (error) {
    overlay.remove();
    disposeCastSnapshot(snapshot);
    recordParticleDeletionDiagnostic({ target: "scene", itemId: id, phase: "mount-canvas", durationMs: performance.now() - started, count: 1, outcome: "failed", error: String(error) }, error);
    throw error;
  }
  beforePositions = currentPositions();
  clearPreparedScriptSceneSnapshots();
  recordParticleDeletionDiagnostic({ target: "scene", itemId: id, phase: "mounted", durationMs: performance.now() - started, count: 1, outcome: "ready" });
  const operation: DeletionOperation = { id, completed: false, seenMissing: false, animations: [], cleanup: () => {} };
  const timer = window.setTimeout(() => {
    operation.cleanup();
    active.delete(operation);
  }, deletionDurationMs + 450);
  operation.cleanup = () => {
    window.clearTimeout(timer);
    operation.animations.forEach((animation) => animation.cancel());
    operation.animations.length = 0;
    stop();
    disposeCastSnapshot(snapshot);
    overlay.remove();
  };
  active.add(operation);
  compactionOwner = operation;
  hidden = new Set([...hidden, id]);
  emit();
  return {
    complete() {
      operation.completed = true;
      hidden = new Set([...hidden].filter((value) => value !== id));
      emit();
    },
    rollback() {
      beforePositions = currentPositions();
      compactionOwner = null;
      operation.cleanup();
      active.delete(operation);
      hidden = new Set([...hidden].filter((value) => value !== id));
      emit();
    },
  };
}

/** Called after React has rendered without the deleted scene, before paint. */
export function finishScriptSceneCompaction() {
  if (!beforePositions) return;
  const before = beforePositions;
  beforePositions = null;
  const owner = compactionOwner;
  compactionOwner = null;
  const delay = owner ? compactionDelayMs : 0;
  const root = document.querySelector<HTMLElement>(".script-canvas");
  for (const scene of root?.querySelectorAll<HTMLElement>(".scene-box[data-scene-id]") ?? []) {
    const previous = before.get(scene.dataset.sceneId!);
    if (!previous) continue;
    const now = scene.getBoundingClientRect();
    const dx = previous.left - now.left;
    const dy = previous.top - now.top;
    if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
      const animation = scene.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "translate(0, 0)" }], { delay, duration: collapseDurationMs, easing: "ease-out", fill: "backwards" });
      if (animation) owner?.animations.push(animation);
    }
  }
}

export function cancelRestoredScriptSceneEffects(project: StudioProject) {
  const present = new Set(project.scenes.map((scene) => scene.id));
  for (const operation of active) {
    if (!operation.completed) continue;
    if (!present.has(operation.id)) operation.seenMissing = true;
    else if (operation.seenMissing) {
      operation.cleanup();
      active.delete(operation);
    }
  }
}

export function cancelScriptSceneDeletionEffects() {
  for (const operation of active) operation.cleanup();
  active.clear();
  hidden = new Set();
  beforePositions = null;
  compactionOwner = null;
  clearPreparedScriptSceneSnapshots();
  emit();
}
