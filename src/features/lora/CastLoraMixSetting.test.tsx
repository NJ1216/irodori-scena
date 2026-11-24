import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { Character, StudioProject } from "../../types";
import { CastLoraMixSetting } from "./CastLoraMixSetting";
const { adapters, status, save, toggle } = vi.hoisted(() => ({ adapters: vi.fn(), status: vi.fn(), save: vi.fn(), toggle: vi.fn() }));
vi.mock("../../api-lora", () => ({ loraApi: { adapters, status } }));
vi.mock("./useLoraAudition", () => ({ useLoraAudition: () => ({ generating: false, playing: false, error: "", toggle }) }));
const assets = Array.from({ length: 5 }, (_, index) => ({ id: `asset-${index}`, name: `声${index}`, adapterHash: "hash", baseModelRepo: "base", baseModelRevision: "rev" }));
const character = { id: "cast", name: "名前", referenceAudioUrl: "/ref" } as Character;
function Editor() {
  const [draft, setDraft] = useState<Character | null>(character);
  return draft ? (
    <>
      <CastLoraMixSetting character={draft} project={{ settings: {} } as StudioProject} onPlay={vi.fn()} onChange={(loraMix) => setDraft({ ...draft, loraMix })} />
      <button onClick={() => save(draft)}>変更を保存</button>
      <button onClick={() => setDraft(null)}>キャンセル</button>
    </>
  ) : (
    <span>編集終了</span>
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  adapters.mockResolvedValue(assets);
  status.mockResolvedValue({ generationSupported: true, baseModelRepo: "base", baseModelRevision: "rev" });
});
it("adds up to four in order and saves the draft only on explicit save", async () => {
  render(<Editor />);
  await waitFor(() => expect(screen.getByRole("button", { name: "LoRAを追加" })).toBeEnabled());
  for (let index = 0; index < 4; index++) {
    fireEvent.click(screen.getByRole("button", { name: "LoRAを追加" }));
    fireEvent.change(screen.getByLabelText("登録済みLoRA"), { target: { value: `asset-${index}` } });
    fireEvent.click(screen.getByRole("button", { name: /^追加$/ }));
  }
  expect(save).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "LoRAを追加" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "変更を保存" }));
  expect(save.mock.calls[0][0].loraMix.entries.map((entry: { assetId: string }) => entry.assetId)).toEqual(["asset-0", "asset-1", "asset-2", "asset-3"]);
  expect(save.mock.calls[0][0].loraMix.baseWeight).toBe(2000);
});
it("cancel discards the unsaved mix; incompatible library members cannot be added", async () => {
  adapters.mockResolvedValue([...assets, { ...assets[0], id: "bad", name: "互換性なし", baseModelRevision: "other" }]);
  render(<Editor />);
  await waitFor(() => expect(screen.getByRole("button", { name: "LoRAを追加" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "LoRAを追加" }));
  expect(screen.queryByRole("button", { name: /登録解除|新しいLoRAを登録|戻す/ })).not.toBeInTheDocument();
  const select = screen.getByLabelText("登録済みLoRA");
  expect(screen.queryByRole("option", { name: "互換性なし" })).not.toBeInTheDocument();
  fireEvent.change(select, { target: { value: "asset-0" } });
  fireEvent.click(screen.getByRole("button", { name: /^追加$/ }));
  fireEvent.click(screen.getByRole("button", { name: "キャンセル" }));
  expect(save).not.toHaveBeenCalled();
  expect(character.loraMix).toBeUndefined();
});
it("disables audition with a reason when the runtime is unsupported", async () => {
  status.mockResolvedValue({ generationSupported: false, generationReason: "MLXを選択してください", baseModelRepo: "base", baseModelRevision: "rev" });
  render(<Editor />);
  await waitFor(() => expect(screen.getByRole("button", { name: "この配合で試聴" })).toHaveAttribute("title", "MLXを選択してください"));
  expect(screen.getByRole("button", { name: "この配合で試聴" })).toBeDisabled();
});

it("keeps mix removal in the graph and auditions the graph mix without a numeric editor", async () => {
  render(<Editor />);
  await waitFor(() => expect(screen.getByRole("button", { name: "LoRAを追加" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "LoRAを追加" }));
  expect(screen.queryByRole("button", { name: /登録解除|新しいLoRAを登録|戻す/ })).not.toBeInTheDocument();
  const select = screen.getByLabelText("登録済みLoRA");
  fireEvent.change(select, { target: { value: "asset-0" } });
  fireEvent.click(screen.getByRole("button", { name: /^追加$/ }));
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "この配合で試聴" }));
  expect(toggle).toHaveBeenCalled();
  expect(screen.queryByText("管理")).not.toBeInTheDocument();
  fireEvent.contextMenu(screen.getByTitle("声0 50%"));
  fireEvent.click(screen.getByRole("menuitem", { name: "削除" }));
  expect(screen.queryByText("LoRA1")).not.toBeInTheDocument();
  expect(screen.getByText("100%")).toBeVisible();
  expect(save).not.toHaveBeenCalled();
});
