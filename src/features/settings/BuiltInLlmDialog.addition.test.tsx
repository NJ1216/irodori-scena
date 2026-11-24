// @vitest-environment jsdom
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import { BuiltInLlmDialog } from "./BuiltInLlmDialog";

vi.mock("../shared/platform", () => ({ isWindows: () => true }));
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it.each(["complete", "failed"])("keeps the dialog waiting for automatic verification: %s", async (outcome) => {
  vi.useFakeTimers();
  vi.spyOn(api, "huggingFaceTokenStatus").mockResolvedValue({ hasToken: false });
  vi.spyOn(api, "huggingFaceMetadata").mockResolvedValue({ models: [] });
  vi.spyOn(api, "searchHuggingFace").mockResolvedValue({ models: [{ repoId: "org/model", publisher: "org", revision: "fixed", displayName: "Test model", downloads: 1, gated: false, compatibility: "gguf", warning: null, downloadSizeBytes: 24, inferredTags: [] }] });
  vi.spyOn(api, "huggingFaceGgufVariants").mockResolvedValue({ repoId: "org/model", revision: "fixed", variants: [{ id: "Q4", quantization: "Q4", files: ["model.gguf"], shardCount: 1, downloadSizeBytes: 24 }] });
  vi.spyOn(api, "downloadHuggingFace").mockResolvedValue({ id: "download", state: "queued" });
  const transfer = { id: "download", state: "complete", downloadedBytes: 24, totalBytes: 24 };
  const poll = vi.spyOn(api, "huggingFaceDownload").mockResolvedValue({ ...transfer, preparation: { state: "preparing", message: "使用するための準備中", downloadedBytes: 10, totalBytes: 20 } });
  const added = vi.fn().mockResolvedValue(undefined);
  render(<BuiltInLlmDialog onAdded={added} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: /Hugging Faceから探す/ }));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "検索" }));
  });
  await act(async () => {
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "モデル" })).getByRole("radio"));
  });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "取得して追加" }));
  });
  expect(added).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "キャンセル" })).toBeDisabled();
  expect(within(screen.getByRole("region", { name: "モデル取得状況" })).getByRole("status")).toHaveTextContent("使用するための準備中");
  poll.mockResolvedValue({ ...transfer, preparation: { state: "verifying", message: "基本動作を確認中", downloadedBytes: 20, totalBytes: 20 } });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(700);
  });
  expect(added).not.toHaveBeenCalled();
  poll.mockResolvedValue({ ...transfer, preparation: { state: outcome, message: outcome === "complete" ? "使用できます" : "確認に失敗しました", downloadedBytes: 20, totalBytes: 20 } });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(700);
  });
  if (outcome === "complete") expect(added).toHaveBeenCalledExactlyOnceWith("Test model");
  else {
    expect(added).not.toHaveBeenCalled();
    expect(screen.getByText("確認に失敗しました")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toHaveClass("download-dialog-footer");
    expect(screen.queryByRole("button", { name: "再確認" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "閉じる" })).toBeEnabled();
  }
});
