import { useState } from "react";
import type { PronunciationDictionaryChangeResult, PronunciationDictionaryEntry } from "../../types";
import type { ChangeDictionary } from "./usePronunciationDictionary";

function removesLastScopeForTerm(entry: PronunciationDictionaryEntry, scope: "global" | "project", entries: PronunciationDictionaryEntry[]) {
  const term = entry.term.toLocaleLowerCase();
  if ((entry.scopes ?? ["global"]).some((candidate) => candidate !== scope)) return false;
  return !entries.some((candidate) => candidate !== entry && candidate.source === entry.source && candidate.term.toLocaleLowerCase() === term && (candidate.scopes ?? ["global"]).length > 0);
}

export function useDictionaryScopeChanges({ entries, changeDictionary, acceptChange, onNotice }: { entries: PronunciationDictionaryEntry[]; changeDictionary: ChangeDictionary; acceptChange: (result: PronunciationDictionaryChangeResult) => void; onNotice: (message: string) => void }) {
  const [scopeConflict, setScopeConflict] = useState<{ entry: PronunciationDictionaryEntry; scope: "global" | "project"; enabled: boolean } | null>(null),
    [scopeRemoval, setScopeRemoval] = useState<{ entry: PronunciationDictionaryEntry; scope: "global" | "project" } | null>(null);
  const toggleScope = async (entry: PronunciationDictionaryEntry, scope: "global" | "project", enabled: boolean) => {
    if (!enabled && removesLastScopeForTerm(entry, scope, entries)) {
      setScopeRemoval({ entry, scope });
      return;
    }
    await applyScopeChange(entry, scope, enabled);
  };
  const applyScopeChange = async (entry: PronunciationDictionaryEntry, scope: "global" | "project", enabled: boolean) => {
    const change = { operation: "toggle-scope" as const, scope, enabled, global_id: entry.globalId ?? "", project_id: entry.projectId ?? "" };
    try {
      acceptChange(await changeDictionary(change));
    } catch (error) {
      if (error instanceof Error && error.message.includes("同じ語句")) {
        setScopeConflict({ entry, scope, enabled });
        return;
      }
      onNotice(`保存先を変更できません: ${(error as Error).message}`);
    }
  };
  return { scopeConflict, setScopeConflict, scopeRemoval, setScopeRemoval, toggleScope, applyScopeChange };
}
