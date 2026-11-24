import { useState } from "react";
import type { Character } from "../../types";
import { CharacterAvatarViewer } from "../characters/CharacterAvatarViewer";
import { avatarImageUrl } from "../shared/studio-utils";

export function ScriptCastAvatar({ character }: { character: Character }) {
  const [origin, setOrigin] = useState<DOMRect | null>(null);
  const thumbnailUrl = character.avatarThumbnailUrl ?? character.avatarUrl;
  if (!character.avatarOriginalUrl) {
    return <div className={`avatar${thumbnailUrl ? " has-image" : ""}`}>{thumbnailUrl ? <img src={avatarImageUrl(thumbnailUrl, character.avatarVersion)} alt={`${character.name}の画像`} /> : character.name.slice(0, 1)}</div>;
  }
  return (
    <>
      <button type="button" className="avatar has-image script-cast-avatar-button" aria-label={`${character.name}の原画像を表示`} onClick={(event) => setOrigin(event.currentTarget.getBoundingClientRect())}>
        {thumbnailUrl ? <img src={avatarImageUrl(thumbnailUrl, character.avatarVersion)} alt={`${character.name}の画像`} /> : character.name.slice(0, 1)}
      </button>
      {origin && <CharacterAvatarViewer character={character} origin={origin} onClose={() => setOrigin(null)} />}
    </>
  );
}
