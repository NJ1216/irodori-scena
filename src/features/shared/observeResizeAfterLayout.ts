/** Keep layout writes out of ResizeObserver's synchronous delivery loop. */
export function observeResizeAfterLayout(update: () => void, elements: Element[]) {
  if (typeof ResizeObserver === "undefined") return () => {};
  let frame: number | undefined;
  const observer = new ResizeObserver(() => {
    if (frame !== undefined) cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      frame = undefined;
      update();
    });
  });
  elements.forEach((element) => observer.observe(element));
  return () => {
    observer.disconnect();
    if (frame !== undefined) cancelAnimationFrame(frame);
  };
}
