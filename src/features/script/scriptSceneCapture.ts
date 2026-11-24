import { disposeCastSnapshot, type CastSnapshot } from "../characters/castSnapshot";
import { ParticlePreparationFailure, particleFailureMessage, particleFailurePhase, recordParticleDeletionDiagnostic, particleCancelled } from "../shared/particleDeletionDiagnostics";
import { captureScriptSceneCanvas } from "./scriptLineCanvasSnapshot";

type VisibleScene = { element: HTMLElement; rect: DOMRect };
type PreparedScene = { element: HTMLElement; rect: DOMRect; image: Promise<CastSnapshot>; controller: AbortController; snapshot: CastSnapshot | null };
const prepared = new Map<string, PreparedScene>();
let expiryTimer: number | null = null;

export function visibleScene(id: string): VisibleScene | null {
  const canvas = document.querySelector<HTMLElement>(".script-canvas");
  const element = canvas?.querySelector<HTMLElement>(`.scene-box[data-scene-id="${CSS.escape(id)}"]`);
  if (!canvas || !element) return null;
  const bounds = element.getBoundingClientRect();
  const viewport = canvas.getBoundingClientRect();
  const left = Math.max(0, viewport.left, bounds.left);
  const right = Math.min(innerWidth, viewport.right, bounds.right);
  const top = Math.max(0, viewport.top, document.querySelector(".app-header")?.getBoundingClientRect().bottom ?? 0, bounds.top);
  const bottom = Math.min(innerHeight, viewport.bottom, document.querySelector(".footer-controls")?.getBoundingClientRect().top ?? innerHeight, bounds.bottom);
  if (right <= left || bottom <= top) return null;
  return { element, rect: { left, top, right, bottom, width: right - left, height: bottom - top } as DOMRect };
}

function sameScene(entry: PreparedScene, scene: VisibleScene) {
  return entry.element === scene.element && !entry.controller.signal.aborted && Math.abs(entry.rect.left - scene.rect.left) < 2 && Math.abs(entry.rect.top - scene.rect.top) < 2 && Math.abs(entry.rect.width - scene.rect.width) < 2 && Math.abs(entry.rect.height - scene.rect.height) < 2;
}

function queue(id: string, scene: VisibleScene) {
  const existing = prepared.get(id);
  if (existing && sameScene(existing, scene)) return existing.image;
  if (existing) {
    existing.controller.abort("superseded");
    disposeCastSnapshot(existing.snapshot);
  }
  const controller = new AbortController();
  const started = performance.now();
  const entry: PreparedScene = { element: scene.element, rect: scene.rect, image: Promise.resolve(null as never), controller, snapshot: null };
  const image = captureScriptSceneCanvas(scene.element, scene.rect, controller.signal).then(
    (snapshot) => {
      if (controller.signal.aborted) disposeCastSnapshot(snapshot);
      else entry.snapshot = snapshot;
      recordParticleDeletionDiagnostic({
        target: "scene",
        itemId: id,
        phase: controller.signal.aborted ? "aborted" : "prepared",
        durationMs: performance.now() - started,
        count: 1,
        outcome: particleCancelled(controller.signal) ? "cancelled" : "ready",
        imageWidth: snapshot.canvas.width,
        imageHeight: snapshot.canvas.height,
      });
      return snapshot;
    },
    (error: unknown) => {
      recordParticleDeletionDiagnostic({ target: "scene", itemId: id, phase: controller.signal.aborted ? "aborted" : particleFailurePhase(error), durationMs: performance.now() - started, count: 1, outcome: particleCancelled(controller.signal) ? "cancelled" : "failed", error: particleFailureMessage(error) }, error);
      if (prepared.get(id) === entry) prepared.delete(id);
      throw error;
    },
  );
  entry.image = image;
  void image.catch(() => undefined);
  prepared.set(id, entry);
  return image;
}

export function prepareScriptSceneSnapshot(id: string) {
  clearPreparedScriptSceneSnapshots();
  const scene = visibleScene(id);
  if (scene) queue(id, scene);
  expiryTimer = window.setTimeout(clearPreparedScriptSceneSnapshots, 4_000);
}

export async function waitForScriptSceneSnapshot(id: string) {
  const started = performance.now();
  if (expiryTimer !== null) window.clearTimeout(expiryTimer);
  expiryTimer = null;
  const scene = visibleScene(id);
  if (!scene) throw new ParticlePreparationFailure("geometry", new Error("シーンが画面に表示されていません"));
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 10_000);
  try {
    const image = await Promise.race([queue(id, scene), new Promise<never>((_, reject) => controller.signal.addEventListener("abort", () => reject(new ParticlePreparationFailure("timeout", new Error("粒子アニメーションの準備がタイムアウトしました"))), { once: true }))]);
    if (!image.width || !image.height) throw new Error("粒子アニメーションを準備できませんでした");
    recordParticleDeletionDiagnostic({ target: "scene", itemId: id, phase: "confirmation-ready", durationMs: performance.now() - started, count: 1, outcome: "ready" });
  } catch (error) {
    recordParticleDeletionDiagnostic({ target: "scene", itemId: id, phase: particleFailurePhase(error), durationMs: performance.now() - started, count: 1, outcome: "failed", error: particleFailureMessage(error) }, error);
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

export function takeScriptSceneSnapshot(id: string) {
  const entry = prepared.get(id);
  prepared.delete(id);
  return entry?.snapshot ?? null;
}

export function clearPreparedScriptSceneSnapshots() {
  if (expiryTimer !== null) window.clearTimeout(expiryTimer);
  expiryTimer = null;
  for (const entry of prepared.values()) {
    entry.controller.abort("cleared");
    disposeCastSnapshot(entry.snapshot);
  }
  prepared.clear();
}
