import type { StudioProject } from "../../types";
import { disposeCastSnapshot, type CastSnapshot } from "../characters/castSnapshot";
import { renderCastDissolve } from "../characters/renderCastDissolve";
import { clearPreparedScriptLineSnapshots, takeScriptLineSnapshot, visibleCards } from "./scriptLineCapture";
import { particleRenderFields, recordParticleDeletionDiagnostic } from "../shared/particleDeletionDiagnostics";
import "../../styles/script-deletion.css";

const collapseDurationMs = 220;
const scriptDeletionDurationMs = 1000;
const compactionDelayMs = 700;
let hidden = new Set<string>();
const listeners = new Set<() => void>();
let beforePositions: Map<string, DOMRect> | null = null;
let compactingTimer: number | null = null;
type DeletionOperation = { ids: Set<string>; completed: boolean; seenMissing: boolean; animations: Animation[]; cleanup: () => void };
const active = new Set<DeletionOperation>();
let compactionOwner: DeletionOperation | null = null;

export function subscribeScriptLineDeletion(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
export function hiddenScriptLineIds() {
  return hidden;
}

function emit() {
  listeners.forEach((listener) => listener());
}

function currentPositions() {
  const root = document.querySelector<HTMLElement>(".script-canvas");
  return new Map(Array.from(root?.querySelectorAll<HTMLElement>(".line-card[data-line-id]") ?? []).map((card) => [card.dataset.lineId!, card.getBoundingClientRect()]));
}

export function beginScriptLineDeletion(ids: readonly string[]) {
  const started = performance.now();
  const root = document.querySelector<HTMLElement>(".script-canvas");
  beforePositions = currentPositions();
  const overlay = document.createElement("div");
  overlay.className = "script-deletion-overlay";
  overlay.inert = true;
  overlay.setAttribute("aria-hidden", "true");
  document.body.append(overlay);
  const images: CastSnapshot[] = [];
  let stopAnimation: (() => void) | undefined;
  try {
    for (const { id } of visibleCards(ids)) {
      const snapshot = takeScriptLineSnapshot(id);
      if (!snapshot) throw new Error(`Missing prepared canvas for ${id}`);
      images.push(snapshot);
    }
    const canvas = document.createElement("canvas");
    canvas.className = "script-deletion-canvas";
    overlay.append(canvas);
    stopAnimation = renderCastDissolve(canvas, images, undefined, scriptDeletionDurationMs, {
      tintParticles: true,
      inkOnly: true,
      onMetrics: (metrics) =>
        recordParticleDeletionDiagnostic({
          target: "line",
          phase: "render-metrics",
          durationMs: metrics.preparationMs,
          count: images.length,
          outcome: "ready",
          imageWidth: images.reduce((sum, image) => sum + image.canvas.width, 0),
          imageHeight: Math.max(0, ...images.map((image) => image.canvas.height)),
          ...particleRenderFields(metrics),
        }),
    });
  } catch (error) {
    stopAnimation?.();
    images.forEach(disposeCastSnapshot);
    overlay.remove();
    recordParticleDeletionDiagnostic({ target: "line", phase: "mount-canvas", durationMs: performance.now() - started, count: ids.length, outcome: "failed", error: String(error) }, error);
    throw error;
  }
  clearPreparedScriptLineSnapshots();
  recordParticleDeletionDiagnostic({ target: "line", phase: "mounted", durationMs: performance.now() - started, count: ids.length, outcome: "ready" });
  const operation: DeletionOperation = { ids: new Set(ids), completed: false, seenMissing: false, animations: [], cleanup: () => {} };
  const timer = window.setTimeout(() => {
    operation.cleanup();
    active.delete(operation);
  }, scriptDeletionDurationMs + 450);
  operation.cleanup = () => {
    window.clearTimeout(timer);
    operation.animations.forEach((animation) => animation.cancel());
    operation.animations.length = 0;
    stopAnimation?.();
    images.forEach(disposeCastSnapshot);
    overlay.remove();
  };
  active.add(operation);
  compactionOwner = operation;
  hidden = new Set([...hidden, ...ids]);
  root?.classList.add("is-deletion-compacting");
  emit();
  return {
    complete() {
      operation.completed = true;
      hidden = new Set([...hidden].filter((id) => !operation.ids.has(id)));
      emit();
    },
    rollback() {
      beforePositions = currentPositions();
      compactionOwner = null;
      if (compactingTimer !== null) window.clearTimeout(compactingTimer);
      compactingTimer = null;
      root?.classList.remove("is-deletion-compacting");
      operation.cleanup();
      active.delete(operation);
      hidden = new Set([...hidden].filter((id) => !operation.ids.has(id)));
      emit();
    },
  };
}

/** Called after React has rendered the filtered rows, before the next paint. */
export function finishScriptLineCompaction() {
  if (!beforePositions) return;
  const before = beforePositions;
  beforePositions = null;
  const owner = compactionOwner;
  compactionOwner = null;
  const delay = owner ? compactionDelayMs : 0;
  const root = document.querySelector<HTMLElement>(".script-canvas");
  for (const card of root?.querySelectorAll<HTMLElement>(".line-card[data-line-id]") ?? []) {
    const previous = before.get(card.dataset.lineId!);
    if (!previous) continue;
    const now = card.getBoundingClientRect();
    const dx = previous.left - now.left;
    const dy = previous.top - now.top;
    if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
      const animation = card.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "translate(0, 0)" }], { delay, duration: collapseDurationMs, easing: "ease-out", fill: "backwards" });
      if (animation) owner?.animations.push(animation);
    }
  }
  if (compactingTimer !== null) window.clearTimeout(compactingTimer);
  compactingTimer = window.setTimeout(() => {
    root?.classList.remove("is-deletion-compacting");
    compactingTimer = null;
  }, delay + collapseDurationMs);
}

export function cancelRestoredScriptLineEffects(project: StudioProject) {
  const present = new Set(project.scenes.flatMap((scene) => scene.lines.map((line) => line.id)));
  for (const operation of active) {
    if (!operation.completed) continue;
    if (![...operation.ids].some((id) => present.has(id))) operation.seenMissing = true;
    else if (operation.seenMissing) {
      operation.cleanup();
      active.delete(operation);
    }
  }
}

export function cancelScriptLineDeletionEffects() {
  if (compactingTimer !== null) window.clearTimeout(compactingTimer);
  compactingTimer = null;
  for (const operation of active) operation.cleanup();
  active.clear();
  hidden = new Set();
  beforePositions = null;
  compactionOwner = null;
  document.querySelector(".script-canvas")?.classList.remove("is-deletion-compacting");
  clearPreparedScriptLineSnapshots();
  emit();
}
