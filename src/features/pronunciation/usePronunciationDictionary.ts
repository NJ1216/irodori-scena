import { useCallback, useEffect, useRef, useState } from "react";
import { api, HISTORY_APPLIED_EVENT } from "../../api";
import type { Character, PronunciationDictionaryChangeResult, PronunciationDictionaryEntry } from "../../types";
import { useDictionaryScopeChanges } from "./useDictionaryScopeChanges";
import { useDictionarySuggestions } from "./useDictionarySuggestions";

let cachedEntries: PronunciationDictionaryEntry[] | null = null;
let cachedSuggestReadings = globalThis.localStorage?.getItem("pronunciation-suggest-readings") !== "false";

export type ChangeDictionary = (request: Parameters<typeof api.changePronunciationDictionary>[0]) => Promise<PronunciationDictionaryChangeResult>;

export function cacheSuggestReadings(next: boolean) {
  cachedSuggestReadings = next;
  globalThis.localStorage?.setItem("pronunciation-suggest-readings", String(next));
}

function useReloadAfterPronunciationHistory(load: () => Promise<void>) {
  useEffect(() => {
    const reload = (event: Event) => {
      if (event instanceof CustomEvent && event.detail === "pronunciation") void load();
    };
    window.addEventListener(HISTORY_APPLIED_EVENT, reload);
    return () => window.removeEventListener(HISTORY_APPLIED_EVENT, reload);
  }, [load]);
}

function useInitialLoad(load: () => Promise<void>) {
  useEffect(() => void load(), [load]);
}

function useReloadAfterCastChange(characters: Character[], loaded: boolean, load: () => Promise<void>) {
  const revision = JSON.stringify(characters.map((character) => [character.id, character.name, character.profileDetails]));
  useEffect(() => {
    if (loaded) void load();
  }, [revision]); // eslint-disable-line react-hooks/exhaustive-deps
}

function useDictionaryMutationQueue(setBusy: (busy: boolean) => void) {
  const mutationQueue = useRef<Promise<void>>(Promise.resolve());
  const queuedChanges = useRef(0);
  const queueMutation = <T>(work: () => Promise<T>): Promise<T> => {
    queuedChanges.current += 1;
    setBusy(true);
    const result = mutationQueue.current.then(work);
    mutationQueue.current = result
      .then(
        () => undefined,
        () => undefined,
      )
      .finally(() => {
        queuedChanges.current -= 1;
        if (queuedChanges.current === 0) setBusy(false);
      });
    return result;
  };
  return queueMutation;
}

export function usePronunciationDictionary(characters: Character[], onNotice: (message: string) => void) {
  const [entries, setEntries] = useState<PronunciationDictionaryEntry[]>(() => cachedEntries ?? []);
  const [loaded, setLoaded] = useState(cachedEntries !== null);
  const [suggestReadings, setSuggestReadings] = useState(cachedSuggestReadings);
  const [addRequest, setAddRequest] = useState(0);
  const [scopeBusy, setScopeBusy] = useState(false);
  const queueMutation = useDictionaryMutationQueue(setScopeBusy);
  const changeDictionary: ChangeDictionary = (request) => queueMutation(() => api.changePronunciationDictionary(request));
  const [llmSuggestedIds, setLlmSuggestedIds] = useState<Set<string>>(() => new Set());
  const [affectedLineIds, setAffectedLineIds] = useState<string[]>([]);
  const [regenerationMode, setRegenerationMode] = useState<"append" | "replace">("append");
  const acceptChange = (result: PronunciationDictionaryChangeResult) => {
    cachedEntries = result.entries;
    setEntries(result.entries);
    if (result.affectedLineIds.length) {
      setRegenerationMode("append");
      setAffectedLineIds(result.affectedLineIds);
    }
  };
  const load = useCallback(
    async (nextSuggestReadings = cachedSuggestReadings) => {
      try {
        const result = await api.pronunciationDictionary(nextSuggestReadings);
        cachedEntries = result;
        setEntries(result);
      } catch (error) {
        onNotice(`辞書を読み込めません: ${(error as Error).message}`);
      } finally {
        setLoaded(true);
      }
    },
    [onNotice],
  );
  useInitialLoad(load);
  useReloadAfterPronunciationHistory(load);
  useReloadAfterCastChange(characters, loaded, load);
  const castEntries = entries.filter((entry) => entry.source === "cast");
  const manualEntries = entries.filter((entry) => entry.source === "manual");
  const suggestions = useDictionarySuggestions({ castEntries, manualEntries, changeDictionary, acceptChange, setLlmSuggestedIds, onNotice });
  const scopeChanges = useDictionaryScopeChanges({ entries, changeDictionary, acceptChange, onNotice });
  const addCast = async (characterId: string, term: string, reading: string) => acceptChange(await changeDictionary({ operation: "add-cast", character_id: characterId, term, reading }));
  const removeCast = async (entry: PronunciationDictionaryEntry) => acceptChange(await changeDictionary({ operation: "delete-cast", entry_id: entry.id }));
  const save = async (entry: PronunciationDictionaryEntry, term: string, reading: string) => {
    const result =
      entry.source === "manual" ? await changeDictionary({ operation: "update-manual", entry_id: entry.id, global_id: entry.globalId ?? "", project_id: entry.projectId ?? "", term, reading, locked: entry.locked }) : await changeDictionary({ operation: "update-cast", entry_id: entry.globalId ?? entry.id, reading });
    acceptChange(result);
    setLlmSuggestedIds((current) => new Set([...current].filter((id) => id !== entry.id)));
  };
  const setLock = async (entry: PronunciationDictionaryEntry, locked: boolean) => {
    if (entry.source === "manual") {
      acceptChange(await changeDictionary({ operation: "update-manual", global_id: entry.globalId ?? "", project_id: entry.projectId ?? "", term: entry.term, reading: entry.reading, locked }));
      return;
    }
    const result = await queueMutation(() => api.setPronunciationLock(entry.id, locked));
    setEntries((current) => {
      const next = current.map((item) => (item.id === entry.id ? result : item));
      cachedEntries = next;
      return next;
    });
  };
  const add = async (term: string, reading: string, scopes: Array<"global" | "project">) => {
    acceptChange(await changeDictionary({ operation: "add-manual", term, reading, scopes }));
  };
  return {
    entries,
    loaded,
    castEntries,
    manualEntries,
    suggestReadings,
    changeSuggestReadings: (next: boolean) => {
      cacheSuggestReadings(next);
      setSuggestReadings(next);
    },
    addRequest,
    requestAdd: () => setAddRequest((value) => value + 1),
    scopeBusy,
    llmSuggestedIds,
    affectedLineIds,
    clearAffectedLines: () => setAffectedLineIds([]),
    regenerationMode,
    setRegenerationMode,
    acceptChange,
    changeDictionary,
    addCast,
    removeCast,
    save,
    setLock,
    add,
    ...suggestions,
    ...scopeChanges,
  };
}
