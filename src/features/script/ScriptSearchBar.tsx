/* eslint-disable react-hooks/set-state-in-effect -- This component synchronizes controlled drafts, imperative media, or stable lifecycle owners at explicit boundaries. */
import { useEffect, useMemo, useRef, useState } from "react";
import type { DialogueLine, StudioProject } from "../../types";
import { findScriptMatches, replaceLineMatches } from "./scriptSearch";
import { listenForScriptSearch } from "./scriptSearchEvents";
function focusLine(lineId: string, onFocusLine: (lineId: string) => void) {
  onFocusLine(lineId);
  let frame = 0;
  let attempts = 0;
  const centerWhenMounted = () => {
    const line = document.querySelector<HTMLElement>(`[data-line-id="${CSS.escape(lineId)}"]`);
    if (line) {
      line.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    attempts += 1;
    if (attempts < 30) frame = requestAnimationFrame(centerWhenMounted);
  };
  frame = requestAnimationFrame(centerWhenMounted);
  return () => {
    cancelAnimationFrame(frame);
    const canvas = document.querySelector<HTMLElement>(".script-canvas");
    if (canvas) canvas.scrollTo({ top: canvas.scrollTop, behavior: "auto" });
  };
}

type HighlightRegistry = { set: (name: string, value: unknown) => void; delete: (name: string) => void };
function domRange(lineId: string, start: number, end: number) {
  const root = document.querySelector<HTMLElement>(`[data-line-id="${CSS.escape(lineId)}"] .line-text-editor`);
  if (!root) return null;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => (node.parentElement?.closest("rt") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  let offset = 0;
  let node: Node | null;
  let startNode: Node | null = null;
  let endNode: Node | null = null;
  let startOffset = 0;
  let endOffset = 0;
  while ((node = walker.nextNode())) {
    const length = node.textContent?.length ?? 0;
    if (!startNode && start <= offset + length) {
      startNode = node;
      startOffset = start - offset;
    }
    if (end <= offset + length) {
      endNode = node;
      endOffset = end - offset;
      break;
    }
    offset += length;
  }
  if (!startNode || !endNode) return null;
  const range = new Range();
  range.setStart(startNode, startOffset);
  range.setEnd(endNode, endOffset);
  return range;
}

function paintMatches(matches: ReturnType<typeof findScriptMatches>, current: number) {
  const registry = (CSS as typeof CSS & { highlights?: HighlightRegistry }).highlights;
  const HighlightType = (window as typeof window & { Highlight?: new (...ranges: Range[]) => unknown }).Highlight;
  if (!registry || !HighlightType) return () => {};
  const ranges = matches.map((item) => domRange(item.lineId, item.start, item.end)).filter((item): item is Range => Boolean(item));
  registry.set("script-search", new HighlightType(...ranges));
  const active = matches[current] && domRange(matches[current].lineId, matches[current].start, matches[current].end);
  if (active) registry.set("script-search-current", new HighlightType(active));
  return () => {
    registry.delete("script-search");
    registry.delete("script-search-current");
  };
}

function createSearchFocusDimmer() {
  let layer: HTMLSpanElement | null = null;
  let windowElement: HTMLSpanElement | null = null;
  const clear = () => {
    layer?.remove();
    layer = null;
    windowElement = null;
    document.querySelector(".app-shell--script")?.classList.remove("has-search-focus-window");
  };
  const position = (line: HTMLElement | null) => {
    if (!line) return clear();
    const rect = line.getBoundingClientRect();
    if (!windowElement) {
      layer = document.createElement("span");
      layer.className = "script-search-dim-layer";
      layer.setAttribute("aria-hidden", "true");
      windowElement = document.createElement("span");
      windowElement.className = "script-search-focus-window";
      layer.append(windowElement);
      const shell = document.querySelector(".app-shell--script");
      shell?.append(layer);
      shell?.classList.add("has-search-focus-window");
    }
    const layerRect = layer!.getBoundingClientRect();
    Object.assign(windowElement.style, { left: `${rect.left}px`, top: `${rect.top - layerRect.top}px`, width: `${rect.width}px`, height: `${rect.height}px` });
  };
  return { clear, position };
}

function watchPaintedMatches(matches: ReturnType<typeof findScriptMatches>, current: number) {
  const canvas = document.querySelector<HTMLElement>(".script-canvas");
  let activeLine: HTMLElement | null = null;
  let clearPaint = () => {};
  let frame = 0;
  let pulseElements: HTMLSpanElement[] = [];
  let pulseDelay: ReturnType<typeof setTimeout> | null = null;
  const focusDimmer = createSearchFocusDimmer();
  const stopPulse = () => {
    if (pulseDelay !== null) clearTimeout(pulseDelay);
    pulseDelay = null;
    pulseElements.forEach((element) => element.remove());
    pulseElements = [];
  };
  const positionPulse = (range: Range, restart: boolean) => {
    const canvasRect = canvas?.getBoundingClientRect();
    const rects = [...range.getClientRects()].filter((rect) => rect.width > 0 && rect.height > 0 && rect.bottom >= 0 && rect.top <= window.innerHeight && (!canvasRect || (rect.bottom >= canvasRect.top && rect.top <= canvasRect.bottom)));
    if (restart || pulseElements.length !== rects.length) {
      stopPulse();
      pulseElements = rects.map(() => {
        const element = document.createElement("span");
        element.className = "script-search-pulse";
        element.setAttribute("aria-hidden", "true");
        document.body.append(element);
        return element;
      });
    }
    pulseElements.forEach((element, index) => {
      const rect = rects[index];
      element.style.left = `${rect.left}px`;
      element.style.top = `${rect.top}px`;
      element.style.width = `${rect.width}px`;
      element.style.height = `${rect.height}px`;
    });
  };
  const schedulePulse = (match: (typeof matches)[number]) => {
    if (pulseDelay !== null) clearTimeout(pulseDelay);
    pulseDelay = setTimeout(() => {
      pulseDelay = null;
      const range = domRange(match.lineId, match.start, match.end);
      if (range) positionPulse(range, true);
    }, 140);
  };
  const paint = () => {
    clearPaint();
    clearPaint = paintMatches(matches, current);
    const match = matches[current];
    const line = match ? document.querySelector<HTMLElement>(`[data-line-id="${CSS.escape(match.lineId)}"]`) : null;
    const changed = line !== activeLine;
    activeLine = line;
    focusDimmer.position(line);
    const range = match ? domRange(match.lineId, match.start, match.end) : null;
    if (range && pulseElements.length) positionPulse(range, false);
    else if (range && match) schedulePulse(match);
    else stopPulse();
    if (changed && range && match) schedulePulse(match);
  };
  const schedulePaint = () => {
    cancelAnimationFrame(frame);
    if (pulseElements.length || pulseDelay !== null) stopPulse();
    frame = requestAnimationFrame(paint);
  };
  paint();
  const observer = new MutationObserver(schedulePaint);
  if (canvas) {
    observer.observe(canvas, { childList: true, subtree: true });
    canvas.addEventListener("scroll", schedulePaint, { passive: true });
  }
  return () => {
    observer.disconnect();
    cancelAnimationFrame(frame);
    canvas?.removeEventListener("scroll", schedulePaint);
    stopPulse();
    focusDimmer.clear();
    clearPaint();
  };
}

export function ScriptSearchBar({ project, onFocusLine, onReplace }: { project: StudioProject; onFocusLine: (lineId: string) => void; onReplace: (updates: Map<string, Pick<DialogueLine, "text" | "pronunciations">>) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [replacement, setReplacement] = useState("");
  const [current, setCurrent] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const onFocusLineRef = useRef(onFocusLine);
  const scenes = project.scenes;
  const matches = useMemo(() => findScriptMatches({ scenes }, query), [query, scenes]);
  useEffect(() => {
    onFocusLineRef.current = onFocusLine;
  }, [onFocusLine]);
  useEffect(() => {
    if (current >= matches.length) setCurrent(0);
  }, [current, matches.length]);
  useEffect(
    () =>
      listenForScriptSearch(() => {
        setOpen(true);
        if (input.current) {
          input.current?.focus();
          input.current?.select();
        }
      }),
    [],
  );
  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    input.current?.select();
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape, true);
    return () => window.removeEventListener("keydown", closeOnEscape, true);
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const match = matches[current];
    if (match) return focusLine(match.lineId, onFocusLineRef.current);
  }, [current, matches, open]);
  useEffect(() => (open ? watchPaintedMatches(matches, current) : paintMatches([], current)), [current, matches, open]);
  const move = (step: number) => {
    if (matches.length) setCurrent((value) => (value + step + matches.length) % matches.length);
  };
  const replace = async (all: boolean) => {
    if (!query || !matches.length) return;
    const selected = all ? matches : [matches[current]];
    const updates = new Map<string, Pick<DialogueLine, "text" | "pronunciations">>();
    for (const scene of project.scenes)
      for (const line of scene.lines) {
        const lineMatches = selected.filter((item) => item.lineId === line.id);
        if (lineMatches.length) updates.set(line.id, replaceLineMatches(line.text, line.pronunciations, lineMatches, replacement));
      }
    await onReplace(updates);
  };
  if (!open) return null;
  return (
    <div
      className="script-search-bar"
      role="search"
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          move(event.shiftKey ? -1 : 1);
        }
      }}
    >
      <input
        ref={input}
        aria-label="検索"
        placeholder="検索"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setCurrent(0);
        }}
      />
      <span>
        {matches.length ? current + 1 : 0} / {matches.length}
      </span>
      <button type="button" aria-label="前の一致" disabled={!matches.length} onClick={() => move(-1)}>
        ↑
      </button>
      <button type="button" aria-label="次の一致" disabled={!matches.length} onClick={() => move(1)}>
        ↓
      </button>
      <input aria-label="置換" placeholder="置換" value={replacement} onChange={(event) => setReplacement(event.target.value)} />
      <button type="button" disabled={!matches.length} onClick={() => void replace(false)}>
        置換
      </button>
      <button type="button" disabled={!matches.length} onClick={() => void replace(true)}>
        すべて置換
      </button>
      <button type="button" aria-label="検索を閉じる" onClick={() => setOpen(false)}>
        ×
      </button>
    </div>
  );
}
