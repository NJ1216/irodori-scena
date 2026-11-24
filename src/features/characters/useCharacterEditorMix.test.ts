import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { Character } from "../../types";
import { useCharacterEditor } from "./useCharacterEditor";
const identity = { assetId: "one", adapterHash: "hash", baseModelRepo: "base", baseModelRevision: "rev" };
it.each([true, false])("migrates legacy LoRA only at explicit save, enabled=%s", async (enabled) => {
  const saved = { id: "cast", name: "cast", profile: "", voiceKeywords: "", lora: { ...identity, enabled } } as Character;
  const update = vi.fn<(character: Character, ...args: unknown[]) => Promise<boolean>>(async () => true);
  const { result } = renderHook(() => useCharacterEditor(vi.fn()));
  act(() => result.current.beginEdit(saved, vi.fn()));
  expect(result.current.editing?.loraMix?.baseWeight).toBe(enabled ? 1000 : 9000);
  expect(saved.loraMix).toBeUndefined();
  await act(async () => {
    await result.current.saveEdit({ preventDefault: vi.fn() } as never, { imagePrompt: "", preferences: {} as never, onUpdate: update, onRemoveAvatar: vi.fn(), onUpdateAvatar: vi.fn() });
  });
  expect(update.mock.calls[0][0]).toMatchObject({ loraMix: { version: 1, baseWeight: enabled ? 1000 : 9000, entries: [{ ...identity, weight: enabled ? 9000 : 1000 }] } });
  expect(update.mock.calls[0][0].lora).toEqual(enabled ? saved.lora : null);
  expect(saved.loraMix).toBeUndefined();
});
