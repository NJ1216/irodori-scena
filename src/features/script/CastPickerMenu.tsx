import type { CSSProperties } from "react";
import type { Character } from "../../types";
import { avatarImageUrl } from "../shared/studio-utils";

export function CastPickerMenu({
  characters,
  label,
  selectedId,
  align = "left",
  density = "standard",
  portalStyle,
  onChoose,
}: {
  characters: Character[];
  label: string;
  selectedId?: string;
  align?: "left" | "right";
  density?: "standard" | "compact";
  portalStyle?: CSSProperties;
  onChoose: (characterId: string) => void;
}) {
  return (
    <div className={`cast-picker-menu is-${align} is-${density}${portalStyle ? " is-portal" : ""}`} style={portalStyle} role="listbox" aria-label={label}>
      {characters.map((character) => {
        const selected = character.id === selectedId;
        return (
          <button type="button" key={character.id} className="cast-picker-option" role="option" aria-selected={selected} onClick={() => onChoose(character.id)}>
            <span className="cast-picker-option-avatar" aria-hidden="true">
              {character.avatarUrl ? <img src={avatarImageUrl(character.avatarUrl, character.avatarVersion)} alt="" /> : character.name.slice(0, 1)}
            </span>
            <span>{character.name}</span>
          </button>
        );
      })}
    </div>
  );
}
