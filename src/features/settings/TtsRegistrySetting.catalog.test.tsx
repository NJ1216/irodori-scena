import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TtsCatalogItem, TtsCatalogVariant } from "../../types";
import { CatalogCardAction, VariantPanel } from "./TtsRegistrySetting";
import { QuickTooltip } from "../shared/QuickTooltip";
import { orderTtsVariantsForDisplay } from "./ttsVariantOrder";

const item = {
  id: "base@revision",
  displayName: "Irodori-TTS v4.1 Small",
  repo: "base",
  revision: "revision",
  installable: true,
  sizeBytes: 3 * 1_000_000_000,
  precision: "FP32",
} as TtsCatalogItem;

const fp16 = {
  id: "mlx-fp16",
  displayName: "FP16",
  precision: "FP16",
  backend: "mlx",
  repo: "mlx/base",
  revision: "mlx-revision",
  sizeBytes: 2 * 1_000_000_000,
  runtimeProfile: "mlx-audio-0.5.0-fp16",
  available: true,
  recommendedOrder: 1,
} as TtsCatalogVariant;

describe("TTS catalog download metadata", () => {
  afterEach(() => vi.useRealTimers());

  it("keeps download sizes available on installed Add buttons and installed variants", () => {
    vi.useFakeTimers();
    render(
      <>
        <CatalogCardAction item={item} recommended={fp16} installed={new Set([fp16.id])} busy={false} onStart={vi.fn()} onVariant={vi.fn()} />
        <VariantPanel item={item} variants={[fp16]} installed={new Set([fp16.id])} verified busy={false} onVariant={vi.fn()} onChanged={vi.fn()} />
        <QuickTooltip />
      </>,
    );
    const installed = screen.getByRole("button", { name: "導入済み" });
    expect(installed).toBeDisabled();
    fireEvent.mouseOver(installed.parentElement!);
    expect(screen.getByRole("tooltip")).toHaveTextContent("ダウンロードサイズ：2.0 GB");
    fireEvent.mouseOut(installed.parentElement!);
    const variant = screen.getByRole("button", { name: "FP16" });
    fireEvent.mouseOver(variant);
    expect(screen.getByRole("tooltip")).toHaveTextContent("ダウンロードサイズ：2.0 GB");
    fireEvent.mouseOut(variant);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(installed).not.toHaveAttribute("title");
    expect(variant).not.toHaveAttribute("title");
  });

  it("shows each variant's own download size immediately on hover and focus without native tooltips", () => {
    vi.useFakeTimers();
    const variants = [{ ...fp16, id: "pytorch-fp32", precision: "FP32", sizeBytes: 3 * 1_000_000_000 }, fp16, { ...fp16, id: "mlx-bf16", precision: "BF16", sizeBytes: 7 * 1_000_000_000 }, { ...fp16, id: "mlx-8bit", precision: "8bit", sizeBytes: 1_000_000_000 }];
    render(
      <>
        <VariantPanel item={item} variants={variants} installed={new Set()} verified={false} busy={false} onVariant={vi.fn()} onChanged={vi.fn()} />
        <QuickTooltip />
      </>,
    );
    for (const variant of variants) {
      const button = screen.getByRole("button", { name: variant.precision });
      fireEvent.mouseOver(button);
      expect(screen.getByRole("tooltip")).toHaveTextContent(`ダウンロードサイズ：${variant.sizeBytes / 1_000_000_000}.0 GB`);
      expect(button).not.toHaveAttribute("title");
      fireEvent.mouseOut(button);
      expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
      expect(button).not.toHaveAttribute("title");
      fireEvent.focusIn(button);
      expect(screen.getByRole("tooltip")).toHaveTextContent(`ダウンロードサイズ：${variant.sizeBytes / 1_000_000_000}.0 GB`);
      fireEvent.focusOut(button);
      expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    }
  });
  it("shows FP32 before FP16 and 8bit on macOS without changing the recommended variant", () => {
    const variants = [fp16, { ...fp16, id: "pytorch-fp32", precision: "FP32", recommendedOrder: 2 }, { ...fp16, id: "mlx-8bit", precision: "8bit", recommendedOrder: 3 }];

    expect(orderTtsVariantsForDisplay(variants).map((variant) => variant.precision)).toEqual(["FP32", "FP16", "8bit"]);
    expect(variants[0].id).toBe("mlx-fp16");
  });

  it("shows FP32 before the Windows quantized variants without changing recommendation metadata", () => {
    const variants = [
      { ...fp16, id: "pytorch-w8a16", precision: "W8A16", recommendedOrder: 1 },
      { ...fp16, id: "pytorch-fp32", precision: "FP32", recommendedOrder: 2 },
      { ...fp16, id: "pytorch-w8a8", precision: "W8A8", recommendedOrder: 3 },
      { ...fp16, id: "pytorch-w4a16", precision: "W4A16", recommendedOrder: 4 },
      { ...fp16, id: "pytorch-fp8-weight-only", precision: "FP8/BF16", recommendedOrder: 5 },
      { ...fp16, id: "pytorch-fp8-dynamic", precision: "FP8 Dynamic", recommendedOrder: 6 },
    ] as TtsCatalogVariant[];

    expect(orderTtsVariantsForDisplay(variants).map((variant) => variant.precision)).toEqual(["FP32", "W8A16", "W8A8", "W4A16", "FP8/BF16", "FP8 Dynamic"]);
    expect(variants.find((variant) => variant.id === "pytorch-w8a16")?.recommendedOrder).toBe(1);
  });

  it("shows the recommended variant size and precision below Add", () => {
    render(<CatalogCardAction item={item} recommended={fp16} installed={new Set()} busy={false} onStart={vi.fn()} onVariant={vi.fn()} />);

    expect(screen.getByText("2.0GB")).toBeInTheDocument();
    expect(screen.getByText("[FP16]")).toBeInTheDocument();
    expect(screen.queryByText("[FP32]")).not.toBeInTheDocument();
  });

  it("keeps FP32 metadata when no MLX variant is available", () => {
    render(<CatalogCardAction item={item} installed={new Set()} busy={false} onStart={vi.fn()} onVariant={vi.fn()} />);

    expect(screen.getByText("3.0GB")).toBeInTheDocument();
    expect(screen.getByText("[FP32]")).toBeInTheDocument();
  });

  it("shows unavailable variants disabled with their hardware reason", async () => {
    const unavailable = { ...fp16, id: "pytorch-w4a16", precision: "W4A16", backend: "pytorch", available: false, unavailableReason: "Compute Capability 8.0以上が必要です。" } as TtsCatalogVariant;
    const { VariantPanel } = await import("./TtsRegistrySetting");
    render(<VariantPanel item={item} variants={[unavailable]} installed={new Set()} verified={false} busy={false} onVariant={vi.fn()} onChanged={vi.fn()} />);
    const button = screen.getByRole("button", { name: /W4A16/ });
    expect(button).toBeDisabled();
    expect(screen.getByText("Compute Capability 8.0以上が必要です。")).toBeInTheDocument();
  });

  it("shows the macOS download sources below the FP16, FP32, and 8bit choices", async () => {
    const { VariantPanel } = await import("./TtsRegistrySetting");
    const variants = [
      { ...fp16, repo: "mlx-community/Irodori-TTS-v4.1-Small-fp16" },
      { ...fp16, id: "pytorch-fp32", precision: "FP32", backend: "pytorch", repo: "Aratako/Irodori-TTS-v4.1-Small" },
      { ...fp16, id: "mlx-8bit", precision: "8bit", repo: "mlx-community/Irodori-TTS-v4.1-Small-8bit" },
    ] as TtsCatalogVariant[];
    render(<VariantPanel item={item} variants={variants} installed={new Set()} verified={false} busy={false} onVariant={vi.fn()} onChanged={vi.fn()} />);

    expect(screen.getByText("FP32はHugging FaceのAratakoから、FP16・8bitはmlx-communityからダウンロードします。")).toBeInTheDocument();
  });
});
