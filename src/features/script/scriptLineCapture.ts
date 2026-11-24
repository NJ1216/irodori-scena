import { disposeCastSnapshot, type CastSnapshot } from "../characters/castSnapshot";
import { ParticlePreparationFailure, particleFailureMessage, particleFailurePhase, recordParticleDeletionDiagnostic, particleCancelled } from "../shared/particleDeletionDiagnostics";
import { captureScriptLineCanvas } from "./scriptLineCanvasSnapshot";

type Card = { id: string; card: HTMLElement; rect: DOMRect };
type Prepared = { card: HTMLElement; rect: DOMRect; image: Promise<CastSnapshot>; controller: AbortController; snapshot: CastSnapshot | null };
const prepared = new Map<string, Prepared>();
let expiryTimer: number | null = null;

export function visibleCards(ids: readonly string[]): Card[] {
  const canvas = document.querySelector<HTMLElement>(".script-canvas");
  if (!canvas) return [];
  const viewport = canvas.getBoundingClientRect();
  const headerBottom = document.querySelector(".app-header")?.getBoundingClientRect().bottom ?? 0;
  const footerTop = document.querySelector(".footer-controls")?.getBoundingClientRect().top ?? innerHeight;
  const top = Math.max(0, viewport.top, headerBottom);
  const bottom = Math.min(innerHeight, viewport.bottom, footerTop);
  return ids.flatMap((id) => {
    const card = canvas.querySelector<HTMLElement>(`.line-card[data-line-id="${CSS.escape(id)}"]`);
    if (!card) return [];
    const rect = card.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && rect.bottom > top && rect.top < bottom && rect.right > 0 && rect.left < innerWidth ? [{ id, card, rect }] : [];
  });
}

function queue(card: Card) {
  const existing = prepared.get(card.id);
  if (existing?.card === card.card && !existing.controller.signal.aborted && Math.abs(existing.rect.left - card.rect.left) < 2 && Math.abs(existing.rect.top - card.rect.top) < 2 && Math.abs(existing.rect.width - card.rect.width) < 2 && Math.abs(existing.rect.height - card.rect.height) < 2) return existing.image;
  if (existing) {
    existing.controller.abort("superseded");
    disposeCastSnapshot(existing.snapshot);
  }
  const controller = new AbortController();
  const started = performance.now();
  const entry: Prepared = { card: card.card, rect: card.rect, image: Promise.resolve(null as never), controller, snapshot: null };
  const image = captureScriptLineCanvas(card.card, controller.signal).then(
    (snapshot) => {
      if (controller.signal.aborted) disposeCastSnapshot(snapshot);
      else entry.snapshot = snapshot;
      recordParticleDeletionDiagnostic({
        target: "line",
        itemId: card.id,
        phase: controller.signal.aborted ? "aborted" : "prepared",
        durationMs: performance.now() - started,
        count: 1,
        outcome: particleCancelled(controller.signal) ? "cancelled" : "ready",
        imageWidth: snapshot.canvas.width,
        imageHeight: snapshot.canvas.height,
        error: controller.signal.aborted ? String(controller.signal.reason) : undefined,
      });
      return snapshot;
    },
    (error: unknown) => {
      recordParticleDeletionDiagnostic(
        {
          target: "line",
          itemId: card.id,
          phase: controller.signal.aborted ? "aborted" : particleFailurePhase(error),
          durationMs: performance.now() - started,
          count: 1,
          outcome: particleCancelled(controller.signal) ? "cancelled" : "failed",
          error: controller.signal.aborted ? String(controller.signal.reason) : particleFailureMessage(error),
        },
        error,
      );
      throw error;
    },
  );
  entry.image = image;
  void image.catch(() => undefined);
  prepared.set(card.id, entry);
  return image;
}

/** Start preparation on the first confirmation click. */
export function prepareScriptLineSnapshots(ids: readonly string[]) {
  clearPreparedScriptLineSnapshots();
  for (const card of visibleCards(ids)) queue(card);
  expiryTimer = window.setTimeout(clearPreparedScriptLineSnapshots, 4_000);
}

/** Never delete a visible card unless its captured pixels are ready. */
export async function waitForScriptLineSnapshots(ids: readonly string[]) {
  const started = performance.now();
  if (expiryTimer !== null) window.clearTimeout(expiryTimer);
  expiryTimer = null;
  const cards = visibleCards(ids);
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 10_000);
  try {
    await Promise.all(
      cards.map(async (card) => {
        const image = await Promise.race([queue(card), new Promise<never>((_, reject) => controller.signal.addEventListener("abort", () => reject(new ParticlePreparationFailure("timeout", new Error("粒子アニメーションの準備がタイムアウトしました"))), { once: true }))]);
        if (!image.width || !image.height) throw new Error("粒子アニメーションを準備できませんでした");
      }),
    );
    recordParticleDeletionDiagnostic({ target: "line", phase: "confirmation-ready", durationMs: performance.now() - started, count: cards.length, outcome: "ready" });
  } catch (error) {
    recordParticleDeletionDiagnostic({ target: "line", phase: particleFailurePhase(error), durationMs: performance.now() - started, count: cards.length, outcome: "failed", error: particleFailureMessage(error) }, error);
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

export function takeScriptLineSnapshot(id: string) {
  const entry = prepared.get(id);
  prepared.delete(id);
  return entry?.snapshot ?? null;
}

export function clearPreparedScriptLineSnapshots() {
  if (expiryTimer !== null) window.clearTimeout(expiryTimer);
  expiryTimer = null;
  for (const entry of prepared.values()) {
    entry.controller.abort("cleared");
    disposeCastSnapshot(entry.snapshot);
  }
  prepared.clear();
}
