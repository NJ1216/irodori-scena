import { useEffect, useState } from "react";
import { EmojiPalette } from "../script/EmojiPalette";
import { listenForExpressionPaletteToggle } from "../script/expressionPaletteEvents";
import { PinIcon } from "../shared/PinIcon";

type VisibilityOverride = "open" | "closed" | null;

export function ExpressionPaletteMenu({ onInsertEmoji }: { onInsertEmoji: (emoji: string) => void }) {
  const [pinned, setPinned] = useState(false);
  const [visibility, setVisibility] = useState<VisibilityOverride>(null);
  const [pointerInside, setPointerInside] = useState(false);
  const [focusWithin, setFocusWithin] = useState(false);

  useEffect(
    () =>
      listenForExpressionPaletteToggle(() => {
        if (document.documentElement.classList.contains("is-dragging-expression-emoji")) return;
        setVisibility((current) => {
          if (current === "open") return "closed";
          if (current === "closed") return "open";
          return pinned || pointerInside || focusWithin ? "closed" : "open";
        });
      }),
    [focusWithin, pinned, pointerInside],
  );

  return (
    <div
      className={`main-window-footer-item main-window-expression-menu${pinned ? " is-pinned" : ""}${visibility ? ` is-keyboard-${visibility}` : ""}`}
      onMouseDown={(event) => event.preventDefault()}
      onMouseEnter={() => {
        setVisibility(null);
        setPointerInside(true);
      }}
      onMouseLeave={() => setPointerInside(false)}
      onFocusCapture={() => {
        setVisibility(null);
        setFocusWithin(true);
      }}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setFocusWithin(false);
      }}
    >
      <button type="button" aria-label="表情パレット" aria-pressed={pinned}>
        <span aria-hidden="true">☺</span>
        <span>表情パレット</span>
      </button>
      <section className="main-window-footer-submenu main-window-expression-submenu" aria-label="表情パレットメニュー">
        <header>
          <strong>表情パレット</strong>
          <button
            type="button"
            className="main-window-submenu-pin"
            aria-label={pinned ? "表情パレットのピン留めを解除" : "表情パレットをピン留め"}
            aria-pressed={pinned}
            title={pinned ? "ピン留めを解除" : "表示をピン留め"}
            onClick={() => {
              setVisibility(null);
              setPinned((current) => !current);
            }}
          >
            <PinIcon />
          </button>
        </header>
        <EmojiPalette onInsert={onInsertEmoji} dragToScript />
      </section>
    </div>
  );
}
