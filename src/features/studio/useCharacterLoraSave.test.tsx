import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { Character } from "../../types";
import { useCharacterPersistenceActions } from "./useCharacterPersistenceActions";
const { updateCharacter } = vi.hoisted(() => ({ updateCharacter: vi.fn() }));
vi.mock("../../api", () => ({ api: { updateCharacter } }));
const reference = { assetId: "asset", adapterHash: "hash", baseModelRepo: "base", baseModelRevision: "revision", enabled: false };
beforeEach(() => {
  updateCharacter.mockReset();
  updateCharacter.mockResolvedValue({ id: "cast", name: "名前" });
});
async function save(lora: Character["lora"]) {
  const hook = renderHook(() => useCharacterPersistenceActions({ editSession: { requestUpdate: (send: () => Promise<Character>) => send() }, setBusy: vi.fn(), setNotice: vi.fn() } as never));
  await act(async () => {
    await hook.result.current.updateCharacter({ id: "cast", lora } as Character, "名前", "設定", "声", {} as never, "画像", {} as never);
  });
}
it("preserves legacy disabled identity on an update that does not explicitly migrate the mix", async () => {
  await save(reference);
  expect(updateCharacter.mock.calls[0][7]).toEqual(reference);
});
it("preserves selected on references and omission semantics", async () => {
  const enabled = { ...reference, enabled: true };
  await save(enabled);
  expect(updateCharacter.mock.calls[0][7]).toEqual(enabled);
  updateCharacter.mockClear();
  await save(undefined);
  expect(updateCharacter.mock.calls[0][7]).toBeUndefined();
});
it("does not introduce a new mixture when the update omits it", async () => {
  await save(reference);
  expect(updateCharacter.mock.calls[0][8]).toBeUndefined();
});
