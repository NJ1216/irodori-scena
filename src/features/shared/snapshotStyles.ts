/**
 * Copies the computed look of live elements onto a detached clone for an SVG snapshot.
 *
 * Copying every computed property (about 630 per element) made a scene capture take about a
 * second and produced a 24 MB SVG. Only properties that shape layout and paint are copied, and
 * only where they differ from what the clone would get anyway: the browser default for its tag,
 * or, for inherited properties, the value its parent already passes down.
 */
const sides = ["top", "right", "bottom", "left"] as const;

const inheritedProperties = [
  "color",
  "font-family",
  "font-size",
  "font-weight",
  "font-style",
  "font-stretch",
  "font-feature-settings",
  "font-variant-numeric",
  "font-kerning",
  "line-height",
  "letter-spacing",
  "word-spacing",
  "text-align",
  "text-transform",
  "text-indent",
  "text-shadow",
  "white-space",
  "white-space-collapse",
  "text-wrap-mode",
  "word-break",
  "overflow-wrap",
  "line-break",
  "visibility",
  "writing-mode",
  "direction",
  "list-style-type",
  "border-collapse",
  "border-spacing",
  "fill",
  "stroke",
  "stroke-width",
  "-webkit-text-fill-color",
  "-webkit-font-smoothing",
  "-webkit-text-stroke-width",
  "-webkit-text-stroke-color",
  "caret-color",
] as const;

const ownProperties = [
  "display",
  "position",
  "top",
  "right",
  "bottom",
  "left",
  "width",
  "height",
  "min-width",
  "min-height",
  "max-width",
  "max-height",
  "box-sizing",
  "aspect-ratio",
  "float",
  "clear",
  "z-index",
  "flex-direction",
  "flex-wrap",
  "flex-grow",
  "flex-shrink",
  "flex-basis",
  "order",
  "align-items",
  "align-self",
  "align-content",
  "justify-content",
  "justify-items",
  "justify-self",
  "row-gap",
  "column-gap",
  "grid-template-columns",
  "grid-template-rows",
  "grid-template-areas",
  "grid-column-start",
  "grid-column-end",
  "grid-row-start",
  "grid-row-end",
  "grid-auto-flow",
  "grid-auto-rows",
  "grid-auto-columns",
  "overflow-x",
  "overflow-y",
  "transform",
  "transform-origin",
  "opacity",
  "filter",
  "clip-path",
  "mask-image",
  "-webkit-mask-image",
  "background-color",
  "background-image",
  "background-size",
  "background-position",
  "background-repeat",
  "background-clip",
  "background-origin",
  "border-top-left-radius",
  "border-top-right-radius",
  "border-bottom-left-radius",
  "border-bottom-right-radius",
  "outline-style",
  "outline-width",
  "outline-color",
  "outline-offset",
  "box-shadow",
  "appearance",
  "-webkit-appearance",
  "text-decoration-line",
  "text-decoration-color",
  "text-decoration-style",
  "text-overflow",
  "vertical-align",
  "object-fit",
  "object-position",
  "-webkit-line-clamp",
  "-webkit-box-orient",
  "table-layout",
  "unicode-bidi",
  "content-visibility",
  ...sides.flatMap((side) => [`margin-${side}`, `padding-${side}`, `border-${side}-width`, `border-${side}-style`, `border-${side}-color`]),
];

export const snapshotStyleProperties: readonly string[] = [...ownProperties, ...inheritedProperties];
const inherited = new Set<string>(inheritedProperties);
const defaultsByTag = new Map<string, Map<string, string>>();

/** Browser defaults per tag, read once from a blank standards-mode frame and cached. */
function readTagDefaults(tags: Iterable<string>) {
  const missing = [...new Set(tags)].filter((tag) => !defaultsByTag.has(tag));
  if (!missing.length) return;
  const frame = document.createElement("iframe");
  frame.setAttribute("aria-hidden", "true");
  frame.tabIndex = -1;
  frame.style.cssText = "position:fixed;left:-10000px;top:0;width:800px;height:600px;border:0;visibility:hidden;pointer-events:none";
  document.body.append(frame);
  try {
    const frameDocument = frame.contentDocument;
    const frameWindow = frame.contentWindow;
    if (!frameDocument || !frameWindow) return;
    frameDocument.open();
    frameDocument.write("<!doctype html><html><body></body></html>");
    frameDocument.close();
    for (const tag of missing) {
      const element = frameDocument.createElement(tag);
      frameDocument.body.append(element);
      const computed = frameWindow.getComputedStyle(element);
      defaultsByTag.set(tag, new Map(snapshotStyleProperties.map((property) => [property, computed.getPropertyValue(property)])));
    }
  } catch {
    /* Without defaults every listed property is copied, which is slower but equally faithful. */
  } finally {
    frame.remove();
  }
}

export type SnapshotStyler = (original: HTMLElement, copy: HTMLElement) => void;

/** Returns a copier for one capture; visit parents before their children. */
export function createSnapshotStyler(originals: readonly Element[]): SnapshotStyler {
  readTagDefaults(originals.map((element) => element.localName));
  const passedDown = new Map<Element, Map<string, string>>();
  return (original, copy) => {
    const computed = getComputedStyle(original);
    const defaults = defaultsByTag.get(original.localName);
    const parent = original.parentElement ? passedDown.get(original.parentElement) : undefined;
    const mine = new Map<string, string>();
    for (const property of snapshotStyleProperties) {
      const value = computed.getPropertyValue(property);
      if (!value) continue;
      if (inherited.has(property)) {
        mine.set(property, value);
        if (parent?.get(property) === value) continue;
      } else if (defaults?.get(property) === value) continue;
      copy.style.setProperty(property, value);
    }
    passedDown.set(original, mine);
  };
}

/** Lets the page paint between slices of a long capture instead of freezing it. */
export function createCaptureYield(budgetMs = 8) {
  let sliceStarted = performance.now();
  return async (signal: AbortSignal) => {
    if (performance.now() - sliceStarted < budgetMs) return;
    await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
    signal.throwIfAborted();
    sliceStarted = performance.now();
  };
}
