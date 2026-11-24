import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

type TooltipState = {
  effect: string;
  x: number;
  y: number;
  below: boolean;
};

/** Shared portal tooltip for Irodori expression emoji controls. */
export function useEmojiTooltip() {
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  useEffect(() => {
    const dismiss = () => setTooltip(null);
    window.addEventListener("scroll", dismiss, true);
    return () => window.removeEventListener("scroll", dismiss, true);
  }, []);

  return {
    hideEmojiTooltip: () => setTooltip(null),
    showEmojiTooltip: (effect: string, element: HTMLElement) => {
      const rect = element.getBoundingClientRect();
      setTooltip({
        effect,
        x: rect.left + rect.width / 2,
        y: rect.top,
        below: rect.top < 44,
      });
    },
    showEmojiTooltipAt: (effect: string, x: number, y: number) => {
      setTooltip({ effect, x, y, below: y < 44 });
    },
    emojiTooltip: tooltip
      ? createPortal(
          <span className={`emoji-tooltip${tooltip.below ? " is-below" : ""}`} style={{ left: tooltip.x, top: tooltip.y }} role="tooltip">
            {tooltip.effect}
          </span>,
          document.body,
        )
      : null,
  };
}
