import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GpuMemoryMeter } from "./GpuMemoryMeter";

describe("GpuMemoryMeter", () => {
  it("renders GPU memory as an independent horizontal meter", () => {
    const { rerender } = render(<GpuMemoryMeter used={6_000_000_000} total={12_000_000_000} other={1_000_000_000} llm={1_000_000_000} tts={4_000_000_000} />);
    const meter = screen.getByRole("meter", { name: "NVIDIA GPUメモリ使用量" });
    expect(meter).toHaveAttribute("aria-valuenow", "6000000000");
    expect(meter.querySelectorAll(".gpu-memory-track > i")).toHaveLength(4);
    expect(meter.querySelector(".gpu-memory-track")).toBeInTheDocument();
    expect(meter.querySelector(".memory-part-3")).toHaveStyle({ width: "33.33333333333333%" });
    expect(screen.getByLabelText("GPUメモリ Irodori-TTS 4.0GB")).toHaveAttribute("data-tooltip", "Irodori-TTS 4.0GB");
    expect(screen.getByLabelText("GPUメモリ その他 1.0GB")).toHaveAttribute("data-tooltip", "その他 1.0GB");
    expect(screen.getByRole("img", { name: "GPUメモリ" })).toHaveAttribute("data-tooltip", "GPUメモリ");
    expect(screen.getByText("6.0GB 空き")).toBeInTheDocument();
    expect(meter.closest(".gpu-memory-meter")).not.toHaveAttribute("data-tooltip");

    rerender(<GpuMemoryMeter used={null} total={12_000_000_000} />);
    expect(screen.getByRole("meter", { name: "NVIDIA GPUメモリ使用量" })).not.toHaveAttribute("aria-valuenow");
    expect(screen.getByText("— 空き")).toBeInTheDocument();

    rerender(<GpuMemoryMeter used={null} total={null} />);
    expect(screen.queryByRole("meter", { name: "NVIDIA GPUメモリ使用量" })).not.toBeInTheDocument();
  });
});
