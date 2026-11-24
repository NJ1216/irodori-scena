// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import { RhubarbDialog, RhubarbSetting } from "./RhubarbSetting";

vi.mock("../../api", () => ({
  api: {
    rhubarbStatus: vi.fn(),
    installRhubarb: vi.fn(),
    cancelRhubarbInstall: vi.fn(),
  },
  openExternal: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.rhubarbStatus).mockReset();
});

it("offers to replace the old runtime from settings", async () => {
  vi.mocked(api.rhubarbStatus).mockResolvedValue({
    provider: "Rhubarb",
    version: "1.14.0",
    releaseId: "new",
    platform: "darwin-arm64",
    supported: true,
    available: true,
    installed: true,
    ready: false,
    updateAvailable: true,
    installedReleaseId: "old",
    archiveBytes: 200_000_000,
    license: "MIT",
    sourceUrl: "https://example.com/source",
    releaseUrl: "https://example.com/release",
    job: null,
  });
  render(<RhubarbSetting />);
  expect(await screen.findByText("更新があります")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Rhubarbの詳細" }));
  expect(screen.getByRole("button", { name: "更新する" })).toBeEnabled();
  expect(screen.getByText(/更新後は古い版を削除します/)).toBeInTheDocument();
});

it("shows the Japanese addon license and allows cancelling installation", async () => {
  const status = {
    provider: "Rhubarb" as const,
    version: "1.14.0",
    releaseId: "review",
    platform: "darwin-arm64",
    supported: true,
    available: true,
    installed: false,
    ready: false,
    archiveBytes: 200_000_000,
    license: "MIT",
    sourceUrl: "https://example.com/source",
    releaseUrl: "https://example.com/release",
    job: null,
    japaneseAddon: { ready: false, analysisVersion: "v3", license: "Apache-2.0" },
  };
  const job = { id: "one", state: "queued" as const, message: "準備中", cancelRequested: false };
  vi.mocked(api.installRhubarb).mockResolvedValue(job);
  vi.mocked(api.cancelRhubarbInstall).mockResolvedValue({ ...job, cancelRequested: true });
  vi.mocked(api.rhubarbStatus).mockResolvedValue({ ...status, job: { ...job, cancelRequested: true } });
  const onClose = vi.fn();
  render(<RhubarbDialog status={status} onClose={onClose} onChanged={vi.fn()} />);
  expect(screen.getByText(/日本語の口形補正（Apache-2.0）/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Rhubarbを追加" }));
  await userEvent.click(screen.getByRole("button", { name: "キャンセル" }));
  expect(api.cancelRhubarbInstall).toHaveBeenCalledOnce();
  expect(onClose).not.toHaveBeenCalled();
});

it("uses the shared model-card composition for an installed Rhubarb runtime", async () => {
  vi.mocked(api.rhubarbStatus).mockResolvedValue({
    provider: "Rhubarb",
    version: "1.14.0",
    releaseId: "1.14.0-scena.1",
    platform: "darwin-arm64",
    supported: true,
    available: true,
    installed: true,
    ready: true,
    archiveBytes: 70_000_000,
    license: "MIT",
    sourceUrl: "https://example.com/source",
    releaseUrl: "https://example.com/release",
    job: null,
  });

  render(<RhubarbSetting />);

  const card = (await screen.findByText("Rhubarb")).closest("button");
  expect(card).toHaveClass("model-selection-trigger", "model-board-card", "is-default");
  expect(screen.getByText("口パクLAB")).toBeInTheDocument();
  expect(screen.getByText("導入済み")).toBeInTheDocument();
  expect(screen.getByText("v1.14.0 · 67 MB")).toBeInTheDocument();
  expect(screen.queryByText("既定")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Rhubarbの詳細" }));
  expect(screen.getByRole("dialog", { name: "Rhubarb" })).toBeInTheDocument();
  expect(screen.getByText(/Rhubarb 1.14.0（MIT）はこの端末で使用できます/)).toBeInTheDocument();
  expect(screen.queryByText("対象")).not.toBeInTheDocument();
  expect(screen.queryByText("削除方法")).not.toBeInTheDocument();
});

it("contains a status failure and lets the user retry", async () => {
  const status = {
    provider: "Rhubarb" as const,
    version: "1.14.0",
    releaseId: "1.14.0-scena.1",
    platform: "darwin-arm64",
    supported: true,
    available: true,
    installed: false,
    ready: false,
    archiveBytes: 70_000_000,
    license: "MIT",
    sourceUrl: "https://example.com/source",
    releaseUrl: "https://example.com/release",
    job: null,
  };
  vi.mocked(api.rhubarbStatus).mockRejectedValueOnce(new Error("internal failure")).mockResolvedValueOnce(status);

  render(<RhubarbSetting />);

  expect(await screen.findByRole("alert")).toHaveTextContent("Rhubarbの状態を確認できませんでした。");
  const card = screen.getByText("Rhubarb").closest("button");
  expect(card).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "再試行" }));
  expect(await screen.findByText("未導入")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(card).toBeEnabled();
});

const downloadingStatus = {
  provider: "Rhubarb" as const,
  version: "1.14.0",
  releaseId: "new",
  platform: "darwin-arm64",
  supported: true,
  available: true,
  installed: false,
  ready: false,
  archiveBytes: 200_000_000,
  license: "MIT",
  sourceUrl: "https://example.com/source",
  releaseUrl: "https://example.com/release",
  job: { id: "one", state: "downloading" as const, message: "ダウンロード中", downloadedBytes: 50_000_000, totalBytes: 200_000_000 },
};

it("shows and polls download progress when reopening settings during installation", async () => {
  vi.mocked(api.rhubarbStatus)
    .mockResolvedValueOnce(downloadingStatus)
    .mockResolvedValue({
      ...downloadingStatus,
      job: { ...downloadingStatus.job, downloadedBytes: 100_000_000 },
    });
  render(<RhubarbSetting />);
  await userEvent.click(await screen.findByRole("button", { name: "Rhubarbの詳細" }));
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
  expect(screen.getByText("25%")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50"));
  expect(screen.getByRole("button", { name: "Rhubarbを追加" })).toBeDisabled();
  expect(screen.queryByText(/音声は外部|補正に失敗|音素解析/)).not.toBeInTheDocument();
});

it("shows an indeterminate bar for preparation, verification and unknown download size", () => {
  const view = render(<RhubarbDialog status={{ ...downloadingStatus, archiveBytes: 0, job: { ...downloadingStatus.job, totalBytes: 0 } }} onClose={vi.fn()} onChanged={vi.fn()} />);
  expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
  for (const state of ["queued", "verifying"] as const) {
    view.rerender(<RhubarbDialog status={{ ...downloadingStatus, job: { ...downloadingStatus.job, state } }} onClose={vi.fn()} onChanged={vi.fn()} />);
    expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
  }
});

it("applies the install response immediately and finishes polling on completion", async () => {
  vi.mocked(api.rhubarbStatus)
    .mockResolvedValueOnce({ ...downloadingStatus, job: null })
    .mockResolvedValue({
      ...downloadingStatus,
      ready: true,
      installed: true,
      job: { ...downloadingStatus.job, state: "complete" },
    });
  vi.mocked(api.installRhubarb).mockResolvedValue(downloadingStatus.job);
  render(<RhubarbSetting />);
  await userEvent.click(await screen.findByRole("button", { name: "Rhubarbの詳細" }));
  await userEvent.click(screen.getByRole("button", { name: "Rhubarbを追加" }));
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
  await waitFor(() => expect(screen.queryByRole("progressbar")).not.toBeInTheDocument());
  expect(screen.getByText(/この端末で使用できます/)).toBeInTheDocument();
});
