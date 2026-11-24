import { rasterizeSnapshotSvg, snapshotImageUrl } from "./castSnapshotResources";

export type CastSnapshot = { canvas: HTMLCanvasElement; width: number; height: number; left: number; top: number };
const paperSelector = ".cast-notebook-spread, .cast-notebook-page";
const omittedSelector = ".cast-notebook-actions, .cast-notebook-reference-voice, .cast-notebook-action-spacer";
export const castSnapshotMaxPixels = 250_000;
export const castSnapshotTimeoutMs = 800;
export function snapshotSvgDocument(xml: string, width: number, height: number) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><foreignObject width="100%" height="100%">${xml}</foreignObject></svg>`;
}

function copyAppearance(source: HTMLElement, target: HTMLElement) {
  const computed = getComputedStyle(source);
  for (const property of computed) target.style.setProperty(property, computed.getPropertyValue(property));
  target.style.animation = "none";
  target.style.transition = "none";
  target.style.boxShadow = "none";
  target.removeAttribute("id");
  if (source.matches(paperSelector)) {
    target.style.background = "transparent";
    target.style.borderColor = "transparent";
    target.style.borderInlineColor = "transparent";
    target.style.borderBlockColor = "transparent";
  }
  if (source.matches(omittedSelector)) target.style.visibility = "hidden";
}

async function cloneNotebook(source: HTMLElement, signal: AbortSignal) {
  const clone = source.cloneNode(true) as HTMLElement;
  // Language controls WebKit's CJK fallback glyph metrics, even for system fonts.
  clone.lang = source.closest("[lang]")?.getAttribute("lang") ?? "ja";
  clone.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");
  const originals = [source, ...source.querySelectorAll<HTMLElement>("*")];
  const copies = [clone, ...clone.querySelectorAll<HTMLElement>("*")];
  const images: Promise<void>[] = [];
  originals.forEach((original, index) => {
    const copy = copies[index];
    copyAppearance(original, copy);
    if (original instanceof HTMLImageElement) {
      images.push(
        snapshotImageUrl(original.currentSrc || original.src, signal).then((url) => {
          copy.removeAttribute("srcset");
          copy.removeAttribute("loading");
          copy.setAttribute("src", url);
        }),
      );
    }
  });
  await Promise.all(images);
  signal.throwIfAborted();
  // This notebook uses installed system fonts, preserved by computed font-family.
  // Only the detached copy loses paper decorations; the live DOM is untouched.
  const style = document.createElement("style");
  style.textContent = "*::before,*::after{content:none!important}.cast-notebook-actions *{visibility:hidden!important}";
  clone.prepend(style);
  clone.style.margin = "0";
  clone.style.position = "relative";
  clone.style.inset = "auto";
  return clone;
}

export async function captureCastSnapshot(region: HTMLElement, signal: AbortSignal): Promise<CastSnapshot> {
  const spread = region.querySelector<HTMLElement>(".cast-notebook-spread");
  if (!spread) throw new Error("No visible notebook");
  const bounds = spread.getBoundingClientRect();
  const origin = region.getBoundingClientRect();
  if (!bounds.width || !bounds.height) throw new Error("Notebook is hidden");
  await document.fonts.ready;
  signal.throwIfAborted();
  const clone = await cloneNotebook(spread, signal);
  const scale = Math.min(0.5, Math.sqrt(castSnapshotMaxPixels / (bounds.width * bounds.height)));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.floor(bounds.width * scale));
  canvas.height = Math.max(1, Math.floor(bounds.height * scale));
  const xml = new XMLSerializer().serializeToString(clone);
  const svg = snapshotSvgDocument(xml, bounds.width, bounds.height);
  try {
    signal.throwIfAborted();
    await rasterizeSnapshotSvg(svg, canvas, signal);
    return { canvas, width: bounds.width, height: bounds.height, left: bounds.left - origin.left, top: bounds.top - origin.top };
  } catch (error) {
    canvas.width = canvas.height = 0;
    throw error;
  }
}

export function disposeCastSnapshot(snapshot: CastSnapshot | null) {
  if (snapshot) snapshot.canvas.width = snapshot.canvas.height = 0;
}

/** The visual preparation is optional and must never prevent a confirmed delete. */
export async function prepareCastSnapshot(region: HTMLElement, signal: AbortSignal): Promise<CastSnapshot | null> {
  if (signal.aborted) return null;
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  const timer = window.setTimeout(abort, castSnapshotTimeoutMs);
  try {
    return await Promise.race([
      captureCastSnapshot(region, controller.signal).then((snapshot) => {
        if (!controller.signal.aborted) return snapshot;
        disposeCastSnapshot(snapshot);
        return null;
      }),
      new Promise<null>((resolve) => controller.signal.addEventListener("abort", () => resolve(null), { once: true })),
    ]);
  } catch {
    return null;
  } finally {
    window.clearTimeout(timer);
    signal.removeEventListener("abort", abort);
    controller.abort();
  }
}
