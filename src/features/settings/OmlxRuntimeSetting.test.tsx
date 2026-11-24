// @vitest-environment jsdom
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import type { OmlxRuntimeStatus } from "../../types";
import { OmlxRuntimeSetting } from "./OmlxRuntimeSetting";

const status: OmlxRuntimeStatus = {
  activeRuntimeId: null,
  recommendedRuntimeId: "scena-test",
  updateAvailable: false,
  catalog: [],
  installedRuntimes: [],
  job: { id: null, runtimeId: null, state: "idle", message: "" },
};
afterEach(() => vi.restoreAllMocks());

it("opens management without installing or fetching releases and supports empty state", async () => {
  const listing = vi.spyOn(api, "omlxRuntimes").mockResolvedValue(status);
  const install = vi.spyOn(api, "installOmlxRuntimeVersion");
  const releases = vi.spyOn(api, "omlxReleases");
  render(<OmlxRuntimeSetting />);
  expect(listing).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "oMLX管理" }));
  expect(await screen.findByText("導入済みの実行基盤はありません。")).toBeInTheDocument();
  const dialog = within(screen.getByRole("dialog", { name: "oMLX管理" }));
  expect(dialog.queryByRole("combobox")).toBeNull();
  expect(install).not.toHaveBeenCalled();
  expect(releases).not.toHaveBeenCalled();
  fireEvent.click(dialog.getByRole("button", { name: "閉じる" }));
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("protects a referenced runtime and confirms deletion of an unused runtime", async () => {
  const base = { displayName: "oMLX", omlxVersion: "0.6.4", source: "scena", state: "ready", diskBytes: 1024, installedAt: 1, error: null, commit: "a", gitRef: "a", path: "/mock", verification: "verified" } as const;
  vi.spyOn(api, "omlxRuntimes").mockResolvedValue({
    ...status,
    installedRuntimes: [
      { ...base, id: "used", usedByModels: [{ id: "model", displayName: "長いモデル名".repeat(20) }], deletionBlockedReason: "登録モデルが使用しています。" },
      { ...base, id: "unused", usedByModels: [], deletionBlockedReason: null },
    ],
  });
  const remove = vi.spyOn(api, "deleteOmlxRuntime").mockResolvedValue(status);
  render(<OmlxRuntimeSetting />);
  fireEvent.click(screen.getByRole("button", { name: "oMLX管理" }));
  await screen.findByText("未使用");
  const buttons = screen.getAllByRole("button", { name: "実行基盤を削除" });
  expect(buttons[0]).toBeDisabled();
  fireEvent.click(buttons[1]);
  expect(remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "もう一度押して削除" }));
  expect(remove).toHaveBeenCalledWith("unused");
});

it("reports a management read failure", async () => {
  vi.spyOn(api, "omlxRuntimes").mockRejectedValue(new Error("読み込み失敗"));
  render(<OmlxRuntimeSetting />);
  fireEvent.click(screen.getByRole("button", { name: "oMLX管理" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("読み込み失敗");
});
