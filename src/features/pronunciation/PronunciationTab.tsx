import type { Character } from "../../types";
import { PronunciationDictionaryView } from "./PronunciationDictionaryView";

export function PronunciationTab({ active, characters, onNotice, onRegenerate }: { active: boolean; characters: Character[]; onNotice: (message: string) => void; onRegenerate: (ids: string[], mode: "append" | "replace") => Promise<void> }) {
  return active ? <PronunciationDictionaryView characters={characters} onNotice={onNotice} onRegenerate={onRegenerate} /> : null;
}
