import { useState, type Dispatch, type SetStateAction } from "react";
import type { PronunciationDictionaryChangeResult, PronunciationDictionaryEntry } from "../../types";
import type { ChangeDictionary } from "./usePronunciationDictionary";

export function useDictionarySuggestions({
  castEntries,
  manualEntries,
  changeDictionary,
  acceptChange,
  setLlmSuggestedIds,
  onNotice,
}: {
  castEntries: PronunciationDictionaryEntry[];
  manualEntries: PronunciationDictionaryEntry[];
  changeDictionary: ChangeDictionary;
  acceptChange: (result: PronunciationDictionaryChangeResult) => void;
  setLlmSuggestedIds: Dispatch<SetStateAction<Set<string>>>;
  onNotice: (message: string) => void;
}) {
  const [llmBusy, setLlmBusy] = useState(false);
  const runLlm = async (work: () => Promise<void>) => {
    if (llmBusy) return;
    setLlmBusy(true);
    try {
      await work();
    } finally {
      setLlmBusy(false);
    }
  };
  const suggest = async (source: PronunciationDictionaryEntry[], operation: "suggest-manual" | "suggest-cast") =>
    runLlm(async () => {
      const blank = new Set(source.filter((entry) => !entry.reading).map((entry) => entry.id));
      try {
        const result = await changeDictionary({ operation });
        acceptChange(result);
        const suggested = result.entries.filter((entry) => blank.has(entry.id) && entry.reading);
        setLlmSuggestedIds((current) => new Set([...current, ...suggested.map((entry) => entry.id)]));
        onNotice(suggested.length ? `${suggested.length}件の読みを推測しました。` : "読み候補を取得できませんでした。");
      } catch (error) {
        onNotice(`読みを推測できません: ${(error as Error).message}`);
      }
    });
  return {
    llmBusy,
    suggestManual: () => suggest(manualEntries, "suggest-manual"),
    suggestCast: () => suggest(castEntries, "suggest-cast"),
  };
}
