import { useEffect, useRef, useState } from "react";
import type { Character } from "../../types";

export function useCastDictionaryDraft({ characters, onAdd, onSuggest }: { characters: Character[]; onAdd: (characterId: string, term: string, reading: string) => Promise<void>; onSuggest: () => Promise<void> }) {
  const [adding, setAdding] = useState(false),
    [characterId, setCharacterId] = useState(""),
    [term, setTerm] = useState(""),
    [reading, setReading] = useState(""),
    [saving, setSaving] = useState(false),
    [suggesting, setSuggesting] = useState(false),
    [error, setError] = useState("");
  const termInput = useRef<HTMLInputElement>(null);
  const selectedCharacter = characters.find((character) => character.id === characterId) ?? characters[0];
  useEffect(() => {
    if (adding) termInput.current?.focus();
  }, [adding]);
  const begin = () => {
    setAdding(true);
    setCharacterId(characters[0].id);
    setTerm("");
    setReading("");
    setError("");
  };
  const cancel = () => {
    setAdding(false);
    setTerm("");
    setReading("");
    setError("");
  };
  const add = async () => {
    if (!characterId) return setError("キャストを選択してください。");
    if (!term.trim()) return setError("語句を入力してください。");
    setSaving(true);
    setError("");
    try {
      await onAdd(characterId, term, reading);
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
  return { adding, characterId, setCharacterId, term, setTerm, reading, setReading, saving, suggesting, error, termInput, selectedCharacter, begin, cancel, finishAdding, suggest };
}
