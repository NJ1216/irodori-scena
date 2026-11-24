import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { LoraLibraryPanel } from "./LoraLibraryPanel";
const { adapters, archivedAdapters, restoreAdapter } = vi.hoisted(() => ({ adapters: vi.fn(), archivedAdapters: vi.fn(), restoreAdapter: vi.fn() }));
vi.mock("../../api-lora", () => ({ loraApi: { adapters, archivedAdapters, restoreAdapter, status: vi.fn(async () => ({ generationSupported: true })) } }));
const asset = { id: "a", name: "穏やかな声", adapterHash: "hash", baseModelRepo: "base", baseModelRevision: "rev" };
const archived = { ...asset, archived: true };
function panel() {
  return <LoraLibraryPanel onBack={vi.fn()} onContinue={vi.fn()} />;
}
beforeEach(() => {
  vi.clearAllMocks();
  adapters.mockResolvedValue([archived]);
  archivedAdapters.mockResolvedValue([archived]);
  restoreAdapter.mockResolvedValue({ ...asset, archived: false });
});
async function open() {
  fireEvent.click(await screen.findByRole("button", { name: "登録を戻す" }));
  return screen.findByRole("button", { name: "穏やかな声を戻す" });
}
it("loads all archived assets in a separate dialog, restores choices without automatically applying", async () => {
  render(panel());
  fireEvent.click(await open());
  expect(await screen.findByText(/「穏やかな声」を戻しました/)).toBeVisible();
  expect(archivedAdapters).toHaveBeenCalledOnce();
  expect(restoreAdapter).toHaveBeenCalledWith("a");
  fireEvent.click(screen.getByRole("button", { name: "閉じる" }));
  expect(screen.getByRole("option", { name: "穏やかな声" })).toBeInTheDocument();
  expect(screen.getByLabelText("登録済みLoRA")).toHaveValue("");
});
it("keeps failed restore in the list and allows cancellation or retry", async () => {
  restoreAdapter.mockRejectedValueOnce(new Error("復元できません"));
  render(panel());
  const button = await open();
  fireEvent.click(button);
  expect(await screen.findByRole("alert")).toHaveTextContent("復元できません");
  expect(button).toBeEnabled();
  fireEvent.click(button);
  expect(await screen.findByText(/「穏やかな声」を戻しました/)).toBeVisible();
  expect(restoreAdapter).toHaveBeenCalledTimes(2);
});
it("locks restore and close while pending and restores focus on close", async () => {
  let release!: (asset: typeof archived) => void;
  restoreAdapter.mockImplementation(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  render(panel());
  const trigger = await screen.findByRole("button", { name: "登録を戻す" });
  trigger.focus();
  const button = await open();
  fireEvent.click(button);
  fireEvent.click(button);
  await waitFor(() => expect(restoreAdapter).toHaveBeenCalledOnce());
  expect(screen.getByRole("button", { name: "閉じる" })).toBeDisabled();
  expect(screen.getByRole("dialog")).toHaveFocus();
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  await act(async () => {
    release({ ...asset, archived: false });
  });
  fireEvent.click(screen.getByRole("button", { name: "閉じる" }));
  expect(screen.getByLabelText("登録済みLoRA")).toHaveFocus();
});
