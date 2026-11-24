import { useRef } from "react";
import { useEmojiTooltip } from "../shared/EmojiTooltip";
import { IRODORI_EMOJI_PALETTE } from "../shared/studio-utils";

const effects = new Map<string, string>(IRODORI_EMOJI_PALETTE);
const emojis = [...effects.keys()].sort((left, right) => right.length - left.length);
const isReadingNode = (node: Node) => node.parentElement?.closest("rt") !== null;

function emojiAtPointer(root: HTMLElement, x: number, y: number) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, { acceptNode: (node) => (isReadingNode(node) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT) });
  let node: Node | null;
  while ((node = walker.nextNode())) {
    const text = node.textContent ?? "";
    for (let index = 0; index < text.length;) {
      const emoji = emojis.find((candidate) => text.startsWith(candidate, index));
      if (!emoji) {
        index += (text.codePointAt(index) ?? 0) > 0xffff ? 2 : 1;
        continue;
      }
      const range = document.createRange();
      range.setStart(node, index);
      range.setEnd(node, index + emoji.length);
      if ([...range.getClientRects()].some((rect) => x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom)) return emoji;
      index += emoji.length;
    }
  }
  return null;
}

export function useEmojiHover() {
  const active = useRef<string | null>(null);
  const { emojiTooltip, hideEmojiTooltip, showEmojiTooltipAt } = useEmojiTooltip();
  const hideEmoji = () => {
    active.current = null;
    hideEmojiTooltip();
  };
  const showEmojiAtPointer = (event: React.MouseEvent<HTMLDivElement>) => {
    const emoji = emojiAtPointer(event.currentTarget, event.clientX, event.clientY);
    if (!emoji) {
      if (active.current) hideEmoji();
      return;
    }
    if (emoji === active.current) return;
    active.current = emoji;
    showEmojiTooltipAt(effects.get(emoji) ?? "", event.clientX, event.clientY);
  };
  return { emojiTooltip, hideEmoji, showEmojiAtPointer };
}
