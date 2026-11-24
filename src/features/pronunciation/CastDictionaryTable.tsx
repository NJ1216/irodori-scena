import type { Character, PronunciationDictionaryEntry } from "../../types";
import { CastEntryRows, CastNewRow } from "./CastDictionaryRows";
import { castDictionaryGroups } from "./castDictionaryOrder";
import { useCastDictionaryDraft } from "./useCastDictionaryDraft";

export function CastDictionaryTable({
  entries,
  characters,
  suggestReadings,
  llmBusy,
  suggestedIds,
  onSuggest,
  onAdd,
  onDelete,
  onSave,
  onLockChange,
  onNotice,
}: {
  entries: PronunciationDictionaryEntry[];
  characters: Character[];
  suggestReadings: boolean;
  llmBusy: boolean;
  suggestedIds: Set<string>;
  onSuggest: () => Promise<void>;
  onAdd: (characterId: string, term: string, reading: string) => Promise<void>;
  onDelete: (entry: PronunciationDictionaryEntry) => Promise<void>;
  onSave: (entry: PronunciationDictionaryEntry, term: string, reading: string) => Promise<void>;
  onLockChange: (entry: PronunciationDictionaryEntry, locked: boolean) => Promise<void>;
  onNotice: (message: string) => void;
}) {
  const draft = useCastDictionaryDraft({ characters, onAdd, onSuggest });
  const groups = castDictionaryGroups(entries, characters);
  if (!characters.length) return null;
  return (
    <section className="dictionary-section cast-dictionary-section">
      <div className="cast-dictionary-heading">
        <h2>キャスト由来</h2>
        <div className="dictionary-section-actions">
          {suggestReadings && (
            <button className={draft.suggesting ? "is-suggesting" : ""} onClick={() => void draft.suggest()} disabled={draft.suggesting || llmBusy}>
              {draft.suggesting ? "推測中…" : "読みを推測"}
            </button>
          )}
          <button onClick={draft.begin}>＋ 単語を追加</button>
        </div>
      </div>
      <div className="dictionary-table-wrap">
        <table className="dictionary-table cast-dictionary-table">
          <colgroup>
            <col className="dictionary-character-column" />
            <col className="dictionary-term-column" />
            <col className="dictionary-reading-column" />
          </colgroup>
          <thead>
            <tr>
              <th aria-label="キャスト" />
              <th>語句</th>
              <th>読み</th>
            </tr>
          </thead>
          <tbody>
            {draft.adding && (
              <CastNewRow
                characters={characters}
                selectedCharacter={draft.selectedCharacter}
                characterId={draft.characterId}
                term={draft.term}
                reading={draft.reading}
                saving={draft.saving}
                error={draft.error}
                termInput={draft.termInput}
                onCharacter={draft.setCharacterId}
                onTerm={draft.setTerm}
                onReading={draft.setReading}
                onCancel={draft.cancel}
                onBlur={draft.finishAdding}
              />
            )}
            <CastEntryRows groups={groups} suggestedIds={suggestedIds} onDelete={onDelete} onSave={onSave} onLockChange={onLockChange} onNotice={onNotice} />
          </tbody>
        </table>
      </div>
    </section>
  );
}
