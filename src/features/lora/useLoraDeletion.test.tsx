import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { LoraLibraryPanel } from "./LoraLibraryPanel";
import { DestructiveConfirmationNotice } from "../shared/DestructiveConfirmationNotice";
import { cancelDestructiveConfirmation } from "../shared/destructiveConfirmation";
const { adapters, adapterUsage, deleteAdapter } = vi.hoisted(() => ({ adapters: vi.fn(), adapterUsage: vi.fn(), deleteAdapter: vi.fn() }));
vi.mock("../../api", () => ({ chooseDirectory: vi.fn() }));
vi.mock("../../api-lora", () => ({ loraApi: { adapters, adapterUsage, deleteAdapter, archivedAdapters: vi.fn(async () => []), status: vi.fn(async () => ({ generationSupported: true })) } }));
const asset = { id: "a", name: "穏やかな声", adapterHash: "hash", baseModelRepo: "base", baseModelRevision: "rev" };
const other = { ...asset, id: "b", name: "別の声" };
beforeEach(() => {
  vi.clearAllMocks();
  adapters.mockResolvedValue([asset]);
  adapterUsage.mockResolvedValue({ casts: [], takeCount: 0 });
  deleteAdapter.mockResolvedValue({ id: "a", deleted: true });
});
afterEach(() => {
  cancelDestructiveConfirmation();
  vi.useRealTimers();
});
function Panel() {
  return (
    <>
      <LoraLibraryPanel onBack={() => {}} onContinue={() => {}} />
      <DestructiveConfirmationNotice />
    </>
  );
}
async function select(id = "a") {
  const list = await screen.findByLabelText("登録済みLoRA");
  fireEvent.change(list, { target: { value: id } });
  return screen.getByRole("button", { name: "削除" });
}
async function twice() {
  const action = await select();
  fireEvent.click(action);
  fireEvent.click(action);
  return action;
}
function pendingDelete() {
  let release!: (result: unknown) => void;
  deleteAdapter.mockImplementation(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  return () => release({ id: "a", deleted: true });
}
it("arms the shared central confirmation without calling the API and keeps the label stable", async () => {
  render(<Panel />);
  const action = await select();
  fireEvent.click(action);
  expect(action).toHaveClass("is-confirming");
  expect(action).toHaveTextContent("削除");
  expect(screen.getByRole("status")).toHaveClass("centered-notice", "is-danger");
  expect(screen.getByRole("status")).toHaveTextContent("「穏やかな声」を削除しますか？");
  expect(screen.getByRole("status")).toHaveTextContent("他の保存プロジェクトは未確認");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(adapterUsage).not.toHaveBeenCalled();
  expect(deleteAdapter).not.toHaveBeenCalled();
});
it("cancels on Escape and requires a fresh pair of clicks", async () => {
  render(<Panel />);
  const action = await select();
  fireEvent.click(action);
  fireEvent.keyDown(window, { key: "Escape" });
  expect(action).not.toHaveClass("is-confirming");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  fireEvent.click(action);
  expect(deleteAdapter).not.toHaveBeenCalled();
  fireEvent.click(action);
  await waitFor(() => expect(deleteAdapter).toHaveBeenCalledWith("a"));
  expect(await screen.findByText("登録済みのLoRAはありません。")).toBeVisible();
});
it("expires after four seconds without executing and rearms on the next click", async () => {
  render(<Panel />);
  const action = await select();
  vi.useFakeTimers();
  fireEvent.click(action);
  act(() => {
    vi.advanceTimersByTime(4001);
  });
  expect(action).not.toHaveClass("is-confirming");
  fireEvent.click(action);
  expect(action).toHaveClass("is-confirming");
  expect(adapterUsage).not.toHaveBeenCalled();
});
it.each(["", "b"])("cancels when selection changes to %s", async (id) => {
  adapters.mockResolvedValue([asset, other]);
  render(<Panel />);
  fireEvent.click(await select());
  fireEvent.change(screen.getByLabelText("登録済みLoRA"), { target: { value: id } });
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(adapterUsage).not.toHaveBeenCalled();
  expect(deleteAdapter).not.toHaveBeenCalled();
});
it.each(["LoRAを登録", "登録を戻す"])("cancels before opening %s", async (label) => {
  adapters.mockResolvedValue([asset, { ...asset, id: "old", archived: true }]);
  render(<Panel />);
  fireEvent.click(await select());
  fireEvent.click(screen.getByRole("button", { name: label }));
  expect(document.querySelector(".centered-notice")).toBeNull();
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(deleteAdapter).not.toHaveBeenCalled();
});
it("cancels on unmount without performing any deletion", async () => {
  const view = render(<Panel />);
  fireEvent.click(await select());
  view.unmount();
  render(<Panel />);
  fireEvent.click(await select());
  expect(adapterUsage).not.toHaveBeenCalled();
  expect(deleteAdapter).not.toHaveBeenCalled();
});
it.each([
  { casts: [{ id: "cast" }], takeCount: 0 },
  { casts: [], takeCount: 1 },
])("blocks deletion while a cast or take still uses the adapter", async (usage) => {
  adapterUsage.mockResolvedValue(usage);
  render(<Panel />);
  await twice();
  expect(await screen.findByRole("alert")).toHaveTextContent("ほかのキャストまたはテイク");
  expect(deleteAdapter).not.toHaveBeenCalled();
});
it("retains the selected target after a failed deletion and requires two clicks to retry", async () => {
  deleteAdapter.mockRejectedValueOnce(new Error("削除に失敗しました"));
  render(<Panel />);
  const action = await twice();
  expect(await screen.findByRole("alert")).toHaveTextContent("削除に失敗");
  expect(screen.getByLabelText("登録済みLoRA")).toHaveValue("a");
  fireEvent.click(action);
  expect(deleteAdapter).toHaveBeenCalledOnce();
  fireEvent.click(action);
  await waitFor(() => expect(deleteAdapter).toHaveBeenCalledTimes(2));
  expect(await screen.findByText("登録済みのLoRAはありません。")).toBeVisible();
});
it("locks all LoRA controls and suppresses duplicate requests while pending", async () => {
  const release = pendingDelete();
  render(<Panel />);
  const action = await select();
  fireEvent.click(action);
  fireEvent.click(action);
  fireEvent.click(action);
  await waitFor(() => expect(deleteAdapter).toHaveBeenCalledOnce());
  expect(action).toBeDisabled();
  expect(screen.getByLabelText("登録済みLoRA")).toBeDisabled();
  expect(screen.getByRole("button", { name: "LoRAを登録" })).toBeDisabled();
  await act(async () => release());
});
