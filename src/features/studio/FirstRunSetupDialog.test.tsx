// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import type { TtsCatalog, TtsInstallJob, TtsRegistry } from "../../types";
import { FIRST_RUN_INSTALLATION_KEY, FIRST_RUN_SETUP_KEY, FirstRunSetupDialog } from "./FirstRunSetupDialog";

const model = { id: "v41", displayName: "Irodori-TTS v4.1 Small", repo: "Aratako/Irodori-TTS-v4.1-Small", revision: "revision", installable: true, legacy: false, recommendedOrder: 1 };
const catalog = { version: 1, verified: true, source: "test", engines: [], models: [model] } as TtsCatalog;
const registry = { version: 2, defaultEngineId: null, defaultModelId: null, engines: [], models: [], libraries: [], projectSelection: null } as TtsRegistry;
const job = (state: TtsInstallJob["state"], extra: Partial<TtsInstallJob> = {}) => ({ id: "job", assetKind: "model", assetId: model.id, state, stage: "モデル", downloadedBytes: 25, totalBytes: 100, currentFile: "model.safetensors", error: null, ...extra }) as TtsInstallJob;

beforeEach(() => {
  localStorage.clear();
  vi.spyOn(api, "ttsCatalog").mockResolvedValue(catalog);
  vi.spyOn(api, "ttsRegistry").mockResolvedValue(registry);
});

afterEach(() => vi.restoreAllMocks());

it("opens only until explicitly dismissed on this SCENA version", async () => {
  const view = render(<FirstRunSetupDialog onOpenLlmSettings={vi.fn()} />);
  expect(await screen.findByRole("heading", { name: "生成機能の準備" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "あとで" }));
  expect(localStorage.getItem(FIRST_RUN_SETUP_KEY)).toBe("seen");
  view.unmount();
  render(<FirstRunSetupDialog onOpenLlmSettings={vi.fn()} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("opens again when a fresh installation has a different identity", async () => {
  localStorage.setItem(FIRST_RUN_INSTALLATION_KEY, "removed-installation");
  localStorage.setItem(FIRST_RUN_SETUP_KEY, "seen");
  render(<FirstRunSetupDialog onOpenLlmSettings={vi.fn()} />);
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
});

it("does not reopen for an in-place update with the same identity", () => {
  localStorage.setItem(FIRST_RUN_INSTALLATION_KEY, "development");
  render(<FirstRunSetupDialog onOpenLlmSettings={vi.fn()} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("migrates a legacy version dismissal without reopening on update", () => {
  localStorage.setItem(FIRST_RUN_SETUP_KEY, "seen");
  render(<FirstRunSetupDialog onOpenLlmSettings={vi.fn()} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(localStorage.getItem(FIRST_RUN_INSTALLATION_KEY)).toBe("development");
});

it("starts the recommended install, shows progress, and allows cancellation", async () => {
  vi.useFakeTimers();
  vi.spyOn(api, "startTtsInstall").mockResolvedValue(job("running"));
  vi.spyOn(api, "ttsInstall").mockResolvedValue(job("running", { downloadedBytes: 50 }));
  const cancel = vi.spyOn(api, "cancelTtsInstall").mockResolvedValue(job("cancelling"));
  render(<FirstRunSetupDialog onOpenLlmSettings={vi.fn()} />);
  await act(async () => Promise.resolve());
  fireEvent.click(screen.getByRole("button", { name: "推奨モデルをダウンロード" }));
  await act(async () => Promise.resolve());
  expect(api.startTtsInstall).toHaveBeenCalledWith("model", model.id);
  expect(screen.getByText("必要な資産を導入中")).toBeInTheDocument();
  await act(async () => vi.advanceTimersByTimeAsync(500));
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  await act(async () => Promise.resolve());
  expect(cancel).toHaveBeenCalledWith("job");
  expect(screen.getByText("取消中です")).toBeInTheDocument();
  vi.useRealTimers();
});

it("uses the platform-recommended variant for a fresh installation", async () => {
  const variantModel = {
    ...model,
    variants: [
      { id: "pytorch-fp32", displayName: "FP32", precision: "FP32", backend: "pytorch", repo: model.repo, revision: model.revision, sizeBytes: 1, runtimeProfile: "pytorch-fp32", available: true, recommendedOrder: 2 },
      { id: "mlx-fp16", displayName: "FP16", precision: "FP16", backend: "mlx", repo: "mlx/model", revision: "mlx-revision", sizeBytes: 1, runtimeProfile: "mlx-fp16", available: true, recommendedOrder: 1 },
    ],
  };
  vi.mocked(api.ttsCatalog).mockResolvedValue({ ...catalog, version: 2, models: [variantModel] } as TtsCatalog);
  const start = vi.spyOn(api, "startTtsVariantInstall").mockResolvedValue(job("running"));
  render(<FirstRunSetupDialog onOpenLlmSettings={vi.fn()} />);
  await screen.findByRole("button", { name: "推奨モデルをダウンロード" });
  fireEvent.click(screen.getByRole("button", { name: "推奨モデルをダウンロード" }));
  await waitFor(() => expect(start).toHaveBeenCalledWith(model.id, "mlx-fp16"));
});

it("does not download an installed model and opens LLM settings", async () => {
  vi.mocked(api.ttsRegistry).mockResolvedValue({ ...registry, models: [{ ...model, source: "managed", diskBytes: 1, verification: "verified" }] } as TtsRegistry);
  const openLlm = vi.fn();
  render(<FirstRunSetupDialog onOpenLlmSettings={openLlm} />);
  expect(await screen.findByText("導入済みです。音声を生成できます。")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /ダウンロード/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "LLM設定を開く" }));
  expect(openLlm).toHaveBeenCalledOnce();
  expect(localStorage.getItem(FIRST_RUN_SETUP_KEY)).toBe("seen");
});

it("opens the LLM usage hint without dismissing the first-run guide", async () => {
  render(<FirstRunSetupDialog onOpenLlmSettings={vi.fn()} />);
  await screen.findByRole("heading", { name: "生成機能の準備" });
  fireEvent.click(screen.getByRole("button", { name: "使い方のヒント" }));
  expect(screen.getByRole("dialog", { name: "LLMモデルを使うヒント" })).toBeInTheDocument();
  expect(localStorage.getItem(FIRST_RUN_SETUP_KEY)).toBeNull();
});

it("shows failure, retries the same model, and reports completion", async () => {
  vi.useFakeTimers();
  const start = vi.spyOn(api, "startTtsInstall").mockResolvedValueOnce(job("running")).mockResolvedValueOnce(job("running"));
  vi.spyOn(api, "ttsInstall")
    .mockResolvedValueOnce(job("failed", { error: "network failed" }))
    .mockResolvedValueOnce(job("complete", { downloadedBytes: 100 }));
  render(<FirstRunSetupDialog onOpenLlmSettings={vi.fn()} />);
  await act(async () => Promise.resolve());
  fireEvent.click(screen.getByRole("button", { name: "推奨モデルをダウンロード" }));
  await act(async () => Promise.resolve());
  await act(async () => vi.advanceTimersByTimeAsync(500));
  expect(screen.getByText("導入に失敗しました")).toBeInTheDocument();
  expect(screen.getByText("network failed")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "ダウンロードを再試行" }));
  await act(async () => Promise.resolve());
  await act(async () => vi.advanceTimersByTimeAsync(500));
  expect(start).toHaveBeenCalledTimes(2);
  expect(screen.getByText("導入が完了しました")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "閉じる" })).toBeInTheDocument();
  vi.useRealTimers();
});

it("records Escape and backdrop dismissal", async () => {
  const first = render(<FirstRunSetupDialog onOpenLlmSettings={vi.fn()} />);
  await screen.findByRole("dialog");
  fireEvent.keyDown(window, { key: "Escape" });
  expect(localStorage.getItem(FIRST_RUN_SETUP_KEY)).toBe("seen");
  first.unmount();
  localStorage.clear();
  render(<FirstRunSetupDialog onOpenLlmSettings={vi.fn()} />);
  const dialog = await screen.findByRole("dialog");
  fireEvent.mouseDown(dialog.parentElement!);
  await waitFor(() => expect(localStorage.getItem(FIRST_RUN_SETUP_KEY)).toBe("seen"));
});
