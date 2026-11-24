// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { api } from "../../api";
import type { TtsAssetCard, TtsProjectSelection, TtsRegistry, TtsRuntimeStatus } from "../../types";
import { CapabilityList, TtsModelDialog } from "./TtsModelDialog";
import { TtsCardContent } from "./TtsRegistrySetting";

it("shows only audio generation and VoiceDesign capability pills", () => {
  const { rerender } = render(<CapabilityList item={{ voiceDesign: false } as TtsAssetCard} />);
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
  expect(screen.getByRole("listitem", { name: "音声生成：対応" })).toHaveTextContent("音声生成");
  expect(screen.getByRole("listitem", { name: "VoiceDesign：非対応" })).toHaveTextContent("VoiceDesign");
  expect(screen.getByRole("list")).not.toHaveTextContent("対応");
  expect(screen.getByRole("list")).not.toHaveTextContent("非対応");

  rerender(<CapabilityList item={{ voiceDesign: true } as TtsAssetCard} />);
  expect(screen.getByRole("listitem", { name: "VoiceDesign：対応" })).toHaveTextContent("VoiceDesign");
});

it("does not expose the obsolete inference mode controls", () => {
  const selection: TtsProjectSelection = {
    engine: { repo: "Aratako/Irodori-TTS", commit: "engine", externalId: null },
    model: { repo: "Aratako/Irodori-TTS-v4.1-Small", revision: "model" },
    codecRevision: "codec",
    optimizationProfile: "cuda-fp32-v1",
  };
  const card = {
    id: "model-id",
    displayName: "Irodori",
    source: "managed",
    repo: selection.model?.repo,
    revision: "model",
    diskBytes: 1,
    verification: "verified",
  } as TtsAssetCard;
  const registry = {
    version: 2,
    defaultEngineId: "engine-id",
    defaultModelId: card.id,
    engines: [],
    models: [card],
    libraries: [],
    projectSelection: selection,
  } as TtsRegistry;
  render(<TtsModelDialog card={card} registry={registry} isDefault isScratch={false} onClose={vi.fn()} onChanged={vi.fn()} onSelectionChanged={vi.fn()} />);

  expect(screen.queryByText("推論の詳細")).not.toBeInTheDocument();
  expect(screen.queryByRole("radio", { name: "高速化優先" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "実行モードを保存" })).not.toBeInTheDocument();
});

it("applies an installed MLX variant globally and hides PyTorch inference details", async () => {
  const card = {
    id: "model-id",
    displayName: "Irodori",
    source: "managed",
    repo: "base",
    revision: "revision",
    diskBytes: 1,
    verification: "verified",
    activeVariantId: "pytorch-fp32",
    installedVariants: [
      { id: "pytorch-fp32", precision: "FP32", backend: "pytorch", repo: "base", revision: "revision", optimizationProfile: "pytorch-fp32" },
      { id: "mlx-fp16", precision: "FP16", backend: "mlx", repo: "mlx", revision: "mlx-revision", optimizationProfile: "mlx-audio-0.5.0-fp16" },
    ],
  } as TtsAssetCard;
  const registry = { version: 3, defaultEngineId: null, defaultModelId: card.id, engines: [], models: [card], libraries: [], projectSelection: null } as TtsRegistry;
  const updated = { ...registry, models: [{ ...card, activeVariantId: "mlx-fp16" }] };
  const apply = vi.spyOn(api, "setTtsActiveVariant").mockResolvedValue(updated);
  const changed = vi.fn();
  render(<TtsModelDialog card={card} registry={registry} isDefault isScratch={false} onClose={vi.fn()} onChanged={changed} onSelectionChanged={vi.fn()} />);

  fireEvent.click(screen.getByRole("radio", { name: "FP16" }));
  expect(screen.queryByText("推論の詳細")).not.toBeInTheDocument();

  await vi.waitFor(() => expect(apply).toHaveBeenCalledWith(card.id, "mlx-fp16"));
  expect(changed).toHaveBeenCalledWith(updated);
  expect(screen.queryByRole("button", { name: "適用" })).not.toBeInTheDocument();
  expect(screen.queryByText("このモデルを使用するすべてのプロジェクトに反映されます。")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "モデルを削除" })).toBeInTheDocument();
});

it("shows a central busy notice while selecting a model from its details", async () => {
  const card = { id: "next-model", displayName: "次のモデル", source: "managed", repo: "next", diskBytes: 1, verification: "verified" } as TtsAssetCard;
  const registry = { version: 3, defaultEngineId: null, defaultModelId: "current-model", engines: [], models: [card], libraries: [], projectSelection: null } as TtsRegistry;
  const updated = { ...registry, defaultModelId: card.id };
  let finishSelection: ((value: TtsRegistry) => void) | undefined;
  let finishPreparation: ((value: TtsRuntimeStatus) => void) | undefined;
  const select = vi.spyOn(api, "setTtsDefaults").mockImplementation(
    () =>
      new Promise((resolve) => {
        finishSelection = resolve;
      }),
  );
  vi.spyOn(api, "ttsRuntimeStatus").mockImplementation(
    () =>
      new Promise((resolve) => {
        finishPreparation = resolve;
      }),
  );
  const changed = vi.fn();
  const close = vi.fn();
  render(<TtsModelDialog card={card} registry={registry} isDefault={false} isScratch={false} onClose={close} onChanged={changed} onSelectionChanged={vi.fn()} />);

  fireEvent.click(screen.getByRole("button", { name: "このモデルを選択" }));
  expect(select).toHaveBeenCalledWith(card.id);
  expect(screen.getByRole("status")).toHaveTextContent("モデルを切り替えています…");
  expect(screen.getByRole("button", { name: "このモデルを選択" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "閉じる" })).toBeDisabled();
  fireEvent.keyDown(window, { key: "Escape" });
  expect(close).not.toHaveBeenCalled();

  await act(async () => {
    finishSelection?.(updated);
  });
  expect(screen.getByRole("status")).toHaveTextContent("モデルを切り替えています…");
  expect(changed).not.toHaveBeenCalled();
  await act(async () => {
    finishPreparation?.({ state: "ready", modelId: card.id } as TtsRuntimeStatus);
  });
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(changed).toHaveBeenCalledWith(updated);
});

it("deletes a managed model with all installed variants after confirmation", async () => {
  const card = {
    id: "model-id",
    displayName: "Irodori",
    source: "managed",
    repo: "base",
    revision: "revision",
    diskBytes: 3,
    verification: "verified",
    activeVariantId: "pytorch-fp32",
    installedVariants: [
      { id: "pytorch-fp32", precision: "FP32", backend: "pytorch", repo: "base", revision: "revision", optimizationProfile: "pytorch-fp32" },
      { id: "mlx-fp16", precision: "FP16", backend: "mlx", repo: "mlx", revision: "mlx-revision", optimizationProfile: "mlx-audio-0.5.0-fp16" },
    ],
  } as TtsAssetCard;
  const registry = { version: 3, defaultEngineId: null, defaultModelId: card.id, engines: [], models: [card], libraries: [], projectSelection: null } as TtsRegistry;
  const updated = { ...registry, defaultModelId: null, models: [] };
  let finishRemoval: ((value: TtsRegistry) => void) | undefined;
  const remove = vi.spyOn(api, "deleteTtsAsset").mockImplementation(
    () =>
      new Promise((resolve) => {
        finishRemoval = resolve;
      }),
  );
  const changed = vi.fn();
  const close = vi.fn();
  render(<TtsModelDialog card={card} registry={registry} isDefault isScratch={false} onClose={close} onChanged={changed} onSelectionChanged={vi.fn()} />);

  fireEvent.click(screen.getByRole("button", { name: "モデルを削除" }));
  expect(remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "もう一度押してモデルを削除" }));

  await vi.waitFor(() => expect(remove).toHaveBeenCalledWith("model", card.id));
  expect(screen.getByRole("status")).toHaveTextContent("モデルを削除しています…");
  expect(screen.getByRole("button", { name: "もう一度押してモデルを削除" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "閉じる" })).toBeDisabled();
  fireEvent.mouseDown(screen.getByRole("dialog").parentElement!);
  fireEvent.keyDown(window, { key: "Escape" });
  expect(close).not.toHaveBeenCalled();

  await act(async () => {
    finishRemoval?.(updated);
  });
  expect(changed).toHaveBeenCalledWith(updated);
  expect(close).toHaveBeenCalledOnce();
});

it("restores dialog controls and shows an error when model deletion fails", async () => {
  const card = { id: "model-id", displayName: "Irodori", source: "managed", repo: "base", diskBytes: 1, verification: "verified" } as TtsAssetCard;
  const registry = { version: 3, defaultEngineId: null, defaultModelId: card.id, engines: [], models: [card], libraries: [], projectSelection: null } as TtsRegistry;
  let failRemoval: ((error: Error) => void) | undefined;
  vi.spyOn(api, "deleteTtsAsset").mockImplementation(
    () =>
      new Promise((_, reject) => {
        failRemoval = reject;
      }),
  );
  const close = vi.fn();
  render(<TtsModelDialog card={card} registry={registry} isDefault isScratch={false} onClose={close} onChanged={vi.fn()} onSelectionChanged={vi.fn()} />);

  fireEvent.click(screen.getByRole("button", { name: "モデルを削除" }));
  fireEvent.click(screen.getByRole("button", { name: "もう一度押してモデルを削除" }));
  expect(screen.getByRole("status")).toHaveTextContent("モデルを削除しています…");

  await act(async () => {
    failRemoval?.(new Error("削除できません"));
  });
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.getByText("削除できません")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "モデルを削除" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "閉じる" })).toBeEnabled();
  expect(close).not.toHaveBeenCalled();
});

it("reveals a Take-style delete action and removes an installed variant after confirmation", async () => {
  const card = {
    id: "model-id",
    displayName: "Irodori",
    source: "managed",
    repo: "base",
    revision: "revision",
    diskBytes: 3,
    verification: "verified",
    activeVariantId: "pytorch-fp32",
    installedVariants: [
      { id: "pytorch-fp32", precision: "FP32", backend: "pytorch", repo: "base", revision: "revision", optimizationProfile: "pytorch-fp32" },
      { id: "mlx-fp16", precision: "FP16", backend: "mlx", repo: "mlx", revision: "mlx-revision", optimizationProfile: "mlx-audio-0.5.0-fp16" },
    ],
  } as TtsAssetCard;
  const registry = { version: 3, defaultEngineId: null, defaultModelId: card.id, engines: [], models: [card], libraries: [], projectSelection: null } as TtsRegistry;
  const nextCard = { ...card, activeVariantId: "mlx-fp16", installedVariants: [card.installedVariants![1]] };
  const updated = { ...registry, models: [nextCard] };
  const remove = vi.spyOn(api, "deleteTtsVariant").mockResolvedValue(updated);
  const changed = vi.fn();
  render(<TtsModelDialog card={card} registry={registry} isDefault isScratch={false} onClose={vi.fn()} onChanged={changed} onSelectionChanged={vi.fn()} />);

  fireEvent.click(screen.getByRole("button", { name: "FP32バリアントを削除" }));
  expect(remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "FP32バリアントの削除を確定" }));

  await vi.waitFor(() => expect(remove).toHaveBeenCalledWith(card.id, "pytorch-fp32"));
  expect(changed).toHaveBeenCalledWith(updated);
  await vi.waitFor(() => expect(screen.getByRole("radio", { name: "FP16" })).toBeChecked());
});

it("closes the model dialog after deleting its final variant", async () => {
  const card = {
    id: "model-id",
    displayName: "Irodori",
    source: "managed",
    repo: "base",
    revision: "revision",
    diskBytes: 1,
    verification: "verified",
    activeVariantId: "pytorch-fp32",
    installedVariants: [{ id: "pytorch-fp32", precision: "FP32", backend: "pytorch", repo: "base", revision: "revision", optimizationProfile: "pytorch-fp32" }],
  } as TtsAssetCard;
  const registry = { version: 3, defaultEngineId: null, defaultModelId: card.id, engines: [], models: [card], libraries: [], projectSelection: null } as TtsRegistry;
  const updated = { ...registry, defaultModelId: null, models: [] };
  vi.spyOn(api, "deleteTtsVariant").mockResolvedValue(updated);
  const close = vi.fn();
  render(<TtsModelDialog card={card} registry={registry} isDefault isScratch={false} onClose={close} onChanged={vi.fn()} onSelectionChanged={vi.fn()} />);

  fireEvent.click(screen.getByRole("button", { name: "FP32バリアントを削除" }));
  fireEvent.click(screen.getByRole("button", { name: "FP32バリアントの削除を確定" }));

  await vi.waitFor(() => expect(close).toHaveBeenCalledOnce());
});

it("shows the selected variant revision and disk usage", async () => {
  const card = {
    id: "model-id",
    displayName: "Irodori",
    source: "managed",
    repo: "base",
    revision: "fp32-revision",
    diskBytes: 6_400_000_000,
    verification: "verified",
    activeVariantId: "pytorch-fp32",
    installedVariants: [
      { id: "pytorch-fp32", precision: "FP32", backend: "pytorch", repo: "base", revision: "fp32-revision", diskBytes: 2 * 1024 ** 3, optimizationProfile: "pytorch-fp32" },
      { id: "mlx-fp16", precision: "FP16", backend: "mlx", repo: "mlx", revision: "fp16-revision", diskBytes: 1 * 1024 ** 3, optimizationProfile: "mlx-audio-0.5.0-fp16" },
    ],
  } as TtsAssetCard;
  const registry = { version: 3, defaultEngineId: null, defaultModelId: card.id, engines: [], models: [card], libraries: [], projectSelection: null } as TtsRegistry;
  vi.spyOn(api, "setTtsActiveVariant").mockResolvedValue(registry);
  render(<TtsModelDialog card={card} registry={registry} isDefault isScratch={false} onClose={vi.fn()} onChanged={vi.fn()} onSelectionChanged={vi.fn()} />);

  expect(screen.getByText("fp32-revision")).toBeInTheDocument();
  expect(screen.getByText("2.0 GB")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("radio", { name: "FP16" }));
  expect(screen.getByText("fp16-revision")).toBeInTheDocument();
  expect(screen.getByText("1.0 GB")).toBeInTheDocument();
  expect(screen.queryByText("6.0 GB")).not.toBeInTheDocument();
});

it("shows the active variant and its own size on the settings card", () => {
  const card = {
    id: "model-id",
    displayName: "Irodori",
    source: "managed",
    generation: "v4.1",
    diskBytes: 6_400_000_000,
    verification: "verified",
    activeVariantId: "mlx-fp16",
    installedVariants: [
      { id: "pytorch-fp32", precision: "FP32", backend: "pytorch", repo: "base", revision: "fp32", diskBytes: 2 * 1024 ** 3, optimizationProfile: "pytorch-fp32" },
      { id: "mlx-fp16", precision: "FP16", backend: "mlx", repo: "mlx", revision: "fp16", diskBytes: 1 * 1024 ** 3, optimizationProfile: "mlx-fp16" },
    ],
  } as TtsAssetCard;
  const registry = { libraries: [] } as unknown as TtsRegistry;

  render(<TtsCardContent card={card} registry={registry} isDefault />);

  expect(screen.getByText("v4.1 · FP16 · 1.0 GB")).toBeInTheDocument();
  expect(screen.queryByText(/6\.0 GB/)).not.toBeInTheDocument();
});
