import type { Placement } from "./modelSelectionTypes";

export function getPopoverPlacement(anchor: DOMRect, itemCount: number, preferredCardWidth: number): Placement {
  const gutter = 12;
  const gap = 12;
  const cardWidth = Math.min(anchor.width, preferredCardWidth);
  const popoverChrome = 26;
  const availableWidth = window.innerWidth - gutter * 2;
  const contentWidth = Math.max(cardWidth, availableWidth - popoverChrome);
  const fittingColumns = Math.max(1, Math.floor((contentWidth + gap) / (cardWidth + gap)));
  const columns = Math.min(itemCount, fittingColumns);
  const width = Math.min(availableWidth, columns * cardWidth + Math.max(0, columns - 1) * gap + popoverChrome);
  const below = window.innerHeight - anchor.bottom - gutter - gap;
  const above = anchor.top - gutter - gap;
  const flip = below < 220 && above > below;
  const maxHeight = Math.max(160, Math.min(420, flip ? above : below));
  const left = Math.min(Math.max(gutter, anchor.left), window.innerWidth - width - gutter);
  return { left, top: flip ? anchor.top - gap : anchor.bottom + gap, width, cardWidth, maxHeight, above: flip };
}
