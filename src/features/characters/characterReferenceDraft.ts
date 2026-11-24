import type { Character } from "../../types";
/** A reference upload commits independently of the edit form's LoRA draft. */
export function preserveReferenceEditDraft(current: Character | null, updated: Character): Character | null {
  if (!current || current.id !== updated.id) return current;
  return { ...updated, lora: current.lora, loraMix: current.loraMix };
}
