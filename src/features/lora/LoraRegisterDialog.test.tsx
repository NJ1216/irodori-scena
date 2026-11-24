import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { LoraRegisterDialog } from "./LoraRegisterDialog";
import { LoraLibraryPanel } from "./LoraLibraryPanel";
const { chooseDirectory, status, importAdapter, adapters, adapterUsage, archiveAdapter, restoreAdapter } = vi.hoisted(() => ({ chooseDirectory: vi.fn(), status: vi.fn(), importAdapter: vi.fn(), adapters: vi.fn(), adapterUsage: vi.fn(), archiveAdapter: vi.fn(), restoreAdapter: vi.fn() }));
vi.mock("../../api", () => ({ chooseDirectory }));
vi.mock("../../api-lora", () => ({ loraApi: { status, importAdapter, adapters, adapterUsage, archiveAdapter, restoreAdapter } }));
const asset = { id: "saved", name: "声", adapterHash: "hash", baseModelRepo: "base", baseModelRevision: "revision" };
beforeEach(() => {
  vi.resetAllMocks();
  status.mockResolvedValue({ supported: true, generationSupported: true, baseModelRepo: "base", baseModelRevision: "revision" });
  adapters.mockResolvedValue([]);
  importAdapter.mockResolvedValue(asset);
});
function fill() {
  fireEvent.change(screen.getByLabelText("LoRAフォルダ"), { target: { value: "/local/adapter" } });
  fireEvent.change(screen.getByLabelText("LoRA名"), { target: { value: "声" } });
}
it("uses shared dialog chrome and cancelling leaves the parent cast untouched", () => {
  const onClose = vi.fn(),
    onRegistered = vi.fn(),
    saveCast = vi.fn();
  render(
    <form onSubmit={saveCast}>
      <LoraRegisterDialog onRegistered={onRegistered} onClose={onClose} />
    </form>,
  );
  const dialog = screen.getByRole("dialog", { name: "LoRAを登録" });
  expect(dialog.querySelector(".dialog-header")).not.toBeNull();
  expect(dialog.querySelector(".dialog-footer")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "キャンセル" }));
  expect(onClose).toHaveBeenCalledOnce();
  expect(onRegistered).not.toHaveBeenCalled();
  expect(saveCast).not.toHaveBeenCalled();
});
it("blocks duplicate registration and closing while pending without submitting the cast editor", async () => {
  let release!: (value: typeof asset) => void;
  importAdapter.mockImplementation(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  const onRegistered = vi.fn(),
    onClose = vi.fn(),
    saveCast = vi.fn();
  render(
    <form onSubmit={saveCast}>
      <LoraRegisterDialog onRegistered={onRegistered} onClose={onClose} />
    </form>,
  );
  fill();
  fireEvent.submit(screen.getByRole("dialog"));
  fireEvent.submit(screen.getByRole("dialog"));
  await waitFor(() => expect(importAdapter).toHaveBeenCalledOnce());
  expect(screen.getByRole("button", { name: "キャンセル" })).toBeDisabled();
  fireEvent.keyDown(window, { key: "Escape" });
  expect(onClose).not.toHaveBeenCalled();
  expect(saveCast).not.toHaveBeenCalled();
  await act(async () => {
    release(asset);
  });
  expect(onRegistered).toHaveBeenCalledWith(asset);
  expect(screen.getByRole("button", { name: "閉じる" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "閉じる" }));
  expect(onClose).toHaveBeenCalledOnce();
  expect(saveCast).not.toHaveBeenCalled();
});
it("keeps drafts after validation failure and permits cancellation or retry", async () => {
  importAdapter.mockRejectedValueOnce(new Error("adapterが不適合です"));
  const onRegistered = vi.fn(),
    onClose = vi.fn();
  render(<LoraRegisterDialog onRegistered={onRegistered} onClose={onClose} />);
  fill();
  fireEvent.click(screen.getByRole("button", { name: "登録する" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("不適合");
  expect(screen.getByLabelText("LoRA名")).toHaveValue("声");
  expect(screen.getByRole("button", { name: "キャンセル" })).toBeEnabled();
  expect(onRegistered).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "登録する" }));
  expect(await screen.findByRole("heading", { name: "LoRAを登録しました" })).toBeVisible();
  expect(onRegistered).toHaveBeenCalledOnce();
});
it("adds a registered adapter to the choices without selecting it", async () => {
  render(<LoraLibraryPanel onBack={vi.fn()} onContinue={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "LoRAを登録" }));
  fill();
  fireEvent.click(screen.getByRole("button", { name: "登録する" }));
  expect(await screen.findByRole("heading", { name: "LoRAを登録しました" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "閉じる" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByLabelText("登録済みLoRA")).toHaveValue("");
  expect(screen.getByRole("option", { name: "声" })).toBeInTheDocument();
});

it("focuses the first field, traps Tab both ways, blocks background while busy and restores the trigger", async () => {
  let release!: (value: typeof asset) => void;
  importAdapter.mockImplementation(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  const saveCast = vi.fn();
  render(
    <form onSubmit={saveCast}>
      <LoraLibraryPanel onBack={vi.fn()} onContinue={vi.fn()} />
      <button type="submit">親キャストを保存</button>
    </form>,
  );
  const trigger = await screen.findByRole("button", { name: "LoRAを登録" });
  trigger.focus();
  fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog");
  expect(screen.getByLabelText("LoRAフォルダ")).toHaveFocus();
  const parentSave = screen.getByRole("button", { name: "親キャストを保存" });
  expect(parentSave.closest("[inert]")).not.toBeNull();
  fireEvent.keyDown(document.activeElement!, { key: "Tab", shiftKey: true });
  expect(screen.getByRole("button", { name: "キャンセル" })).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: "Tab" });
  expect(screen.getByLabelText("LoRAフォルダ")).toHaveFocus();
  parentSave.focus();
  expect(screen.getByLabelText("LoRAフォルダ")).toHaveFocus();
  fill();
  fireEvent.submit(dialog);
  await waitFor(() => expect(importAdapter).toHaveBeenCalledOnce());
  expect(dialog).toHaveFocus();
  fireEvent.keyDown(dialog, { key: "Tab" });
  expect(dialog).toHaveFocus();
  parentSave.focus();
  expect(dialog).toHaveFocus();
  expect(saveCast).not.toHaveBeenCalled();
  await act(async () => {
    release(asset);
  });
  expect(screen.getByRole("button", { name: "閉じる" })).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "閉じる" }));
  expect(trigger).toHaveFocus();
  expect(parentSave.closest("[inert]")).toBeNull();
});

it("keeps new registration separate from deletion and archived inventory", () => {
  render(<LoraRegisterDialog onRegistered={vi.fn()} onClose={vi.fn()} />);
  expect(screen.queryByLabelText("登録済みLoRAの管理")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /削除|戻す/ })).not.toBeInTheDocument();
  expect(adapters).not.toHaveBeenCalled();
});
