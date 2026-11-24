import { castSnapshotMaxPixels, snapshotSvgDocument, type CastSnapshot } from "../characters/castSnapshot";
import { rasterizeSnapshotSvg, snapshotImageUrl } from "../characters/castSnapshotResources";
import { ParticlePreparationFailure } from "../shared/particleDeletionDiagnostics";

function isOutsideCrop(original: HTMLElement, visible: DOMRect, outsideCrop: Map<HTMLElement, boolean>) {
  const line = original.closest<HTMLElement>(".line-card");
  if (!line) return false;
  if (!outsideCrop.has(line)) {
    const rect = line.getBoundingClientRect();
    outsideCrop.set(line, rect.bottom <= visible.top || rect.top >= visible.top + visible.height || rect.right <= visible.left || rect.left >= visible.left + visible.width);
  }
  return outsideCrop.get(line) ?? false;
}

function copyVisibleElement(original: HTMLElement, copy: HTMLElement, visible: DOMRect, crop: boolean, outsideCrop: Map<HTMLElement, boolean>, imageTasks: Promise<void>[], signal: AbortSignal) {
  const outside = crop && isOutsideCrop(original, visible, outsideCrop);
  if (outside && !original.matches(".line-card")) return;
  const computed = getComputedStyle(original);
  for (const property of computed) copy.style.setProperty(property, computed.getPropertyValue(property));
  copy.style.animation = "none";
  copy.style.transition = "none";
  copy.removeAttribute("id");
  if (outside) {
    copy.replaceChildren();
    copy.style.height = `${original.getBoundingClientRect().height}px`;
    copy.style.boxSizing = "border-box";
    copy.style.visibility = "hidden";
    return;
  }
  if (original instanceof HTMLImageElement) {
    imageTasks.push(
      snapshotImageUrl(original.currentSrc || original.src, signal).then((url) => {
        copy.removeAttribute("srcset");
        copy.setAttribute("src", url);
      }),
    );
  } else if (original instanceof HTMLTextAreaElement && copy instanceof HTMLTextAreaElement) {
    copy.textContent = original.value;
  } else if (original instanceof HTMLInputElement && copy instanceof HTMLInputElement) {
    copy.setAttribute("value", original.value);
  }
}

/** Capture the whole visible card, including its avatar and current editor text. */
async function captureScriptCanvas(card: HTMLElement, signal: AbortSignal, crop?: DOMRect): Promise<CastSnapshot> {
  const bounds = card.getBoundingClientRect();
  const visible = crop ?? bounds;
  if (!visible.width || !visible.height) throw new ParticlePreparationFailure("geometry", new Error("削除対象が表示されていません"));
  await document.fonts?.ready;
  signal.throwIfAborted();
  const clone = card.cloneNode(true) as HTMLElement;
  clone.lang = card.closest("[lang]")?.getAttribute("lang") ?? "ja";
  clone.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");
  const originals = [card, ...card.querySelectorAll<HTMLElement>("*")];
  const copies = [clone, ...clone.querySelectorAll<HTMLElement>("*")];
  const imageTasks: Promise<void>[] = [];
  const outsideCrop = new Map<HTMLElement, boolean>();
  originals.forEach((original, index) => {
    copyVisibleElement(original, copies[index], visible, Boolean(crop), outsideCrop, imageTasks, signal);
  });
  try {
    await Promise.all(imageTasks);
  } catch (error) {
    throw new ParticlePreparationFailure("image-fetch", error);
  }
  signal.throwIfAborted();
  const style = document.createElement("style");
  style.textContent = "*::before,*::after{content:none!important}";
  clone.prepend(style);
  clone.style.margin = "0";
  const scale = Math.min(0.5, Math.sqrt(castSnapshotMaxPixels / (visible.width * visible.height)));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.floor(visible.width * scale));
  canvas.height = Math.max(1, Math.floor(visible.height * scale));
  try {
    let source = clone;
    if (crop) {
      const frame = document.createElement("div");
      frame.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");
      frame.style.cssText = `position:relative;width:${visible.width}px;height:${visible.height}px;overflow:hidden`;
      clone.style.position = "absolute";
      clone.style.left = `${bounds.left - visible.left}px`;
      clone.style.top = `${bounds.top - visible.top}px`;
      clone.style.width = `${bounds.width}px`;
      frame.append(clone);
      source = frame;
    }
    await rasterizeSnapshotSvg(snapshotSvgDocument(new XMLSerializer().serializeToString(source), visible.width, visible.height), canvas, signal);
    return { canvas, width: visible.width, height: visible.height, left: visible.left, top: visible.top };
  } catch (error) {
    canvas.width = canvas.height = 0;
    throw new ParticlePreparationFailure("rasterize", error);
  }
}

export const captureScriptLineCanvas = (card: HTMLElement, signal: AbortSignal) => captureScriptCanvas(card, signal);
export const captureScriptSceneCanvas = (scene: HTMLElement, crop: DOMRect, signal: AbortSignal) => captureScriptCanvas(scene, signal, crop);
