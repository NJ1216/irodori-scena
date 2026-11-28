// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import type { CharacterActionModel } from "./studioCharacterActionTypes";
import { useVoiceCandidateActions } from "./useVoiceCandidateActions";

afterEach(() => vi.restoreAllMocks());

function model(requestUpdate: () => Promise<unknown>) {
  return { editSession: { requestUpdate }, setBusy: vi.fn(), setNotice: vi.fn(), setStatusNotice: vi.fn(), stop: vi.fn() } as unknown as CharacterActionModel & {
    setNotice: ReturnType<typeof vi.fn>;
    setStatusNotice: ReturnType<typeof vi.fn>;
  };
}

it("reports generated candidates without raising the dialog overlay notice", async () => {
  vi.spyOn(api, "candidates").mockResolvedValue({ candidates: [] } as never);
  const current = model(async () => ({ candidates: [{}, {}, {}] }));
  const { result } = renderHook(() => useVoiceCandidateActions(current));
  await expect(result.current.generateCandidates("calm", 3, "こんにちは")).resolves.toBe(true);
  expect(current.setStatusNotice).toHaveBeenCalledWith("3 件の声候補を追加しました。採用しない候補はページを離れると消去されます。");
  expect(current.setNotice).not.toHaveBeenCalledWith(expect.stringContaining("声候補を追加しました"));
});

it("keeps generation failures as result notices the overlay shows", async () => {
  const current = model(async () => {
    throw new Error("TTS stopped");
  });
  const { result } = renderHook(() => useVoiceCandidateActions(current));
  await expect(result.current.generateCandidates("calm", 3, "こんにちは")).resolves.toBe(false);
  expect(current.setNotice).toHaveBeenLastCalledWith("候補を作れませんでした: TTS stopped");
});
