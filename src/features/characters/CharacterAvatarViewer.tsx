import { useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";
import type { Character } from "../../types";
import { avatarImageUrl } from "../shared/studio-utils";

export function CharacterAvatarViewer({ character, origin, onClose }: { character: Character; origin?: DOMRect; onClose: () => void }) {
  const dialogRef = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || !origin) return;
    const target = dialog.getBoundingClientRect();
    const animation = dialog.animate(
      [
        {
          opacity: 0.3,
          transform: `translate(${origin.left - target.left}px, ${origin.top - target.top}px) scale(${origin.width / target.width}, ${origin.height / target.height})`,
        },
        { opacity: 1, transform: "none" },
      ],
      { duration: 260, easing: "cubic-bezier(.2, .8, .2, 1)" },
    );
    return () => animation.cancel();
  }, [origin]);
  if (!character.avatarOriginalUrl) return null;
  return createPortal(
    <div className="modal-backdrop avatar-original-backdrop" onClick={onClose}>
      <section ref={dialogRef} className="modal avatar-original-modal" role="dialog" aria-modal="true" aria-label={`${character.name}の原画像`}>
        <div className="avatar-original-heading">
          <div>
            <p className="eyebrow">ORIGINAL IMAGE</p>
            <h2>{character.name}</h2>
          </div>
          <button type="button" aria-label="原画像を閉じる">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 3l10 10M13 3L3 13" />
            </svg>
          </button>
        </div>
        <img src={avatarImageUrl(character.avatarOriginalUrl, character.avatarVersion)} alt={`${character.name}の原画像`} />
      </section>
    </div>,
    document.body,
  );
}
