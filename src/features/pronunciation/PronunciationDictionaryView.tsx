import type { Character } from "../../types";
import { CastDictionaryTable } from "./CastDictionaryTable";
import { ManualDictionaryTable } from "./ManualDictionaryTable";
import { RegenerationDialog, ScopeConflictDialog, ScopeRemovalDialog } from "./PronunciationDictionaryDialogs";
import { usePronunciationDictionary } from "./usePronunciationDictionary";

function PronunciationHeading({ suggestReadings, onChange }: { suggestReadings: boolean; onChange: (value: boolean) => void }) {
  return (
    <div className="page-heading accent-heading pronunciation-title-heading">
      <div>
        <p className="eyebrow type-eyebrow">PRONUNCIATION</p>
        <h1 className="type-display">読み辞書</h1>
        <p className="type-body">台本本文を合成直前に読みへ置き換えます。読み以外の台本・テイクは変わりません。</p>
      </div>
      <label className="pronunciation-llm-toggle">
        <input type="checkbox" checked={suggestReadings} onChange={(event) => onChange(event.target.checked)} />
        LLMの使用
      </label>
    </div>
  );
}

function PronunciationCaution() {
  return (
    <p className="pronunciation-caution" role="note">
      <span className="pronunciation-caution-mark" aria-label="注意">
        ！
      </span>
      <span>
        Irodori-TTSがすでに自然に読める語にも読みを設定すると、イントネーションが不自然になることがあります。
        <br />
        不必要な場合は値を空欄にして未設定にし、固定化してください。
      </span>
    </p>
  );
}

export function PronunciationDictionaryView({ characters, onNotice, onRegenerate }: { characters: Character[]; onNotice: (message: string) => void; onRegenerate: (ids: string[], mode: "append" | "replace") => Promise<void> }) {
  const d = usePronunciationDictionary(characters, onNotice);
  const { castEntries, manualEntries, scopeConflict, scopeRemoval } = d;
  return (
    <section className="page pronunciation-page">
      <PronunciationHeading suggestReadings={d.suggestReadings} onChange={d.changeSuggestReadings} />
      <PronunciationCaution />
      <div className="pronunciation-summary">
        キャスト語 {castEntries.length}件 / 手動 {manualEntries.length}件
      </div>
      <div className="pronunciation-dictionary-columns">
        <CastDictionaryTable entries={castEntries} characters={characters} suggestReadings={d.suggestReadings} llmBusy={d.llmBusy} suggestedIds={d.llmSuggestedIds} onSuggest={d.suggestCast} onAdd={d.addCast} onDelete={d.removeCast} onSave={d.save} onLockChange={d.setLock} onNotice={onNotice} />
        <ManualDictionaryTable
          entries={manualEntries}
          castTerms={new Set(castEntries.map((entry) => entry.term.toLocaleLowerCase()))}
          suggestReadings={d.suggestReadings}
          llmBusy={d.llmBusy}
          suggestedIds={d.llmSuggestedIds}
          addRequest={d.addRequest}
          onRequestAdd={d.requestAdd}
          onSuggest={d.suggestManual}
          onSave={d.save}
          onLockChange={d.setLock}
          onAdd={d.add}
          onToggleScope={d.toggleScope}
          scopeBusy={d.scopeBusy}
          onNotice={onNotice}
        />
      </div>
      {d.loaded && !characters.length && <div className="pronunciation-empty">キャストを登録すると、名前や一人称の読みをここで確認できます。</div>}
      {d.loaded && characters.length > 0 && !castEntries.length && <div className="pronunciation-empty">キャスト名・姓名・一人称を設定すると自動で同期されます。</div>}
      {d.affectedLineIds.length > 0 && <RegenerationDialog ids={d.affectedLineIds} mode={d.regenerationMode} onMode={d.setRegenerationMode} onClose={d.clearAffectedLines} onRegenerate={onRegenerate} />}
      {scopeConflict && (
        <ScopeConflictDialog
          conflict={scopeConflict}
          onClose={() => d.setScopeConflict(null)}
          onReplace={async () => {
            const { entry, scope, enabled } = scopeConflict;
            d.setScopeConflict(null);
            d.acceptChange(await d.changeDictionary({ operation: "toggle-scope", scope, enabled, global_id: entry.globalId ?? "", project_id: entry.projectId ?? "", replace_conflict: true }));
          }}
        />
      )}
      {scopeRemoval && (
        <ScopeRemovalDialog
          removal={scopeRemoval}
          onClose={() => d.setScopeRemoval(null)}
          onRemove={async () => {
            const { entry, scope } = scopeRemoval;
            d.setScopeRemoval(null);
            await d.applyScopeChange(entry, scope, false);
          }}
        />
      )}
    </section>
  );
}
