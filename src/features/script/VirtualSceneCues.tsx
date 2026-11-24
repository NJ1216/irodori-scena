import { defaultRangeExtractor, useVirtualizer } from "@tanstack/react-virtual";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { DialogueCue } from "./dialogueCues";
import { includePinnedCueIndexes } from "./virtualCueRange";

export function VirtualSceneCues({ cues, focusedCueIndex, followedCueIndex, renderCue }: { cues: DialogueCue[]; focusedCueIndex: number | undefined; followedCueIndex: number | undefined; renderCue: (cue: DialogueCue) => ReactNode }) {
  const listRef = useRef<HTMLDivElement>(null);
  const [geometry, setGeometry] = useState({ margin: 0, gap: 0 });
  // eslint-disable-next-line react-hooks/incompatible-library -- The virtualizer owns DOM measurements locally.
  const virtualizer = useVirtualizer({
    count: cues.length,
    getScrollElement: () => listRef.current?.closest<HTMLElement>(".script-canvas") ?? null,
    estimateSize: (index) => 190 * cues[index].lines.length,
    getItemKey: (index) => cues[index].id,
    overscan: 10,
    scrollMargin: geometry.margin,
    gap: geometry.gap,
    useAnimationFrameWithResizeObserver: true,
    rangeExtractor: (range) => {
      const visible = defaultRangeExtractor(range);
      return includePinnedCueIndexes(visible, focusedCueIndex, followedCueIndex);
    },
  });

  useLayoutEffect(() => {
    const list = listRef.current;
    const canvas = list?.closest<HTMLElement>(".script-canvas");
    if (!list || !canvas) return;
    const measure = () => {
      const margin = list.getBoundingClientRect().top - canvas.getBoundingClientRect().top + canvas.scrollTop - canvas.clientTop;
      const gap = parseFloat(getComputedStyle(list).rowGap) || 0;
      setGeometry((previous) => (previous.margin === margin && previous.gap === gap ? previous : { margin, gap }));
    };
    measure();
    let frame = 0;
    const scheduleMeasure = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    const observer = new ResizeObserver(scheduleMeasure);
    observer.observe(canvas);
    // Earlier scenes can move this list without changing the list's own size.
    canvas.querySelectorAll(".scene-box, .project-title, .script-search-bar").forEach((element) => observer.observe(element));
    canvas.addEventListener("scroll", scheduleMeasure, { passive: true });
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      canvas.removeEventListener("scroll", scheduleMeasure);
    };
  }, [cues]);

  useLayoutEffect(() => {
    if (focusedCueIndex !== undefined) virtualizer.scrollToIndex(focusedCueIndex, { align: "auto" });
  }, [focusedCueIndex, virtualizer]);

  return (
    <div ref={listRef} className="virtual-scene-cues" style={{ height: virtualizer.getTotalSize() }}>
      {virtualizer.getVirtualItems().map((item) => (
        <div key={item.key} className="virtual-scene-cue" data-index={item.index} ref={virtualizer.measureElement} style={{ transform: `translateY(${item.start - geometry.margin}px)` }}>
          {renderCue(cues[item.index])}
        </div>
      ))}
    </div>
  );
}
