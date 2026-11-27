// @vitest-environment jsdom
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import { ApiConnectionError, ApiError } from "../../api-error";
import { BuiltInLlmDialog } from "./BuiltInLlmDialog";

vi.mock("../shared/platform", () => ({ isWindows: () => true }));
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

async function startDownload(added: () => Promise<void>) {
  vi.useFakeTimers();
  vi.spyOn(api, "huggingFaceTokenStatus").mockResolvedValue({ hasToken: false });
  vi.spyOn(api, "huggingFaceMetadata").mockResolvedValue({ models: [] });
  vi.spyOn(api, "searchHuggingFace").mockResolvedValue({ models: [{ repoId: "org/model", publisher: "org", revision: "fixed", displayName: "Test model", downloads: 1, gated: false, compatibility: "gguf", warning: null, downloadSizeBytes: 24, inferredTags: [] }] });
  vi.spyOn(api, "huggingFaceGgufVariants").mockResolvedValue({ repoId: "org/model", revision: "fixed", variants: [{ id: "Q4", quantization: "Q4", files: ["model.gguf"], shardCount: 1, downloadSizeBytes: 24 }] });
  vi.spyOn(api, "downloadHuggingFace").mockResolvedValue({ id: "download", state: "queued" });
  const view = render(<BuiltInLlmDialog onAdded={added} onClose={vi.fn()} />);
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
  return view;
}

it("keeps polling after one failed status request and finishes the addition", async () => {
  const added = vi.fn().mockResolvedValue(undefined);
  const poll = vi.spyOn(api, "huggingFaceDownload").mockResolvedValueOnce({ id: "download", state: "downloading", downloadedBytes: 1, totalBytes: 24 }).mockRejectedValueOnce(new ApiConnectionError("接続できません")).mockResolvedValue({ id: "download", state: "complete", downloadedBytes: 24, totalBytes: 24 });
  await startDownload(added);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(poll.mock.calls.length).toBeGreaterThanOrEqual(3);
  expect(added).toHaveBeenCalledExactlyOnceWith("Test model");
});

it("stops polling when the dialog is closed", async () => {
  const poll = vi.spyOn(api, "huggingFaceDownload").mockResolvedValue({ id: "download", state: "downloading", downloadedBytes: 1, totalBytes: 24 });
  const view = await startDownload(vi.fn());
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1500);
  });
  view.unmount();
  const calls = poll.mock.calls.length;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(poll).toHaveBeenCalledTimes(calls);
});

const running = { id: "download", state: "downloading", downloadedBytes: 1, totalBytes: 24 };

it("does not stay busy after the server reports the download job is gone", async () => {
  vi.spyOn(api, "huggingFaceDownload")
    .mockResolvedValueOnce(running)
    .mockRejectedValue(new ApiError("ジョブが見つかりません", 404, null, undefined, "http"));
  await startDownload(vi.fn());
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1500);
  });
  expect(screen.getByText("ジョブが見つかりません")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "取得して追加" })).toBeEnabled();
});

it("keeps Cancel available after a non-retryable status failure so the job cannot be duplicated", async () => {
  const poll = vi.spyOn(api, "huggingFaceDownload").mockResolvedValueOnce(running).mockRejectedValue(new Error("状態を取得できません"));
  const start = vi.spyOn(api, "downloadHuggingFace");
  await startDownload(vi.fn());
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1500);
  });
  expect(screen.getByText("状態を取得できません")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "取得して追加" })).not.toBeInTheDocument();
  const calls = poll.mock.calls.length;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(poll).toHaveBeenCalledTimes(calls);
  vi.spyOn(api, "cancelHuggingFaceDownload").mockResolvedValue({ id: "download", state: "cancelled", downloadedBytes: 1, totalBytes: 24 } as never);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "追加を取り消す" }));
  });
  expect(start).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "閉じる" })).toBeEnabled();
});

it("restores Cancel when the cancel request itself fails", async () => {
  vi.spyOn(api, "huggingFaceDownload").mockResolvedValueOnce(running).mockRejectedValue(new Error("状態を取得できません"));
  await startDownload(vi.fn());
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1500);
  });
  vi.spyOn(api, "cancelHuggingFaceDownload").mockRejectedValue(new Error("接続できません"));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "追加を取り消す" }));
  });
  expect(screen.getByText(/取消を要求できませんでした: 接続できません/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "追加を取り消す" })).toBeEnabled();
});
