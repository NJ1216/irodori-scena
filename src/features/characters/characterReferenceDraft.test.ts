import { expect, it } from "vitest";
import type { Character } from "../../types";
import { preserveReferenceEditDraft } from "./characterReferenceDraft";
const lora = { assetId: "saved", adapterHash: "hash", baseModelRepo: "base", baseModelRevision: "rev", enabled: true };
it("keeps the unsaved LoRA selection while committing an unrelated reference upload", () => {
  const current = { id: "cast", referenceFile: "old.wav", lora } as Character;
  const updated = { ...current, referenceFile: "new.wav", lora: null };
  expect(preserveReferenceEditDraft(current, updated)).toEqual({ ...updated, lora });
  expect(preserveReferenceEditDraft({ ...current, lora: null }, { ...updated, lora })).toEqual(updated);
});
it("does not reopen a closed editor or overwrite another cast after an upload finishes", () => {
  const updated = { id: "old" } as Character;
  const current = { id: "new" } as Character;
  expect(preserveReferenceEditDraft(null, updated)).toBeNull();
  expect(preserveReferenceEditDraft(current, updated)).toBe(current);
});
