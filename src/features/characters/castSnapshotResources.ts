import { apiConnection, apiFetch } from "../../api-runtime";

function readDataUrl(blob: Blob, signal: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    const abort = () => reader.abort();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.onabort = () => reject(new DOMException("Capture cancelled", "AbortError"));
    reader.onloadend = () => signal.removeEventListener("abort", abort);
    signal.throwIfAborted();
    signal.addEventListener("abort", abort, { once: true });
    reader.readAsDataURL(blob);
  });
}

/** Never send the local API bearer token to an arbitrary image origin. */
export async function snapshotImageUrl(source: string, signal: AbortSignal) {
  signal.throwIfAborted();
  if (source.startsWith("data:image/")) return source;
  const url = new URL(source, document.baseURI);
  const connection = await apiConnection();
  const apiOrigin = new URL(connection.baseUrl || document.baseURI).origin;
  let response: Response;
  let sourceKind: "same-origin" | "api-origin";
  if (url.protocol === "blob:" || url.origin === location.origin) {
    sourceKind = "same-origin";
    response = await fetch(url, { signal, cache: "no-store" });
  } else if (url.origin === apiOrigin) {
    sourceKind = "api-origin";
    response = await apiFetch(url.href, { signal, cache: "no-store" });
  } else {
    throw new Error("Snapshot image must belong to this application");
  }
  if (!response.ok) throw new Error(`Snapshot image could not be loaded: HTTP ${response.status} (${sourceKind})`);
  return readDataUrl(await response.blob(), signal);
}

function loadImage(source: string, signal: AbortSignal): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    const cleanup = () => {
      signal.removeEventListener("abort", abort);
      image.onload = null;
      image.onerror = null;
    };
    const abort = () => {
      cleanup();
      image.src = "";
      reject(new DOMException("Capture cancelled", "AbortError"));
    };
    signal.throwIfAborted();
    image.onload = () => {
      cleanup();
      resolve(image);
    };
    image.onerror = () => {
      cleanup();
      reject(new Error("Notebook image could not be rendered"));
    };
    signal.addEventListener("abort", abort, { once: true });
    image.src = source;
  });
}

export type SnapshotRasterFailure = { stage: "data-url" | "blob-url"; error: unknown };

function hasVisiblePixels(context: CanvasRenderingContext2D, width: number, height: number) {
  const pixels = context.getImageData(0, 0, width, height).data;
  for (let index = 3; index < pixels.length; index += 4) {
    if (pixels[index] !== 0) return true;
  }
  return false;
}

/** WebKit prefers a data URL while WebView2 is more reliable with a blob URL. */
export async function rasterizeSnapshotSvg(svg: string, canvas: HTMLCanvasElement, signal: AbortSignal): Promise<SnapshotRasterFailure[]> {
  const failures: SnapshotRasterFailure[] = [];
  let blobUrl: string | null = null;
  try {
    for (const stage of ["data-url", "blob-url"] as const) {
      let image: HTMLImageElement | null = null;
      try {
        signal.throwIfAborted();
        const source = stage === "data-url" ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}` : (blobUrl = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" })));
        image = await loadImage(source, signal);
        const context = canvas.getContext("2d");
        if (!context) throw new Error("Canvas unavailable");
        context.clearRect(0, 0, canvas.width, canvas.height);
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        // WebView2 may report a successful SVG load while rendering the
        // foreignObject as a fully transparent bitmap. Treat that as a failed
        // path so the blob attempt or the visible CSS fallback can take over.
        if (!hasVisiblePixels(context, canvas.width, canvas.height)) throw new Error("Notebook image rendered without visible pixels");
        return failures;
      } catch (error) {
        if (signal.aborted) throw error;
        failures.push({ stage, error });
      } finally {
        if (image) image.src = "";
      }
    }
  } finally {
    if (blobUrl) URL.revokeObjectURL(blobUrl);
  }
  throw new AggregateError(
    failures.map((failure) => failure.error),
    "Notebook image could not be rendered",
  );
}

export function loadSnapshotSvg(svg: string, signal: AbortSignal): Promise<HTMLImageElement> {
  return loadImage(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`, signal);
}
