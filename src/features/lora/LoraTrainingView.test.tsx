import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cancelDestructiveConfirmation } from "../shared/destructiveConfirmation";
import { DestructiveConfirmationNotice } from "../shared/DestructiveConfirmationNotice";
import { LoraManagementView } from "./LoraTrainingView";
const { api } = vi.hoisted(() => ({ api: { status: vi.fn(), jobs: vi.fn(), inputs: vi.fn(), folderInputs: vi.fn(), start: vi.fn(), cancel: vi.fn(), adapters: vi.fn(), updateAdapter: vi.fn(), adapterUsage: vi.fn(), deleteAdapter: vi.fn() } }));
vi.mock("../../api-lora", () => ({ loraApi: api }));
vi.mock("../../api-core", () => ({ chooseDirectory: vi.fn(async () => "/fixtures/materials") }));
const rows = ["one", "two"].map((id) => ({ id, wavName: `${id}.wav`, textName: `${id}.txt`, text: `台詞${id}`, caption: "", speakerId: "speaker-1", durationSeconds: 7, issues: [] }));
beforeEach(() => {
  vi.resetAllMocks();
  api.status.mockResolvedValue({ supported: true });
  api.jobs.mockResolvedValue([]);
  api.adapters.mockResolvedValue([{ id: "existing", name: "学習済み", memo: "元のメモ", adapterHash: "hash", baseModelRepo: "base", baseModelRevision: "rev" }]);
  api.folderInputs.mockResolvedValue({ datasetId: "fixed", rows });
  api.start.mockResolvedValue({ id: "job", name: "声", status: "completed", adapterId: "saved" });
});
async function review() {
  render(<LoraManagementView />);
  await userEvent.click(screen.getByRole("button", { name: /LoRAを学習する/ }));
  await userEvent.click(screen.getByRole("button", { name: "フォルダを選択" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "内容を確認する" })).toBeEnabled());
  await userEvent.click(await screen.findByRole("button", { name: "内容を確認する" }));
}
it("shows one next action per step, keeps transcript/name drafts on Back, and defaults to normal training", async () => {
  await review();
  expect(screen.queryByLabelText("話者ID")).not.toBeInTheDocument();
  expect(document.querySelectorAll("button.primary")).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: "one.wavの台詞を編集" }));
  fireEvent.change(screen.getByLabelText("台詞"), { target: { value: "修正した台詞" } });
  await userEvent.click(screen.getByRole("button", { name: "名前と学習へ" }));
  fireEvent.change(screen.getByLabelText("LoRA名"), { target: { value: "声" } });
  expect(screen.getByLabelText("学習モード")).toHaveValue("normal");
  await userEvent.click(screen.getByRole("button", { name: "戻る" }));
  await userEvent.click(screen.getByRole("button", { name: "one.wavの台詞を編集" }));
  expect(screen.getByLabelText("台詞")).toHaveValue("修正した台詞");
  await userEvent.click(screen.getByRole("button", { name: "名前と学習へ" }));
  expect(screen.getByLabelText("LoRA名")).toHaveValue("声");
  await userEvent.click(screen.getByRole("button", { name: "学習を開始" }));
  expect(await screen.findByText("保存しました。キャスト編集で選択できます。")).toBeVisible();
  expect(api.start.mock.calls[0][0]).toMatchObject({
    mode: "normal",
    settings: { maxSteps: 1000, maxSeconds: null },
    rows: [
      { id: "one", text: "修正した台詞", caption: "", speakerId: "speaker-1" },
      { id: "two", caption: "" },
    ],
  });
  expect(screen.queryByLabelText("登録済みLoRA")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("キャスト")).not.toBeInTheDocument();
});
it("requires explicit correction or exclusion before advancing from mismatched material", async () => {
  api.folderInputs.mockResolvedValue({ datasetId: "fixed", rows: [...rows, { ...rows[0], id: "orphan", wavName: null, textName: "orphan.txt" }] });
  await review();
  await userEvent.click(screen.getByRole("button", { name: "名前と学習へ" }));
  expect(screen.getByRole("alert")).toHaveTextContent("WAV");
  expect(screen.queryByLabelText("LoRA名")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("checkbox", { name: "orphan.txtを除外" }));
  await userEvent.click(screen.getByRole("button", { name: "名前と学習へ" }));
  expect(screen.getByLabelText("LoRA名")).toBeVisible();
});
it("stays on name and training when Start validation fails instead of showing a saved result", async () => {
  await review();
  await userEvent.click(screen.getByRole("button", { name: "名前と学習へ" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "学習を開始" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "学習を開始" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("LoRA名");
  expect(api.start).not.toHaveBeenCalled();
  expect(screen.getByLabelText("LoRA名")).toBeVisible();
  expect(screen.queryByText("保存しました。キャスト編集で選択できます。")).not.toBeInTheDocument();
});

afterEach(() => {
  cancelDestructiveConfirmation();
  vi.restoreAllMocks();
});
it("keeps the accepted job selected after completion even when polling returns an older job first", async () => {
  let poll!: () => void;
  const originalInterval = window.setInterval.bind(window);
  vi.spyOn(window, "setInterval").mockImplementation((callback, delay, ...args) => {
    if (delay !== 1500) return originalInterval(callback, delay, ...args);
    poll = callback as () => void;
    return 1;
  });
  api.start.mockResolvedValue({ id: "accepted", name: "今回の学習", status: "running" });
  await review();
  await userEvent.click(screen.getByRole("button", { name: "名前と学習へ" }));
  fireEvent.change(screen.getByLabelText("LoRA名"), { target: { value: "今回の学習" } });
  await userEvent.click(screen.getByRole("button", { name: "学習を開始" }));
  expect(await screen.findByRole("heading", { name: "今回の学習" })).toBeVisible();
  api.jobs.mockResolvedValue([
    { id: "old", name: "古い学習", status: "completed" },
    { id: "accepted", name: "今回の学習", status: "completed" },
  ]);
  const { act } = await import("@testing-library/react");
  await act(async () => {
    poll();
  });
  expect(screen.getByRole("heading", { name: "今回の学習" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "古い学習" })).not.toBeInTheDocument();
  expect(screen.getByText("保存しました。キャスト編集で選択できます。")).toBeVisible();
});

it("omits removed history UI even when many completed jobs exist", async () => {
  api.jobs.mockResolvedValue(Array.from({ length: 100 }, (_, index) => ({ id: `history-${index}`, name: `履歴${index}`, status: "completed" })));
  await review();
  expect(screen.queryByText("これまでの学習")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "戻る" }));
  expect(screen.queryByText("これまでの学習")).not.toBeInTheDocument();
  expect(screen.queryByText("履歴99 — 保存しました")).not.toBeInTheDocument();
});

it("keeps a compact progress route when a running job is discovered during review", async () => {
  let poll!: () => void;
  const interval = window.setInterval.bind(window);
  vi.spyOn(window, "setInterval").mockImplementation((callback, delay, ...args) => {
    if (delay !== 1500) return interval(callback, delay, ...args);
    poll = callback as () => void;
    return 1;
  });
  await review();
  api.jobs.mockResolvedValue([{ id: "running", name: "別の学習", status: "running" }]);
  const { act } = await import("@testing-library/react");
  await act(async () => {
    poll();
  });
  expect(screen.queryByRole("heading", { name: "別の学習" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "学習の進み具合を見る" }));
  expect(screen.getByRole("heading", { name: "別の学習" })).toBeVisible();
  expect(screen.getByRole("button", { name: "学習を中断" })).toBeVisible();
});

it("opens management first, edits metadata only on save, and continues from the selected adapter", async () => {
  render(<LoraManagementView />);
  expect(screen.queryByRole("button", { name: "フォルダを選択" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /登録済みLoRAを管理/ }));
  fireEvent.change(await screen.findByLabelText("登録済みLoRA"), { target: { value: "existing" } });
  await userEvent.click(screen.getByRole("button", { name: "名前とメモを編集" }));
  fireEvent.change(screen.getByLabelText("LoRA名"), { target: { value: "" } });
  await userEvent.click(screen.getByRole("button", { name: "変更を保存" }));
  expect(screen.getByLabelText("LoRA名")).toHaveValue("");
  expect(api.updateAdapter).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("LoRA名"), { target: { value: "変更した名前" } });
  fireEvent.change(screen.getByLabelText("管理メモ"), { target: { value: "新しいメモ" } });
  api.updateAdapter.mockResolvedValue({ id: "existing", name: "変更した名前", memo: "新しいメモ" });
  await userEvent.click(screen.getByRole("button", { name: "変更を保存" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(api.updateAdapter).toHaveBeenCalledWith("existing", { name: "変更した名前", memo: "新しいメモ" });
  await userEvent.click(screen.getByRole("button", { name: "追加学習" }));
  await userEvent.click(screen.getByRole("button", { name: "フォルダを選択" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "内容を確認する" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "内容を確認する" }));
  await userEvent.click(screen.getByRole("button", { name: "名前と学習へ" }));
  expect(screen.getByLabelText("LoRA名")).toHaveValue("変更した名前 追加学習");
  await userEvent.click(screen.getByRole("button", { name: "学習を開始" }));
  await waitFor(() => expect(api.start).toHaveBeenCalled());
  expect(api.start.mock.calls[0][0]).toMatchObject({ sourceAdapterId: "existing", memo: "新しいメモ" });
});

it("preserves training drafts across the operation chooser and clears continuation for new training", async () => {
  render(<LoraManagementView />);
  await userEvent.click(screen.getByRole("button", { name: /登録済みLoRAを管理/ }));
  fireEvent.change(await screen.findByLabelText("登録済みLoRA"), { target: { value: "existing" } });
  await userEvent.click(screen.getByRole("button", { name: "追加学習" }));
  await userEvent.click(screen.getByRole("button", { name: "フォルダを選択" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "内容を確認する" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "戻る" }));
  await userEvent.click(screen.getByRole("button", { name: /LoRAを学習する/ }));
  await userEvent.click(screen.getByRole("button", { name: "内容を確認する" }));
  await userEvent.click(screen.getByRole("button", { name: "名前と学習へ" }));
  await userEvent.click(screen.getByRole("button", { name: "学習を開始" }));
  await waitFor(() => expect(api.start).toHaveBeenCalled());
  expect(api.start.mock.calls[0][0].sourceAdapterId).toBeUndefined();
});

it("uses the same single back control before content for training and library management", async () => {
  render(<LoraManagementView />);
  await userEvent.click(screen.getByRole("button", { name: /LoRAを学習する/ }));
  const trainingBack = screen.getByRole("button", { name: "戻る" });
  expect(screen.getAllByRole("button", { name: "戻る" })).toHaveLength(1);
  expect(trainingBack.closest(".lora-step-actions")?.nextElementSibling).toHaveClass("lora-composer");
  await userEvent.click(trainingBack);
  await userEvent.click(screen.getByRole("button", { name: /登録済みLoRAを管理/ }));
  const libraryBack = screen.getByRole("button", { name: "戻る" });
  expect(screen.getAllByRole("button", { name: "戻る" })).toHaveLength(1);
  expect(libraryBack.className).toBe(trainingBack.className);
  expect(libraryBack.closest(".lora-step-actions")?.nextElementSibling).toHaveClass("lora-composer");
  await userEvent.click(libraryBack);
  expect(screen.getByRole("button", { name: /LoRAを学習する/ })).toBeVisible();
  expect(screen.queryByRole("button", { name: "戻る" })).not.toBeInTheDocument();
});

it("groups all four actions and permanently deletes only after confirmation and an idle usage check", async () => {
  render(
    <>
      <LoraManagementView />
      <DestructiveConfirmationNotice />
    </>,
  );
  await userEvent.click(screen.getByRole("button", { name: /登録済みLoRAを管理/ }));
  const group = screen.getByRole("group", { name: "LoRAの操作" });
  expect(Array.from(group.querySelectorAll("button")).map((button) => button.textContent?.trim())).toEqual(["名前とメモを編集", "追加学習", "LoRAを登録", "削除"]);
  const remove = screen.getByRole("button", { name: "削除" });
  expect(remove).toBeDisabled();
  fireEvent.change(await screen.findByLabelText("登録済みLoRA"), { target: { value: "existing" } });
  api.adapterUsage.mockResolvedValue({ casts: [], takeCount: 0 });
  api.deleteAdapter.mockResolvedValue({ id: "existing", deleted: true });
  await userEvent.click(remove);
  expect(api.deleteAdapter).not.toHaveBeenCalled();
  expect(screen.getByRole("status")).toHaveTextContent("この操作は取り消せません");
  await userEvent.click(remove);
  expect(await screen.findByText("登録済みのLoRAはありません。")).toBeVisible();
  expect(api.deleteAdapter).toHaveBeenCalledExactlyOnceWith("existing");
  expect(screen.queryByRole("button", { name: "登録を戻す" })).not.toBeInTheDocument();
});

it("retains a used adapter and rejects deletion before the destructive API", async () => {
  render(<LoraManagementView />);
  await userEvent.click(screen.getByRole("button", { name: /登録済みLoRAを管理/ }));
  fireEvent.change(await screen.findByLabelText("登録済みLoRA"), { target: { value: "existing" } });
  api.adapterUsage.mockResolvedValue({ casts: [{ id: "cast" }], takeCount: 0 });
  const remove = screen.getByRole("button", { name: "削除" });
  await userEvent.click(remove);
  await userEvent.click(remove);
  expect(await screen.findByRole("alert")).toHaveTextContent("使用中");
  expect(api.deleteAdapter).not.toHaveBeenCalled();
  expect(screen.getByLabelText("登録済みLoRA")).toHaveValue("existing");
});
