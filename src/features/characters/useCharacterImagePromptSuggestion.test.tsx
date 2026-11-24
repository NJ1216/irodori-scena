import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import type { Character } from "../../types";
import { useCharacterImagePromptSuggestion } from "./useCharacterImagePromptSuggestion";

vi.mock("../../api", () => ({ api: { suggestCharacterImagePrompt: vi.fn() } }));

const editing = { id: "cast-1", name: "彩" } as Character;

function renderSuggestion(onPromptReady = vi.fn().mockResolvedValue(true)) {
  const onBusy = vi.fn();
  const hook = renderHook(() =>
    useCharacterImagePromptSuggestion({
      connection: {} as never,
      busy: null,
      onBusy,
      editing,
      name: editing.name,
      profile: "",
      profileDetails: () => ({}) as never,
      onPromptReady,
    }),
  );
  return { ...hook, onBusy, onPromptReady };
}

beforeEach(() => vi.clearAllMocks());

it("sends a custom accessory and closes after its converted prompt is saved", async () => {
  vi.mocked(api.suggestCharacterImagePrompt).mockResolvedValue({
    imagePrompt: "1girl, solo, tiara",
    usedLlm: true,
    ignoredCustomFields: [],
    warnings: [],
  });
  const hook = renderSuggestion();
  act(() => {
    hook.result.current.setImagePromptSuggestionOpen(true);
    hook.result.current.updateImagePromptField("accessory", ["ティアラ"]);
  });
  await act(() => hook.result.current.suggestCharacterImagePrompt({ preventDefault: vi.fn() } as never));

  expect(api.suggestCharacterImagePrompt).toHaveBeenCalledWith(expect.objectContaining({ accessory: "ティアラ" }));
  expect(hook.onPromptReady).toHaveBeenCalledWith("1girl, solo, tiara", expect.any(Object));
  expect(hook.result.current.editImagePrompt).toBe("1girl, solo, tiara");
  expect(hook.result.current.imagePromptSuggestionError).toBe("");
  expect(hook.result.current.imagePromptSuggestionOpen).toBe(false);
});

it("keeps a partially generated prompt and the dialog open when custom fields were ignored", async () => {
  vi.mocked(api.suggestCharacterImagePrompt).mockResolvedValue({
    imagePrompt: "1girl, solo, school blazer",
    usedLlm: true,
    ignoredCustomFields: ["accessory"],
    warnings: ["自由入力を変換できなかったため無視しました: accessory"],
  });
  const hook = renderSuggestion();
  act(() => hook.result.current.setImagePromptSuggestionOpen(true));
  await act(() => hook.result.current.suggestCharacterImagePrompt({ preventDefault: vi.fn() } as never));

  expect(hook.onPromptReady).toHaveBeenCalledWith("1girl, solo, school blazer", expect.any(Object));
  expect(hook.result.current.editImagePrompt).toBe("1girl, solo, school blazer");
  expect(hook.result.current.imagePromptSuggestionError).toContain("accessory");
  expect(hook.result.current.imagePromptSuggestionOpen).toBe(true);
});
