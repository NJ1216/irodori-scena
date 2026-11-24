import type { RefObject } from "react";
import type { Character, PronunciationDictionaryEntry } from "../../types";
import { avatarImageUrl } from "../shared/studio-utils";
import { DictionaryEditableCell } from "./DictionaryEditableCell";

export function CastNewRow({
  characters,
  selectedCharacter,
  characterId,
  term,
  reading,
  saving,
  error,
  termInput,
  onCharacter,
  onTerm,
  onReading,
  onCancel,
  onBlur,
}: {
  characters: Character[];
  selectedCharacter: Character;
  characterId: string;
  term: string;
  reading: string;
  saving: boolean;
  error: string;
  termInput: RefObject<HTMLInputElement | null>;
  onCharacter: (characterId: string) => void;
  onTerm: (term: string) => void;
  onReading: (reading: string) => void;
  onCancel: () => void;
  onBlur: (target: EventTarget | null) => void;
}) {
  return (
    <tr className="dictionary-new-row" onBlur={(event) => onBlur(event.relatedTarget)}>
      <td className="cast-avatar-picker">
        <span className="dictionary-avatar" title={selectedCharacter.name}>
          {selectedCharacter.avatarUrl ? <img src={avatarImageUrl(selectedCharacter.avatarUrl, selectedCharacter.avatarVersion)} alt={selectedCharacter.name} /> : selectedCharacter.name.slice(0, 1)}
        </span>
        <select value={characterId} aria-label="対象キャスト" onChange={(event) => onCharacter(event.target.value)} disabled={saving}>
          {characters.map((character) => (
            <option key={character.id} value={character.id}>
              {character.name}
            </option>
          ))}
        </select>
      </td>
      <td>
        <input
          ref={termInput}
          value={term}
          aria-label="キャスト語句"
          onChange={(event) => onTerm(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") onCancel();
          }}
          disabled={saving}
        />
      </td>
      <td>
        <input
          value={reading}
          aria-label="キャスト語句の読み"
          onChange={(event) => onReading(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") onCancel();
          }}
          disabled={saving}
        />
        {saving && <span className="dictionary-saving">保存中…</span>}
        {error && <small role="alert">{error}</small>}
      </td>
    </tr>
  );
}

export function CastEntryRows({
  groups,
  suggestedIds,
  onDelete,
  onSave,
  onLockChange,
  onNotice,
}: {
  groups: { character: Character; rows: PronunciationDictionaryEntry[] }[];
  suggestedIds: Set<string>;
  onDelete: (entry: PronunciationDictionaryEntry) => Promise<void>;
  onSave: (entry: PronunciationDictionaryEntry, term: string, reading: string) => Promise<void>;
  onLockChange: (entry: PronunciationDictionaryEntry, locked: boolean) => Promise<void>;
  onNotice: (message: string) => void;
}) {
  return (
    <>
      {groups.flatMap(({ character, rows }) =>
        rows.map((entry, index) => (
          <tr key={entry.id}>
            {index === 0 && (
              <th className="dictionary-character" scope="rowgroup" rowSpan={rows.length}>
                <span className="dictionary-avatar" title={character.name}>
                  {character.avatarUrl ? <img src={avatarImageUrl(character.avatarUrl, character.avatarVersion)} alt={character.name} /> : character.name.slice(0, 1)}
                </span>
              </th>
            )}
            <td className="dictionary-term">
              {entry.sourceKeys.includes("manual") ? (
                <span className="manual-term-cell">
                  <span>{entry.term}</span>
                  <button className="dictionary-delete" aria-label={`${entry.term}を削除`} onClick={() => void onDelete(entry).catch((reason) => onNotice((reason as Error).message))}>
                    ×
                  </button>
                </span>
              ) : (
                entry.term
              )}
            </td>
            <td>
              <DictionaryEditableCell
                value={entry.reading}
                label={`${entry.term} の読み`}
                suggested={suggestedIds.has(entry.id)}
                locked={entry.locked}
                onSave={async (nextReading) => {
                  try {
                    await onSave(entry, entry.term, nextReading);
                  } catch (reason) {
                    onNotice(`辞書を保存できません: ${(reason as Error).message}`);
                    throw reason;
                  }
                }}
                onLockChange={(locked) => onLockChange(entry, locked)}
              />
            </td>
          </tr>
        )),
      )}
    </>
  );
}
