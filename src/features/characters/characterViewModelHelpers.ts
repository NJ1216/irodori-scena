import type { Character, VoiceCandidate } from "../../types";

export async function importBaselineReference(file: File, onImport: (file: File) => Promise<VoiceCandidate | null>, select: (candidateId: string) => void) {
  const candidate = await onImport(file);
  if (candidate) select(candidate.id);
}

export function resetNewVoiceDesignIdentity(setReferenceVoiceTarget: (value: Character | null) => void, setName: (value: string) => void) {
  setReferenceVoiceTarget(null);
  setName("新規キャスト");
}

export function insertTextAtSelection(input: HTMLTextAreaElement | null, text: string, setValue: (value: string) => void) {
  if (!input) return;
  const start = input.selectionStart;
  const end = input.selectionEnd;
  setValue(`${input.value.slice(0, start)}${text}${input.value.slice(end)}`);
  window.requestAnimationFrame(() => {
    input.focus();
    const caret = start + text.length;
    input.setSelectionRange(caret, caret);
  });
}
