import { useState } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiConnectionError, ApiError } from "../../api-error";
import type { RhubarbStatus } from "../../types";
import { RhubarbDialog } from "./RhubarbSetting";

const api = vi.hoisted(() => ({ rhubarbStatus: vi.fn(), installRhubarb: vi.fn(), cancelRhubarbInstall: vi.fn(), deleteRhubarb: vi.fn() }));
vi.mock("../../api", () => ({ api, openExternal: vi.fn() }));
const downloading: RhubarbStatus = {
  provider: "Rhubarb",
  version: "1",
  releaseId: "test-release",
  platform: "darwin-arm64",
  supported: true,
  available: true,
  installed: false,
  ready: false,
  archiveBytes: 100,
  license: "MIT",
  sourceUrl: "https://example.com/source",
  releaseUrl: "https://example.com/release",
  job: { id: "addon", state: "downloading", message: "取得中", downloadedBytes: 25, totalBytes: 100 },
};
const complete: RhubarbStatus = { ...downloading, installed: true, ready: true, job: { ...downloading.job!, state: "complete" } };
function setup(initial = downloading) {
  const onReady = vi.fn();
  const onChanged = vi.fn();
  function Owner() {
    const [status, setStatus] = useState(initial);
    return (
      <RhubarbDialog
        exportMode
        status={status}
        onClose={vi.fn()}
        onReady={onReady}
        onChanged={(next) => {
          onChanged(next);
          setStatus(next);
        }}
      />
    );
  }
  return { ...render(<Owner />), onReady, onChanged };
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it.each([new ApiConnectionError("offline"), new ApiError("unavailable", 503, null, undefined, "http")])("keeps progress and resumes addon monitoring after %s", async (error) => {
  api.rhubarbStatus
    .mockRejectedValueOnce(error)
    .mockResolvedValueOnce({ ...downloading, job: { ...downloading.job!, downloadedBytes: 50 } })
    .mockResolvedValue(complete);
  const view = setup();
  await act(() => vi.advanceTimersByTimeAsync(500));
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
  expect(screen.getByRole("alert")).toHaveTextContent(error.message);
  expect(view.onReady).not.toHaveBeenCalled();
  await act(() => vi.advanceTimersByTimeAsync(500));
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  await act(() => vi.advanceTimersByTimeAsync(500));
  expect(view.onReady).toHaveBeenCalledOnce();
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  expect(api.installRhubarb).not.toHaveBeenCalled();
  expect(api.rhubarbStatus).toHaveBeenCalledTimes(3);
});

it("does not resume export from a polling result after its dialog unmounts", async () => {
  let finish!: (status: RhubarbStatus) => void;
  api.rhubarbStatus.mockImplementation(() => new Promise((resolve) => (finish = resolve)));
  const view = setup();
  await act(() => vi.advanceTimersByTimeAsync(500));
  view.unmount();
  await act(async () => finish(complete));
  expect(view.onChanged).not.toHaveBeenCalled();
  expect(view.onReady).not.toHaveBeenCalled();
});

it("stops polling and shows a permanent failure", async () => {
  api.rhubarbStatus.mockRejectedValue(new ApiError("forbidden", 403, null, undefined, "http"));
  const view = setup();
  await act(() => vi.advanceTimersByTimeAsync(2000));
  expect(screen.getByRole("alert")).toHaveTextContent("forbidden");
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  expect(api.rhubarbStatus).toHaveBeenCalledOnce();
  expect(view.onReady).not.toHaveBeenCalled();
});

it("reports completion once when a cancellation reply arrives after polling completed", async () => {
  let finish!: () => void;
  api.cancelRhubarbInstall.mockImplementation(() => new Promise<void>((resolve) => (finish = resolve)));
  api.rhubarbStatus.mockResolvedValue(complete);
  const view = setup();
  fireEvent.click(screen.getByRole("button", { name: "キャンセル" }));
  await act(() => vi.advanceTimersByTimeAsync(500));
  expect(view.onReady).toHaveBeenCalledOnce();
  await act(async () => finish());
  expect(view.onReady).toHaveBeenCalledOnce();
  expect(api.rhubarbStatus).toHaveBeenCalledOnce();
});

it("does not fetch or apply cancellation status after its dialog is removed", async () => {
  let finish!: () => void;
  api.cancelRhubarbInstall.mockImplementation(() => new Promise<void>((resolve) => (finish = resolve)));
  api.rhubarbStatus.mockResolvedValue(complete);
  const view = setup();
  fireEvent.click(screen.getByRole("button", { name: "キャンセル" }));
  view.unmount();
  await act(async () => finish());
  expect(view.onReady).not.toHaveBeenCalled();
  expect(view.onChanged).not.toHaveBeenCalled();
  expect(api.rhubarbStatus).not.toHaveBeenCalled();
});

it("waits for start acknowledgement before polling an earlier terminal job", async () => {
  let finish!: (job: RhubarbStatus["job"]) => void;
  api.installRhubarb.mockImplementation(() => new Promise((resolve) => (finish = resolve)));
  api.rhubarbStatus.mockResolvedValue(complete);
  const view = setup({ ...complete, updateAvailable: true });
  fireEvent.click(screen.getByRole("button", { name: "更新してエクスポート" }));
  await act(() => vi.advanceTimersByTimeAsync(1000));
  expect(screen.getByRole("progressbar")).toBeInTheDocument();
  expect(view.onReady).not.toHaveBeenCalled();
  expect(api.rhubarbStatus).not.toHaveBeenCalled();
  await act(async () => finish(downloading.job));
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
  await act(() => vi.advanceTimersByTimeAsync(500));
  expect(view.onReady).toHaveBeenCalledOnce();
});

it("ignores an install acknowledgement after unmount", async () => {
  let finish!: (job: RhubarbStatus["job"]) => void;
  api.installRhubarb.mockImplementation(() => new Promise((resolve) => (finish = resolve)));
  const view = setup({ ...downloading, job: null });
  fireEvent.click(screen.getByRole("button", { name: "追加してエクスポート" }));
  view.unmount();
  await act(async () => finish(downloading.job));
  expect(view.onChanged).not.toHaveBeenCalled();
});

it("keeps deletion failures in the dialog instead of rejecting its click handler", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  api.deleteRhubarb.mockRejectedValue(new Error("delete failed"));
  const onChanged = vi.fn();
  render(<RhubarbDialog status={complete} onChanged={onChanged} onClose={vi.fn()} />);
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "削除" })));
  expect(screen.getByRole("alert")).toHaveTextContent("delete failed");
  expect(onChanged).not.toHaveBeenCalled();
});
