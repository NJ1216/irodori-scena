/* eslint-disable react-hooks/set-state-in-effect -- This hook synchronizes controlled drafts and focus at explicit boundaries. */
import { useEffect, useRef, useState } from "react";
import type { PronunciationDictionaryEntry } from "../../types";
import { dictionaryScopes, termKey, type DictionaryScope } from "./manualDictionaryShared";

export function useManualDictionaryDraft({ entries, addRequest, onAdd, onSuggest }: { entries: PronunciationDictionaryEntry[]; addRequest: number; onAdd: (term: string, reading: string, scopes: DictionaryScope[]) => Promise<void>; onSuggest: () => Promise<void> }) {
  const [adding, setAdding] = useState(false),
    [term, setTerm] = useState(""),
    [reading, setReading] = useState(""),
    [saving, setSaving] = useState(false),
    [suggesting, setSuggesting] = useState(false),
    [error, setError] = useState(""),
    [requestedScopes, setRequestedScopes] = useState<Record<DictionaryScope, boolean>>({ global: true, project: true });
  const termInput = useRef<HTMLInputElement>(null);
  const begin = () => {
    setAdding(true);
    setError("");
  };
  useEffect(() => {
    if (adding) termInput.current?.focus();
  }, [adding]);
  useEffect(() => {
    if (addRequest) begin();
  }, [addRequest]);
  const cancel = () => {
    setAdding(false);
    setTerm("");
    setReading("");
    setError("");
    setRequestedScopes({ global: true, project: true });
  };
  const occupiedScopes = new Set<DictionaryScope>(entries.filter((entry) => termKey(entry.term) === termKey(term)).flatMap((entry) => entry.scopes ?? (["global"] as DictionaryScope[])));
  const selectedScopes = dictionaryScopes.filter((scope) => !occupiedScopes.has(scope) && requestedScopes[scope]);
  const occupancyMessage = occupiedScopes.size === 2 ? "SCENAとPROJECTの両方に登録済みです。既存行を編集してください。" : occupiedScopes.has("global") ? "SCENAには登録済みです。PROJECT用の読みを追加します。" : occupiedScopes.has("project") ? "PROJECTには登録済みです。SCENA用の読みを追加します。" : "";
  const add = async () => {
    if (!term.trim()) return setError("語句を入力してください。");
    if (!selectedScopes.length) {
      if (occupiedScopes.size < 2) setError("保存先を1つ以上選択してください。");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await onAdd(term, reading, selectedScopes);
      cancel();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const finishAdding = (nextTarget: EventTarget | null) => {
    if (nextTarget instanceof HTMLElement && nextTarget.closest(".dictionary-new-row")) return;
    if (!term.trim() && !reading) cancel();
    else void add();
  };
  const suggest = async () => {
    setSuggesting(true);
    try {
      await onSuggest();
    } finally {
      setSuggesting(false);
    }
  };
  return { adding, term, setTerm, reading, setReading, saving, suggesting, error, setError, requestedScopes, setRequestedScopes, termInput, occupiedScopes, occupancyMessage, cancel, finishAdding, suggest };
}
