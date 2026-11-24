import type { StudioProject } from "../../types";

const durationMs = 260;
type Pending = { projectId: string; ids: string[]; positions: Map<string, DOMRect> };
let pending: Pending | null = null;
let animations: Animation[] = [];
let retryFrame = 0;
let retryCount = 0;

function cards() {
  return Array.from(document.querySelectorAll<HTMLElement>(".script-canvas .line-card[data-line-id]"));
}

function clearAnimations() {
  animations.forEach((animation) => animation.cancel());
  animations = [];
}

export function prepareScriptLineRestoration(before: StudioProject | null, after: StudioProject): string[] {
  cancelScriptLineRestoration();
  if (!before || before.id !== after.id) return [];
  const existingScenes = new Set(before.scenes.map((scene) => scene.id));
  const existing = new Set(before.scenes.flatMap((scene) => scene.lines.map((line) => line.id)));
  const ids = after.scenes
    .filter((scene) => existingScenes.has(scene.id))
    .flatMap((scene) => scene.lines.map((line) => line.id))
    .filter((id) => !existing.has(id));
  if (ids.length) {
    pending = {
      projectId: after.id,
      ids,
      positions: new Map(cards().map((card) => [card.dataset.lineId!, card.getBoundingClientRect()])),
    };
  }
  return ids;
}

function animateRestoredCards(operation: Pending) {
  const restored = new Set(operation.ids);
  for (const card of cards()) {
    if (restored.has(card.dataset.lineId!)) {
      animations.push(
        card.animate(
          [
            { clipPath: "inset(49% 0 49%)", backgroundColor: "var(--scena-brand-soft)", opacity: 0.65 },
            { clipPath: "inset(0 0 0)", backgroundColor: "var(--scena-surface-raised)", opacity: 1 },
          ],
          { duration: durationMs, easing: "ease-out" },
        ),
      );
      continue;
    }
    const previous = operation.positions.get(card.dataset.lineId!);
    if (!previous) continue;
    const now = card.getBoundingClientRect();
    const dx = previous.left - now.left;
    const dy = previous.top - now.top;
    if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
      animations.push(card.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "translate(0, 0)" }], { duration: durationMs, easing: "ease-out" }));
    }
  }
}

function scrollRestoredCard(first: HTMLElement, reducedMotion: boolean) {
  const canvas = first.closest<HTMLElement>(".script-canvas");
  const bounds = first.getBoundingClientRect();
  const viewport = canvas?.getBoundingClientRect();
  if (viewport && (bounds.top < viewport.top || bounds.bottom > viewport.bottom)) {
    first.scrollIntoView({ behavior: reducedMotion ? "instant" : "smooth", block: "center" });
  }
}

/** Returns the first restored ID when a virtual row must be mounted before animation. */
export function finishScriptLineRestoration(project: StudioProject): string | null {
  const operation = pending;
  if (!operation || operation.projectId !== project.id) return null;
  const first = cards().find((card) => card.dataset.lineId === operation.ids[0]);
  if (!first) {
    if (retryCount >= 30) {
      cancelScriptLineRestoration();
      return null;
    }
    if (!retryFrame) {
      retryCount += 1;
      retryFrame = window.requestAnimationFrame(() => {
        retryFrame = 0;
        finishScriptLineRestoration(project);
      });
    }
    return operation.ids[0];
  }
  pending = null;
  window.cancelAnimationFrame(retryFrame);
  retryFrame = 0;
  retryCount = 0;
  const reducedMotion = Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
  if (!reducedMotion) animateRestoredCards(operation);
  scrollRestoredCard(first, reducedMotion);
  return null;
}

export function cancelScriptLineRestoration() {
  pending = null;
  window.cancelAnimationFrame(retryFrame);
  retryFrame = 0;
  retryCount = 0;
  clearAnimations();
}
