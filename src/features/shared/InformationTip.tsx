import { useId, useState } from "react";
import { createPortal } from "react-dom";

export function InformationTip({ ariaLabel, paragraphs }: { ariaLabel: string; paragraphs: string[] }) {
  const tooltipId = useId();
  const [position, setPosition] = useState<{ x: number; y: number; below: boolean } | null>(null);
  const show = (element: HTMLElement) => {
    const bounds = element.getBoundingClientRect();
    const halfWidth = 160;
    const gutter = 12;
    setPosition({ x: Math.min(window.innerWidth - gutter - halfWidth, Math.max(gutter + halfWidth, bounds.left + bounds.width / 2)), y: bounds.top < 150 ? bounds.bottom + 8 : bounds.top, below: bounds.top < 150 });
  };
  return (
    <span className="information-tip-control">
      <button type="button" className="information-tip" aria-label={ariaLabel} aria-describedby={tooltipId} onMouseEnter={(event) => show(event.currentTarget)} onMouseLeave={() => setPosition(null)} onFocus={(event) => show(event.currentTarget)} onBlur={() => setPosition(null)}>
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M5 5.5h14v10H10l-4.5 3v-3H5z" />
          <path d="M8.5 9h7M8.5 12h5" />
        </svg>
      </button>
      {position &&
        createPortal(
          <span className={`information-tip-tooltip${position.below ? " is-below" : ""}`} id={tooltipId} role="tooltip" style={{ left: position.x, top: position.y }}>
            {paragraphs.map((paragraph) => (
              <span key={paragraph}>{paragraph}</span>
            ))}
          </span>,
          document.body,
        )}
    </span>
  );
}
