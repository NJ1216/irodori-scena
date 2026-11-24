import { useLayoutEffect, useRef, type ReactNode, type RefObject } from "react";
import type { useCastDeletion } from "./useCastDeletion";
import { renderCastDissolve } from "./renderCastDissolve";
import { particleRenderFields, recordParticleDeletionDiagnostic } from "../shared/particleDeletionDiagnostics";
import "../../styles/cast-deletion.css";

function revealDeletionNotebook(region: HTMLDivElement | null) {
  const spread = region?.querySelector<HTMLElement>(".cast-notebook-spread");
  const page = region?.closest<HTMLElement>(".characters-page");
  if (!region || !spread || !page) return;
  const headerBottom = document.querySelector(".app-header")?.getBoundingClientRect().bottom ?? 0;
  const gap = Number.parseFloat(getComputedStyle(region).getPropertyValue("--scena-space-3")) || 0;
  const visibleTop = Math.max(page.getBoundingClientRect().top, headerBottom) + gap;
  const offset = spread.getBoundingClientRect().top - visibleTop;
  // Deleting at the foot of a tall page can leave all the ink behind the header.
  if (offset < 0) page.scrollBy({ top: offset, behavior: "instant" });
}

function restoreDeletionFocus(region: HTMLDivElement | null, previous: "pending" | "dissolving" | undefined, deletionEnded: boolean) {
  if (deletionEnded && previous === "pending") {
    region?.querySelector<HTMLElement>(".cast-notebook-actions .delete-button")?.focus({ preventScroll: true });
  } else if (previous === "dissolving" && document.activeElement === document.body) {
    const next = region?.querySelector<HTMLElement>('.cast-notebook-tab[aria-current="page"]') ?? region;
    next?.focus({ preventScroll: true });
  }
}

export function CastDeletionFeedback({ deletion, regionRef, children }: { deletion: ReturnType<typeof useCastDeletion>["deletion"]; regionRef: RefObject<HTMLDivElement | null>; children: ReactNode }) {
  const dissolving = deletion?.phase === "dissolving";
  const image = dissolving ? deletion.image : null;
  const previousPhase = useRef<"pending" | "dissolving" | undefined>(undefined);
  useLayoutEffect(() => {
    if (dissolving) {
      revealDeletionNotebook(regionRef.current);
      regionRef.current?.querySelector<HTMLElement>('[role="status"]')?.focus({ preventScroll: true });
    } else {
      restoreDeletionFocus(regionRef.current, previousPhase.current, !deletion);
    }
    previousPhase.current = deletion?.phase;
  }, [deletion, dissolving, regionRef]);
  useLayoutEffect(() => {
    const region = regionRef.current;
    if (!image || !region) return;
    const bounds = region.getBoundingClientRect();
    const layer = document.createElement("div");
    layer.className = "cast-deletion-particle-layer";
    layer.setAttribute("aria-hidden", "true");
    layer.style.setProperty("--cast-particle-header-bottom", `${document.querySelector(".app-header")?.getBoundingClientRect().bottom ?? 0}px`);
    const canvas = document.createElement("canvas");
    canvas.className = "cast-deletion-canvas";
    layer.append(canvas);
    document.body.append(layer);
    const viewportImage = { ...image, left: bounds.left + image.left, top: bounds.top + image.top };
    let stop: () => void;
    try {
      stop = renderCastDissolve(canvas, viewportImage, undefined, undefined, {
        onMetrics: (metrics) =>
          recordParticleDeletionDiagnostic({
            target: "cast",
            phase: "render-metrics",
            durationMs: metrics.preparationMs,
            count: 1,
            outcome: "ready",
            imageWidth: image.canvas.width,
            imageHeight: image.canvas.height,
            ...particleRenderFields(metrics),
          }),
      });
    } catch (error) {
      layer.remove();
      throw error;
    }
    return () => {
      stop();
      layer.remove();
    };
  }, [image, regionRef]);
  return (
    <div ref={regionRef} className={`cast-deletion-region${dissolving ? (image ? " is-dissolving has-particles" : " is-dissolving is-css-fallback") : ""}`} tabIndex={-1}>
      <div inert={Boolean(deletion)} aria-hidden={dissolving || undefined}>
        {children}
      </div>
      {dissolving && (
        <>
          <p className="cast-deletion-notice" role="status" tabIndex={-1}>
            「{deletion?.name}」を削除しました
          </p>
        </>
      )}
    </div>
  );
}
