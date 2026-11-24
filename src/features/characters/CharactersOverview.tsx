import { useRef, useState } from "react";
import type { Character } from "../../types";
import { CharacterAvatarViewer } from "./CharacterAvatarViewer";
import type { CharactersViewModel } from "./useCharactersViewModel";

import { CastNotebook } from "./CastNotebook";
import { CastDeletionFeedback } from "./CastDeletionFeedback";
import { useCastDeletion } from "./useCastDeletion";
import { projectCharacterGroups } from "../shared/projectCharacterOrder";

function normalizeCastSearch(value: string) {
  return value.normalize("NFKC").toLocaleLowerCase("ja").trim();
}

export function CharactersOverview({ model, onImportCasts }: { model: CharactersViewModel; onImportCasts: () => void }) {
  const [castSearch, setCastSearch] = useState("");
  const [originalAvatar, setOriginalAvatar] = useState<{
    character: Character;
    origin: DOMRect;
  } | null>(null);
  const { project, busy, onDelete, onReorder, openVoiceDesign, setWavImportOpen, playReferenceAudio, playingReferenceCharacterId, beginEdit, voiceDesignUnavailableReason } = model;
  const normalizedCastSearch = normalizeCastSearch(castSearch);
  const { ordered: orderedCharacters, used } = projectCharacterGroups(project);
  const filtered = normalizedCastSearch ? orderedCharacters.filter((character) => normalizeCastSearch(character.name).includes(normalizedCastSearch)) : orderedCharacters;
  const deletion = useCastDeletion(filtered, onDelete);
  const notebookRegionRef = useRef<HTMLDivElement>(null);
  const visibleCharacters = deletion.characters;
  return (
    <>
      <div className="page-heading character-heading">
        <p className="eyebrow type-eyebrow">VOICE CAST</p>
        <h1 className="type-display">物語の声を、ここに集める</h1>
        <p className="type-body">声をつくるか、手元の参照WAVを迎え入れるか。キャストの性格はAI台本の会話づくりにも使われます。</p>
      </div>
      <div className="cast-action-buttons">
        <span className="disabled-reason-control cast-action-control" tabIndex={voiceDesignUnavailableReason ? 0 : undefined}>
          <button type="button" className="cast-action-button voice" disabled={Boolean(voiceDesignUnavailableReason)} aria-describedby={voiceDesignUnavailableReason ? "voice-design-create-reason" : undefined} onClick={openVoiceDesign}>
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 17h6v-6H4zm10 2h6v-6h-6zM10 10h4V6h-4zM6 8l2-2m7 5 2-2M12 2v2m-1-1h2" />
            </svg>
            <b>声をつくる</b>
            <small>VOICE DESIGN</small>
          </button>
          {voiceDesignUnavailableReason && (
            <span className="disabled-reason-tooltip" id="voice-design-create-reason" role="tooltip">
              {voiceDesignUnavailableReason}
            </span>
          )}
        </span>
        <button type="button" className="cast-action-button wav" onClick={() => setWavImportOpen(true)}>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="7.5" r="3.25" />
            <path d="M4.5 21c.35-4.25 3.45-7 7.5-7s7.15 2.75 7.5 7" />
          </svg>
          <b>WAVを登録</b>
          <small>REFERENCE WAV</small>
        </button>
        <button type="button" className="cast-action-button cast-import" onClick={onImportCasts}>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 3v12m-4-4 4 4 4-4M4 19h16" />
          </svg>
          <b>キャストインポート</b>
          <small>SCENA CAST</small>
        </button>
      </div>
      <section className="saved-characters">
        <div className="saved-heading">
          <div className="saved-heading-title">
            <p className="eyebrow">YOUR CAST</p>
            {project.characters.length > 0 && (
              <label className={`cast-search-field${castSearch ? " has-value" : ""}`}>
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <circle cx="10.5" cy="10.5" r="6.5" />
                  <path d="m15.5 15.5 5 5" />
                </svg>
                <input type="search" value={castSearch} disabled={Boolean(deletion.deletion)} aria-label="キャストを検索" onChange={(event) => setCastSearch(event.target.value)} />
              </label>
            )}
          </div>
          <span>{normalizedCastSearch ? `${visibleCharacters.length} / ${project.characters.length} 人` : `${project.characters.length} 人`}</span>
        </div>
        <CastDeletionFeedback deletion={deletion.deletion} regionRef={notebookRegionRef}>
          {visibleCharacters.length ? (
            <CastNotebook
              characters={visibleCharacters}
              usedCharacterIds={used}
              reorderDisabled={Boolean(normalizedCastSearch || busy || deletion.deletion)}
              onReorder={onReorder}
              onPlay={playReferenceAudio}
              playingCharacterId={playingReferenceCharacterId}
              onEdit={beginEdit}
              onDelete={(character) => void deletion.remove(character, notebookRegionRef.current)}
              onViewOriginalAvatar={(character, origin) => setOriginalAvatar({ character, origin })}
            />
          ) : project.characters.length ? (
            <div className="empty-state cast-search-empty">「{castSearch.trim()}」に一致するキャストはいません。</div>
          ) : (
            <div className="empty-state">まだ登録されていません。候補を採用するか、WAVを登録してください。</div>
          )}
        </CastDeletionFeedback>
      </section>
      {originalAvatar && <CharacterAvatarViewer character={originalAvatar.character} origin={originalAvatar.origin} onClose={() => setOriginalAvatar(null)} />}
    </>
  );
}
