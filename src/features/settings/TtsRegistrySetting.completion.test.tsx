import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as apiModule from "../../api";
import type { TtsAssetCard, TtsCatalog, TtsCatalogItem, TtsRegistry } from "../../types";
import { modelRegistryCache } from "../shared/modelRegistryCache";
import { TtsRegistrySetting } from "./TtsRegistrySetting";

const card = { id: "installed", displayName: "追加したモデル", source: "managed", repo: "test/model", diskBytes: 1, verification: "verified" } as TtsAssetCard;
const registry = { version: 3, defaultEngineId: null, defaultModelId: null, engines: [], models: [], libraries: [], projectSelection: null } as TtsRegistry;
const installed = { ...registry, models: [card], defaultModelId: card.id };
const catalog = { version: 1, verified: true, source: "test", engines: [], models: [{ id: card.id, displayName: card.displayName, repo: card.repo, precision: "FP32", sizeBytes: 100, installable: true } as TtsCatalogItem] } as TtsCatalog;

beforeEach(() => {
  vi.useFakeTimers();
  modelRegistryCache.reset();
  vi.spyOn(apiModule.api, "ttsRegistry").mockResolvedValueOnce(registry).mockRejectedValueOnce(new Error("refresh offline")).mockResolvedValue(installed);
  vi.spyOn(apiModule.api, "ttsCatalog").mockResolvedValue(catalog);
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  modelRegistryCache.reset();
});

async function openSettings() {
  await act(async () => {
    render(<TtsRegistrySetting isScratch={false} onLegacyEngine={vi.fn()} onSelectionChanged={vi.fn()} />);
  });
  fireEvent.click(screen.getByRole("button", { name: /音声モデルがありません/ }));
}

it("retries registry loading before showing managed installation as complete", async () => {
  vi.spyOn(apiModule.api, "startTtsInstall").mockResolvedValue({ id: "install", state: "running" } as never);
  const poll = vi.spyOn(apiModule.api, "ttsInstall").mockResolvedValue({ id: "install", state: "complete" } as never);
  await openSettings();
  fireEvent.click(screen.getByRole("button", { name: /\+ 音声モデル/ }));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "追加" })));
  await act(() => vi.advanceTimersByTimeAsync(500));
  expect(screen.queryByText("導入が完了しました")).not.toBeInTheDocument();
  expect(screen.getByText("refresh offline")).toBeInTheDocument();
  await act(() => vi.advanceTimersByTimeAsync(500));
  expect(screen.getByText("導入が完了しました")).toBeInTheDocument();
  expect(screen.queryByText("refresh offline")).not.toBeInTheDocument();
  expect(modelRegistryCache.tts()?.models.map((item) => item.id)).toEqual([card.id]);
  expect(poll).toHaveBeenCalledTimes(2);
});

it("keeps library registration active until the installed registry refresh succeeds", async () => {
  vi.spyOn(apiModule, "chooseDirectory").mockResolvedValue("/test/library");
  vi.spyOn(apiModule.api, "scanTtsLibrary").mockResolvedValue({
    root: "/test/library",
    displayName: "library",
    limited: false,
    engines: [{ id: "engine", path: "/test/engine", pythonPath: null }],
    models: [{ id: "source", path: "/test/model", tokenizerPath: "/test/tokenizer", displayName: "library model", repo: null, revision: null, location: "model" }],
    codecs: [{ id: "codec", path: "/test/codec" }],
    warnings: [],
  });
  vi.spyOn(apiModule.api, "registerTtsLibrary").mockResolvedValue({ ...registry, libraries: [{ id: "library", root: "/test/library" }] } as TtsRegistry);
  vi.spyOn(apiModule.api, "registerTtsLibraryModel").mockResolvedValue({ id: "registration", state: "running" } as never);
  const poll = vi.spyOn(apiModule.api, "ttsLibraryModelJob").mockResolvedValue({ id: "registration", state: "complete" } as never);
  await openSettings();
  fireEvent.click(screen.getByRole("button", { name: /ストレージから追加/ }));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "フォルダを選ぶ" })));
  fireEvent.click(screen.getByRole("radio", { name: /library model/ }));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "このモデルを登録" })));
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(screen.getByRole("dialog", { name: "ストレージから追加" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "このモデルを登録" })).toBeDisabled();
  expect(screen.getByText("refresh offline")).toBeInTheDocument();
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(screen.queryByRole("dialog", { name: "ストレージから追加" })).not.toBeInTheDocument();
  expect(modelRegistryCache.tts()?.models.map((item) => item.id)).toEqual([card.id]);
  expect(poll).toHaveBeenCalledTimes(2);
});
