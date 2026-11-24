import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, openExternal } from "../../api";
import { MainWindowFooter } from "./MainWindowFooter";
import { MemoryMeter } from "./MemoryMeter";
import { GpuMeter } from "./GpuMeter";
import { emptyGpuUtilizationState, updateGpuUtilization } from "./gpuUtilizationAverage";
import { memoryNeedsInitialFollowup, stabilizeMemorySnapshot } from "./memorySnapshotStability";
import { requestExpressionPaletteToggle } from "../script/expressionPaletteEvents";
import metadata from "../../../release-metadata.json";

vi.mock("../../api", () => ({
  openExternal: vi.fn(),
  api: {
    memorySnapshot: vi.fn().mockRejectedValue(new Error("unavailable")),
    llmSessionUsage: vi.fn().mockRejectedValue(new Error("unavailable")),
  },
}));

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("MainWindowFooter", () => {
  it("quickly follows an initial split sample until dynamic GPU values arrive", async () => {
    vi.useFakeTimers();
    const base = {
      kind: "split" as const,
      ram: { totalBytes: 100, availableBytes: 50, otherUsedBytes: 30, scenaAppBytes: 20, llmBytes: 0, ttsBytes: 0 },
      vram: { totalBytes: 80, availableBytes: null, otherUsedBytes: null, scenaAppBytes: 0, llmBytes: null, ttsBytes: null },
      acceleratorOwner: null,
      gpuUtilizationPercent: null,
      sampledAt: 1,
    };
    vi.mocked(api.memorySnapshot)
      .mockResolvedValueOnce(base)
      .mockResolvedValueOnce({ ...base, vram: { ...base.vram, availableBytes: 60 }, gpuUtilizationPercent: 25, sampledAt: 2 });

    render(<MainWindowFooter onInsertEmoji={vi.fn()} />);
    await vi.advanceTimersByTimeAsync(250);

    expect(api.memorySnapshot).toHaveBeenCalledTimes(2);
    expect(screen.getAllByText("0.0GB 空き")).toHaveLength(2);
  });

  it("only requests an initial follow-up while dynamic accelerator values are missing", () => {
    const unified = { kind: "unified" as const, totalBytes: 1, availableBytes: 1, otherUsedBytes: 0, scenaAppBytes: 0, llmBytes: 0, ttsBytes: 0, metalOwner: null, gpuUtilizationPercent: 1, sampledAt: 1 };
    expect(memoryNeedsInitialFollowup(unified)).toBe(false);
    expect(memoryNeedsInitialFollowup({ ...unified, gpuUtilizationPercent: null })).toBe(true);
  });

  it("refreshes resources every second while retaining a five-second usage cadence", async () => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    vi.mocked(api.memorySnapshot).mockResolvedValue({
      kind: "unified",
      totalBytes: 100,
      availableBytes: 50,
      otherUsedBytes: 30,
      scenaAppBytes: 20,
      llmBytes: 0,
      ttsBytes: 0,
      metalOwner: null,
      gpuUtilizationPercent: 10,
      sampledAt: 1,
    });
    vi.mocked(api.llmSessionUsage).mockRejectedValue(new Error("unavailable"));

    render(<MainWindowFooter onInsertEmoji={vi.fn()} />);
    await vi.advanceTimersByTimeAsync(0);
    expect(api.memorySnapshot).toHaveBeenCalledTimes(1);
    expect(api.llmSessionUsage).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(1_000);
    expect(api.memorySnapshot).toHaveBeenCalledTimes(2);
    expect(api.llmSessionUsage).toHaveBeenCalledTimes(1);
  });

  it("retains the last known meter fields across a partial sample", () => {
    const previous = {
      kind: "unified" as const,
      totalBytes: 100,
      availableBytes: 40,
      otherUsedBytes: 30,
      scenaAppBytes: 10,
      llmBytes: 15,
      ttsBytes: 5,
      metalOwner: "tts" as const,
      gpuUtilizationPercent: 10,
      sampledAt: 1,
    };
    const next = { ...previous, availableBytes: 35, scenaAppBytes: null, ttsBytes: null, sampledAt: 2 };
    expect(stabilizeMemorySnapshot(previous, next)).toMatchObject({
      availableBytes: 35,
      scenaAppBytes: 10,
      ttsBytes: 5,
      sampledAt: 2,
    });
  });

  it("shows LLM and Irodori-TTS as separate unified-memory segments", async () => {
    vi.mocked(api.memorySnapshot).mockResolvedValueOnce({
      kind: "unified",
      totalBytes: 100_000_000_000,
      availableBytes: 40_000_000_000,
      otherUsedBytes: 30_000_000_000,
      scenaAppBytes: 10_000_000_000,
      llmBytes: 15_000_000_000,
      ttsBytes: 5_000_000_000,
      metalOwner: "llm",
      gpuUtilizationPercent: 42,
      sampledAt: 1,
    });
    render(<MainWindowFooter onInsertEmoji={vi.fn()} />);

    const llm = await screen.findByLabelText("メモリ LLM 15.0GB");
    expect(llm).toHaveAttribute("data-tooltip", "LLM 15.0GB");
    expect(screen.getByLabelText("メモリ Irodori-TTS 5.0GB")).toHaveAttribute("data-tooltip", "Irodori-TTS 5.0GB");
    expect(screen.getByText("40.0GB 空き")).toBeInTheDocument();
    const segments = llm.closest(".unified-memory-bar")!.querySelectorAll(".memory-part");
    expect(segments).toHaveLength(5);
    expect(segments[2]).toHaveStyle({ width: "15%" });
    expect(segments[3]).toHaveStyle({ width: "5%" });
  });
});

describe("MainWindowFooter interactions", () => {
  it("toggles the visible palette with F3 requests without changing its pinned state", async () => {
    render(<MainWindowFooter onInsertEmoji={vi.fn()} />);
    const menu = screen.getByLabelText("表情パレットメニュー");
    const pin = screen.getByRole("button", { name: "表情パレットをピン留め" });

    act(() => requestExpressionPaletteToggle());
    expect(menu.closest(".main-window-expression-menu")).toHaveClass("is-keyboard-open");
    await userEvent.click(pin);
    expect(pin).toHaveAttribute("aria-pressed", "true");

    act(() => requestExpressionPaletteToggle());
    expect(menu.closest(".main-window-expression-menu")).toHaveClass("is-keyboard-closed", "is-pinned");
    expect(pin).toHaveAttribute("aria-pressed", "true");
    act(() => requestExpressionPaletteToggle());
    expect(menu.closest(".main-window-expression-menu")).toHaveClass("is-keyboard-open", "is-pinned");
  });

  it("restores hover opening after F3 hides the palette", async () => {
    render(<MainWindowFooter onInsertEmoji={vi.fn()} />);
    const trigger = screen.getByRole("button", { name: "表情パレット" });
    const expression = trigger.closest(".main-window-expression-menu")!;
    act(() => requestExpressionPaletteToggle());
    act(() => requestExpressionPaletteToggle());
    expect(expression).toHaveClass("is-keyboard-closed");

    await userEvent.hover(trigger);

    expect(expression).not.toHaveClass("is-keyboard-closed");
  });

  it("shows no modifier icon beside the shortcut label on Windows", () => {
    vi.stubGlobal("navigator", { platform: "Win32" });
    render(<MainWindowFooter onInsertEmoji={vi.fn()} />);

    expect(screen.getByRole("button", { name: "ショートカット" })).toHaveTextContent(/^ショートカット$/);
    expect(screen.queryByText("Ctrl")).not.toBeInTheDocument();
  });
});

describe("MainWindowFooter meters and menu", () => {
  it("maps a split-memory snapshot onto the existing memory and GPU-memory meters", async () => {
    const breakdown = {
      totalBytes: 1000,
      availableBytes: 400,
      otherUsedBytes: 300,
      scenaAppBytes: 100,
      llmBytes: 150,
      ttsBytes: 50,
    };
    vi.mocked(api.memorySnapshot).mockResolvedValueOnce({
      kind: "split",
      ram: breakdown,
      vram: { ...breakdown, llmBytes: 250, availableBytes: 300 },
      acceleratorOwner: "llm",
      gpuUtilizationPercent: 42,
      sampledAt: 1,
    });
    render(<MainWindowFooter onInsertEmoji={vi.fn()} />);

    const ramLlm = await screen.findByLabelText("メモリ LLM 0.0GB");
    expect(ramLlm).toHaveAttribute("data-tooltip", "LLM 0.0GB");
    expect(screen.getByLabelText("GPUメモリ LLM 0.0GB")).toHaveAttribute("data-tooltip", "LLM 0.0GB");
    expect(document.querySelectorAll(".unified-memory-bar")).toHaveLength(1);
    expect(screen.getByRole("meter", { name: "NVIDIA GPUメモリ使用量" })).toBeInTheDocument();
  });

  it("omits zero and unavailable segments and overlays a positive tiny SCENA segment at 3px", () => {
    render(
      <MemoryMeter
        memory={{
          kind: "unified",
          totalBytes: 100_000_000_000,
          otherUsedBytes: 10_000_000_000,
          scenaAppBytes: 1,
          llmBytes: 0,
          ttsBytes: null,
          availableBytes: 90_000_000_000,
          metalOwner: null,
          gpuUtilizationPercent: null,
          sampledAt: 1,
        }}
      />,
    );

    const scena = screen.getByLabelText("メモリ SCENA本体 0.0GB");
    expect(scena).toHaveStyle({ left: "10%" });
    expect(scena.style.width).toMatch(/^max\(.+%, 3px\)$/);
    expect(screen.queryByLabelText(/メモリ LLM/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/メモリ Irodori-TTS/)).not.toBeInTheDocument();
    expect(document.querySelectorAll(".memory-part-hit")).toHaveLength(3);
  });

  it("holds the peak of valid GPU samples from the last three seconds", () => {
    const first = updateGpuUtilization(emptyGpuUtilizationState, 10, 1000);
    const second = updateGpuUtilization(first, 20, 2000);
    const third = updateGpuUtilization(second, 30, 3000);
    expect(third.displayedPercent).toBe(30);
    const afterGap = updateGpuUtilization(third, 50, 7001);
    expect(afterGap.samples).toHaveLength(1);
    expect(afterGap.displayedPercent).toBe(50);
  });

  it("keeps the last GPU display across a missing sample and starts unavailable", () => {
    expect(updateGpuUtilization(emptyGpuUtilizationState, null, 1000).displayedPercent).toBeNull();
    const measured = updateGpuUtilization(emptyGpuUtilizationState, 24, 1000);
    expect(updateGpuUtilization(measured, null, 2000).displayedPercent).toBe(24);
  });

  it("renders the GPU value, width, meter semantics, and shared peak tooltip", () => {
    render(<GpuMeter percent={41.6} />);
    expect(screen.getByRole("img", { name: "GPU使用率" })).toHaveAttribute("data-tooltip", "GPU使用率");
    const meter = screen.getByRole("meter", { name: "GPU使用率（1秒ごとに取得、直近3秒のピーク）" });
    expect(meter).toHaveAttribute("aria-valuenow", "42");
    expect(meter.querySelector("i")).toHaveStyle({ width: "42%" });
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(meter.closest(".gpu-meter")).toHaveAttribute("data-tooltip", "GPU使用率（1秒ごとに取得、直近3秒のピーク）");
  });

  it("shows the three right-side menu mock items and reports selection", async () => {
    vi.mocked(api.memorySnapshot).mockRejectedValueOnce(new Error("unavailable"));
    const onInsertEmoji = vi.fn();
    render(<MainWindowFooter onInsertEmoji={onInsertEmoji} />);

    expect(screen.getByRole("navigation", { name: "アプリケーションメニュー" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "メモリ" })).toHaveAttribute("data-tooltip", "メモリ");
    expect(screen.getByRole("button", { name: "表情パレット" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ショートカット" })).toBeInTheDocument();
    expect(screen.getByLabelText("表情パレットメニュー").querySelectorAll(".emoji-palette button")).toHaveLength(45);
    expect(screen.getByLabelText("ショートカットメニュー")).toContainElement(screen.getByRole("region", { name: "ショートカット" }));
    expect(screen.getByRole("button", { name: "バージョン情報" })).toHaveTextContent("ⓘ");
    expect(screen.getByLabelText("バージョン情報メニュー")).toHaveTextContent("本体 Version");
    expect(screen.getByLabelText("バージョン情報メニュー")).toHaveTextContent(`v${metadata.version}`);
    const authorLink = screen.getByRole("link", { name: "NJ" });
    const versionLink = screen.getByRole("link", { name: `v${metadata.version}` });
    expect(authorLink).toHaveAttribute("href", "https://github.com/NJ1216");
    expect(versionLink).toHaveAttribute("href", "https://github.com/NJ1216/irodori-scena");
    await userEvent.click(authorLink);
    await userEvent.click(versionLink);
    expect(openExternal).toHaveBeenNthCalledWith(1, "https://github.com/NJ1216");
    expect(openExternal).toHaveBeenNthCalledWith(2, "https://github.com/NJ1216/irodori-scena");

    const pin = screen.getByRole("button", { name: "表情パレットをピン留め" });
    await userEvent.click(pin);
    expect(pin).toHaveAttribute("aria-pressed", "true");

    const firstEmoji = screen.getByLabelText("表情パレットメニュー").querySelector<HTMLButtonElement>(".emoji-palette button");
    await userEvent.click(firstEmoji!);
    expect(onInsertEmoji).toHaveBeenCalledWith("👂");
  });

  it("keeps the active text editor focused through palette, pin, and emoji clicks", async () => {
    const onInsertEmoji = vi.fn();
    render(
      <>
        <div contentEditable role="textbox" aria-label="台詞" />
        <MainWindowFooter onInsertEmoji={onInsertEmoji} />
      </>,
    );
    const editor = screen.getByRole("textbox", { name: "台詞" });
    editor.focus();

    await userEvent.click(screen.getByRole("button", { name: "表情パレット" }));
    expect(editor).toHaveFocus();
    await userEvent.click(screen.getByRole("button", { name: "表情パレットをピン留め" }));
    expect(editor).toHaveFocus();
    const emoji = screen.getByLabelText("表情パレットメニュー").querySelector<HTMLButtonElement>(".emoji-palette button");
    await userEvent.click(emoji!);
    expect(editor).toHaveFocus();
    expect(onInsertEmoji).toHaveBeenCalledWith("👂");
  });
});
