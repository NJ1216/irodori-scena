// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import type { TtsAssetCard, TtsCatalog, TtsRegistry } from "../../types";
import { modelRegistryCache } from "../shared/modelRegistryCache";
import { TtsRegistrySetting } from "./TtsRegistrySetting";

const current = { id: "current", displayName: "現在のモデル", source: "managed", repo: "current", diskBytes: 1, verification: "verified" } as TtsAssetCard;
const next = { id: "next", displayName: "次のモデル", source: "managed", repo: "next", diskBytes: 1, verification: "verified" } as TtsAssetCard;
const registry = { version: 3, defaultEngineId: null, defaultModelId: current.id, engines: [], models: [current, next], libraries: [], projectSelection: null } as TtsRegistry;
const catalog = { version: 1, verified: true, source: "test", engines: [], models: [] } as TtsCatalog;

beforeEach(() => {
  modelRegistryCache.reset();
  vi.spyOn(api, "ttsRegistry").mockResolvedValue(registry);
  vi.spyOn(api, "ttsCatalog").mockResolvedValue(catalog);
});
afterEach(() => {
  vi.restoreAllMocks();
  modelRegistryCache.reset();
});

it("shows a central notice until a model picked from the settings list is selected", async () => {
  const updated = { ...registry, defaultModelId: next.id };
  let finishSelection: ((value: TtsRegistry) => void) | undefined;
  const select = vi.spyOn(api, "setTtsDefaults").mockImplementation(
    () =>
      new Promise((resolve) => {
        finishSelection = resolve;
      }),
  );
  vi.spyOn(api, "ttsRuntimeStatus").mockResolvedValue({ state: "ready", modelId: next.id } as never);
  render(<TtsRegistrySetting isScratch={false} onLegacyEngine={vi.fn()} onSelectionChanged={vi.fn()} />);

  fireEvent.click(await screen.findByRole("button", { name: /現在のモデル/ }));
  fireEvent.click(await screen.findByRole("option", { name: /次のモデル/ }));
  expect(select).toHaveBeenCalledWith(next.id);
  expect(screen.getByRole("status")).toHaveTextContent("モデルを切り替えています…");
  expect(document.querySelector(".modal-backdrop")).toHaveAttribute("data-dismiss-disabled", "true");

  await act(async () => {
    finishSelection?.(updated);
  });
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /次のモデル/ })).toBeInTheDocument();
});

it("removes the busy notice and shows the existing selection error after failure", async () => {
  let failSelection: ((error: Error) => void) | undefined;
  vi.spyOn(api, "setTtsDefaults").mockImplementation(
    () =>
      new Promise((_, reject) => {
        failSelection = reject;
      }),
  );
  render(<TtsRegistrySetting isScratch={false} onLegacyEngine={vi.fn()} onSelectionChanged={vi.fn()} />);

  fireEvent.click(await screen.findByRole("button", { name: /現在のモデル/ }));
  fireEvent.click(await screen.findByRole("option", { name: /次のモデル/ }));
  expect(screen.getByRole("status")).toHaveTextContent("モデルを切り替えています…");

  await act(async () => {
    failSelection?.(new Error("切り替え失敗"));
  });
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("音声モデルを切り替えられませんでした: 切り替え失敗");
});

it("retains the selected model when its background preparation fails", async () => {
  const updated = { ...registry, defaultModelId: next.id };
  vi.spyOn(api, "setTtsDefaults").mockResolvedValue(updated);
  vi.spyOn(api, "ttsRuntimeStatus").mockResolvedValue({ state: "failed", modelId: next.id, error: "読み込み失敗" } as never);
  render(<TtsRegistrySetting isScratch={false} onLegacyEngine={vi.fn()} onSelectionChanged={vi.fn()} />);

  fireEvent.click(await screen.findByRole("button", { name: /現在のモデル/ }));
  fireEvent.click(await screen.findByRole("option", { name: /次のモデル/ }));

  expect(await screen.findByRole("alert")).toHaveTextContent("モデルは切り替わりましたが、読み込み失敗");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /次のモデル/ })).toBeInTheDocument();
});
