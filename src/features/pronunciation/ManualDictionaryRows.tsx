import type { Dispatch, RefObject, SetStateAction } from "react";
import { useState } from "react";
import type { PronunciationDictionaryEntry } from "../../types";
import { DictionaryEditableCell } from "./DictionaryEditableCell";
import { DictionaryScopeCell } from "./DictionaryScopeCell";
import { dictionaryScopes, type DictionaryScope } from "./manualDictionaryShared";

export function NewManualRow({
  termInput,
  term,
  reading,
  saving,
  error,
  castConflict,
  occupiedScopes,
  requestedScopes,
  occupancyMessage,
  onTerm,
  onReading,
  onScopes,
  onCancel,
  onBlur,
}: {
  termInput: RefObject<HTMLInputElement | null>;
  term: string;
  reading: string;
  saving: boolean;
  error: string;
  castConflict: boolean;
  occupiedScopes: Set<DictionaryScope>;
  requestedScopes: Record<DictionaryScope, boolean>;
  occupancyMessage: string;
  onTerm: (value: string) => void;
  onReading: (value: string) => void;
  onScopes: Dispatch<SetStateAction<Record<DictionaryScope, boolean>>>;
  onCancel: () => void;
  onBlur: (target: EventTarget | null) => void;
}) {
  return (
    <tr className="dictionary-new-row" onBlur={(event) => onBlur(event.relatedTarget)}>
      <td>
        <input
          ref={termInput}
          value={term}
          aria-label="新しい語句"
          onChange={(event) => onTerm(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") onCancel();
          }}
          disabled={saving}
        />
        {castConflict && <small className="manual-conflict">キャスト語を上書き</small>}
        {occupancyMessage && (
          <small className={occupiedScopes.size === 2 ? "dictionary-inline-error" : "dictionary-scope-note"} role={occupiedScopes.size === 2 ? "alert" : undefined}>
            {occupancyMessage}
          </small>
        )}
      </td>
      <td>
        <input
          value={reading}
          aria-label="新しい読み"
          onChange={(event) => onReading(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") onCancel();
          }}
          disabled={saving}
        />
        {saving && <span className="dictionary-saving">保存中…</span>}
        {error && <small role="alert">{error}</small>}
      </td>
      <td>
        <div className="dictionary-scope-tags" aria-label="新規項目の保存先">
          {dictionaryScopes.map((scope) => {
            const disabled = occupiedScopes.has(scope);
            return (
              <button key={scope} type="button" className="dictionary-scope-tag" aria-pressed={!disabled && requestedScopes[scope]} disabled={disabled || saving} onClick={() => onScopes((current) => ({ ...current, [scope]: !current[scope] }))}>
                {scope === "global" ? "SCENA" : "PROJECT"}
              </button>
            );
          })}
        </div>
      </td>
    </tr>
  );
}

export function ManualDictionaryHeader({ suggestReadings, suggesting, llmBusy, onSuggest, onRequestAdd }: { suggestReadings: boolean; suggesting: boolean; llmBusy: boolean; onSuggest: () => Promise<void>; onRequestAdd: () => void }) {
  return (
    <div className="manual-dictionary-heading">
      <h2>手動追加</h2>
      <div className="dictionary-section-actions">
        {suggestReadings && (
          <button className={suggesting ? "is-suggesting" : ""} onClick={() => void onSuggest()} disabled={suggesting || llmBusy}>
            {suggesting ? "推測中…" : "読みを推測"}
          </button>
        )}
        <button onClick={onRequestAdd}>＋ 単語を追加</button>
      </div>
    </div>
  );
}

export function ManualRow({
  entry,
  suggested,
  castConflict,
  onSave,
  onLockChange,
  onToggleScope,
  scopeBusy,
  onNotice,
}: {
  entry: PronunciationDictionaryEntry;
  suggested: boolean;
  castConflict: boolean;
  onSave: (entry: PronunciationDictionaryEntry, term: string, reading: string) => Promise<void>;
  onLockChange: (entry: PronunciationDictionaryEntry, locked: boolean) => Promise<void>;
  onToggleScope: (entry: PronunciationDictionaryEntry, scope: "global" | "project", enabled: boolean) => Promise<void>;
  scopeBusy?: boolean;
  onNotice: (message: string) => void;
}) {
  const [term, setTerm] = useState(entry.term),
    [editingTerm, setEditingTerm] = useState(false),
    [error, setError] = useState("");
  const saveTerm = async () => {
    if (!term.trim()) return setError("語句を入力してください。");
    if (term === entry.term) {
      setEditingTerm(false);
      return;
    }
    try {
      await onSave(entry, term, entry.reading);
      setEditingTerm(false);
      setError("");
    } catch (reason) {
      setError((reason as Error).message);
      onNotice(`辞書を保存できません: ${(reason as Error).message}`);
    }
  };
  return (
    <tr>
      <td className="dictionary-term">
        {editingTerm ? (
          <>
            <input
              autoFocus
              value={term}
              aria-label={`${entry.term} の語句`}
              onChange={(event) => setTerm(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void saveTerm();
                if (event.key === "Escape") {
                  setTerm(entry.term);
                  setEditingTerm(false);
                }
              }}
              onBlur={() => void saveTerm()}
            />
            {error && <small role="alert">{error}</small>}
          </>
        ) : (
          <>
            <span className="manual-term-cell">
              <button className="dictionary-cell-button" onClick={() => setEditingTerm(true)}>
                {entry.term}
              </button>
            </span>
            {castConflict && <small className="manual-conflict">キャスト語を上書き</small>}
          </>
        )}
      </td>
      <td>
        <DictionaryEditableCell
          value={entry.reading}
          label={`${entry.term} の読み`}
          suggested={suggested}
          locked={entry.locked}
          onSave={async (reading) => {
            try {
              await onSave(entry, entry.term, reading);
            } catch (reason) {
              onNotice(`辞書を保存できません: ${(reason as Error).message}`);
              throw reason;
            }
          }}
          onLockChange={(locked) => onLockChange(entry, locked)}
        />
      </td>
      <td>
        <DictionaryScopeCell entry={entry} busy={scopeBusy} onToggle={(scope, enabled) => onToggleScope(entry, scope, enabled)} />
      </td>
    </tr>
  );
}
