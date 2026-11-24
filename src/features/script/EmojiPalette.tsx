import { IRODORI_EMOJI_PALETTE } from "../shared/studio-utils";
import { useEmojiTooltip } from "../shared/EmojiTooltip";
import { useEmojiPaletteDrag } from "./useEmojiPaletteDrag";

export function EmojiPalette({ onInsert, heading, dragToScript = false }: { onInsert: (emoji: string) => void; heading?: string; dragToScript?: boolean }) {
  const { emojiTooltip, hideEmojiTooltip, showEmojiTooltip } = useEmojiTooltip();
  const drag = useEmojiPaletteDrag(dragToScript, hideEmojiTooltip);
  return (
    <section className={`emoji-palette${heading ? " has-heading" : ""}${dragToScript ? " can-drag-to-script" : ""}`} aria-label="Irodori-TTS 表情絵文字パレット">
      {heading && <h3>{heading}</h3>}
      <div>
        {IRODORI_EMOJI_PALETTE.map(([emoji, effect]) => (
          <button
            key={emoji}
            type="button"
            aria-label={`${emoji}：${effect}`}
            onMouseEnter={(event) => showEmojiTooltip(effect, event.currentTarget)}
            onMouseLeave={hideEmojiTooltip}
            onFocus={(event) => showEmojiTooltip(effect, event.currentTarget)}
            onBlur={hideEmojiTooltip}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onInsert(emoji)}
            {...drag.handlersFor(emoji)}
          >
            <span className="emoji-palette-glyph" aria-hidden="true">
              {emoji}
            </span>
          </button>
        ))}
      </div>
      {emojiTooltip}
      {drag.overlay}
    </section>
  );
}
