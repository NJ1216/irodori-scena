import type { PronunciationDictionaryEntry } from "../../types";
import { InformationTip } from "../shared/InformationTip";
import { ManualDictionaryHeader, ManualRow, NewManualRow } from "./ManualDictionaryRows";
import { termKey, type DictionaryScope } from "./manualDictionaryShared";
import { useManualDictionaryDraft } from "./useManualDictionaryDraft";

export function ManualDictionaryTable({
  entries,
  castTerms,
  suggestReadings,
  llmBusy,
  suggestedIds,
  addRequest,
  onRequestAdd,
  onSuggest,
  onSave,
  onLockChange,
  onAdd,
  onToggleScope,
  scopeBusy,
  onNotice,
}: {
  entries: PronunciationDictionaryEntry[];
  castTerms: Set<string>;
  suggestReadings: boolean;
  llmBusy: boolean;
  suggestedIds: Set<string>;
  addRequest: number;
  onRequestAdd: () => void;
  onSuggest: () => Promise<void>;
  onSave: (entry: PronunciationDictionaryEntry, term: string, reading: string) => Promise<void>;
  onLockChange: (entry: PronunciationDictionaryEntry, locked: boolean) => Promise<void>;
  onAdd: (term: string, reading: string, scopes: DictionaryScope[]) => Promise<void>;
  onToggleScope: (entry: PronunciationDictionaryEntry, scope: "global" | "project", enabled: boolean) => Promise<void>;
  scopeBusy?: boolean;
  onNotice: (message: string) => void;
}) {
  const draft = useManualDictionaryDraft({ entries, addRequest, onAdd, onSuggest });
  const { term, error, requestedScopes } = draft;
  return (
    <section className="dictionary-section manual-dictionary-section">
      <ManualDictionaryHeader suggestReadings={suggestReadings} suggesting={draft.suggesting} llmBusy={llmBusy} onSuggest={draft.suggest} onRequestAdd={onRequestAdd} />
      <div className="dictionary-table-wrap">
        <table className="dictionary-table manual-dictionary-table">
          <colgroup>
            <col className="dictionary-term-column" />
            <col className="dictionary-reading-column" />
            <col className="dictionary-scope-column" />
          </colgroup>
          <thead>
            <tr>
              <th>語句</th>
              <th>読み</th>
              <th>
                <span className="dictionary-scope-heading">
                  保存先
                  <InformationTip ariaLabel="保存先の説明" paragraphs={["SCENA：アプリ本体の共通辞書に保存され、すべてのプロジェクトで使えます。", "PROJECT：現在のプロジェクトファイル（.scena）に保存されます。", "PROJECTがオフでも、SCENAの読みが音声生成で実際に使われ、生成に成功するとPROJECTにも自動保存されます。"]} />
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {draft.adding && (
              <NewManualRow
                termInput={draft.termInput}
                term={term}
                reading={draft.reading}
                saving={draft.saving}
                error={error}
                castConflict={castTerms.has(termKey(term))}
                occupiedScopes={draft.occupiedScopes}
                requestedScopes={requestedScopes}
                occupancyMessage={draft.occupancyMessage}
                onTerm={(value) => {
                  draft.setTerm(value);
                  draft.setError("");
                }}
                onReading={draft.setReading}
                onScopes={draft.setRequestedScopes}
                onCancel={draft.cancel}
                onBlur={draft.finishAdding}
              />
            )}
            {entries.map((entry) => (
              <ManualRow key={`${entry.globalId ?? ""}:${entry.projectId ?? ""}`} entry={entry} suggested={suggestedIds.has(entry.id)} castConflict={castTerms.has(entry.term.toLocaleLowerCase())} onSave={onSave} onLockChange={onLockChange} onToggleScope={onToggleScope} scopeBusy={scopeBusy} onNotice={onNotice} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
