/* eslint-disable react-hooks/set-state-in-effect -- This component synchronizes controlled drafts, imperative media, or stable lifecycle owners at explicit boundaries. */
import { useEffect, useRef, useState } from "react";
import { PinIcon } from "../shared/PinIcon";

export function DictionaryEditableCell({ value, label, suggested = false, locked = false, onSave, onLockChange }: { value: string; label: string; suggested?: boolean; locked?: boolean; onSave: (value: string) => Promise<void>; onLockChange: (locked: boolean) => Promise<void> }) {
  const [editing, setEditing] = useState(false),
    [draft, setDraft] = useState(value),
    [saving, setSaving] = useState(false),
    [locking, setLocking] = useState(false),
    [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const skipBlurSave = useRef(false);
  useEffect(() => {
    if (!editing) setDraft(value);
  }, [editing, value]);
  useEffect(() => {
    if (editing) input.current?.focus();
  }, [editing]);
  const cancel = () => {
    skipBlurSave.current = true;
    setDraft(value);
    setError("");
    setEditing(false);
  };
  const save = async () => {
    if (skipBlurSave.current) {
      skipBlurSave.current = false;
      return;
    }
    if (saving || !editing) return;
    if (draft === value) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setError("");
    try {
      await onSave(draft);
      setEditing(false);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const toggleLock = async () => {
    if (locking) return;
    setLocking(true);
    setError("");
    try {
      await onLockChange(!locked);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setLocking(false);
    }
  };
  if (!editing)
    return (
      <div className="dictionary-reading-cell">
        <button className={`dictionary-cell-button${suggested ? " is-llm-suggested" : ""}`} onClick={() => setEditing(true)} aria-label={`${label}を編集`}>
          {value || <em>未設定</em>}
        </button>
        {!value && (
          <button className={`dictionary-lock${locked ? " is-locked" : ""}`} onClick={() => void toggleLock()} aria-label={`${label}を${locked ? "固定解除" : "固定"}`} aria-pressed={locked} disabled={locking}>
            <PinIcon />
          </button>
        )}
        {error && <small role="alert">{error}</small>}
      </div>
    );
  return (
    <div className="dictionary-cell-editor">
      <input
        ref={input}
        value={draft}
        aria-label={label}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") void save();
          if (event.key === "Escape") cancel();
        }}
        onBlur={() => void save()}
        disabled={saving}
      />
      {saving && <span className="dictionary-saving">保存中…</span>}
      {error && <small role="alert">{error}</small>}
    </div>
  );
}
