import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { Character } from "../../types";
import { useCharacterEditor } from "./useCharacterEditor";
import { useCharacterImportForm } from "./useCharacterImportForm";

const submitEvent = { preventDefault: vi.fn() } as unknown as React.FormEvent<HTMLFormElement>;

it("keeps WAV import drafts until valid and clears them only after import", async () => {
  const onImport = vi.fn().mockResolvedValue(undefined);
  const onNotice = vi.fn();
  const { result } = renderHook(() => useCharacterImportForm(onImport, onNotice));
  await act(() => result.current.importWav(submitEvent));
  expect(onNotice).toHaveBeenCalledWith("登録するWAVファイルを選んでください。");
  const file = new File(["wav"], "voice.wav", { type: "audio/wav" });
  act(() => {
    result.current.setReferenceFile(file);
    result.current.setImportName("春");
    result.current.setImportProfile("主人公");
  });
  await act(() => result.current.importWav(submitEvent));
  expect(onImport).toHaveBeenCalledWith(file, "春", "主人公");
  expect(result.current.referenceFile).toBeNull();
  expect(result.current.importName).toBe("");
});

it("saves profile before applying an avatar change and closes only after both succeed", async () => {
  const order: string[] = [];
  const character = { id: "cast-1", name: "春", profile: "旧", voiceKeywords: "clear" } as Character;
  const { result } = renderHook(() => useCharacterEditor(vi.fn()));
  act(() => {
    result.current.beginEdit(character, vi.fn());
    result.current.setEditName("春子");
    result.current.setEditAvatarChange({ original: "full", thumbnail: "thumb" });
  });
  await act(() =>
    result.current.saveEdit(submitEvent, {
      imagePrompt: "portrait",
      preferences: {} as never,
      onUpdate: vi.fn(async () => {
        order.push("profile");
        return true;
      }),
      onRemoveAvatar: vi.fn(async () => true),
      onUpdateAvatar: vi.fn(async () => {
        order.push("avatar");
        return true;
      }),
    }),
  );
  expect(order).toEqual(["profile", "avatar"]);
  expect(result.current.editing).toBeNull();
});
