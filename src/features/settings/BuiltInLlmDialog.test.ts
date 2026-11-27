import { describe, expect, it } from "vitest";
import { availableHfTagValues, compareHfTagValues, formatDownloadSpeed, formatModelBytes, visibleModelTags } from "./huggingFaceModelUi";
import { visibleEndpointUrl } from "./llmCardPresentation";

const model = {
  repoId: "org/model",
  publisher: "org",
  revision: "abc",
  displayName: "model",
  downloads: 1,
  gated: false,
  compatibility: "mlx" as const,
  warning: null,
  downloadSizeBytes: 12 * 1_000_000_000,
  inferredTags: [
    { kind: "family" as const, value: "model" },
    { kind: "parameters" as const, value: "8B" },
    { kind: "quantization" as const, value: "Q4" },
    { kind: "purpose" as const, value: "Instruct" },
    { kind: "compatibility" as const, value: "MLX" },
    { kind: "compatibility" as const, value: "MTP対応" },
  ],
};

describe("Hugging Face model presentation", () => {
  it("does not expose the internal SCENA endpoint marker", () => {
    expect(
      visibleEndpointUrl({
        id: "local",
        provider: "scena-local",
        displayName: "SCENA",
        baseUrl: "http://scena.local/v1",
        hasCredential: false,
      }),
    ).toBe("");
    expect(
      visibleEndpointUrl({
        id: "ollama",
        provider: "ollama",
        displayName: "Ollama",
        baseUrl: "http://127.0.0.1:11434/v1",
        hasCredential: false,
      }),
    ).toBe("http://127.0.0.1:11434/v1");
  });
  it("formats repository sizes in decimal GB", () => {
    expect(formatModelBytes(6_800_000_000)).toBe("6.8 GB");
    expect(formatModelBytes(null)).toBe("容量不明");
    expect(formatModelBytes(null, true)).toBe("計算中…");
  });

  it.each([
    [10_000_000, "10.0 MB/秒"],
    [400_000, "400.0 KB/秒"],
    [250, "250 B/秒"],
    [0.1, "1 B/秒未満"],
    [1_000, "1.0 KB/秒"],
    [1_000_000, "1.0 MB/秒"],
    [1_000_000_000, "1.0 GB/秒"],
    [0, "速度を計測中"],
    [Number.NaN, "速度を計測中"],
  ])("shows a readable download speed for %s bytes/sec", (speed, expected) => {
    expect(formatDownloadSpeed(speed)).toBe(expected);
  });

  it("hides the redundant MLX platform marker from variant tags", () => {
    expect(visibleModelTags([...model.inferredTags, { kind: "compatibility", value: "MLX" }])).not.toContainEqual({
      kind: "compatibility",
      value: "MLX",
    });
  });

  it("derives facets from each new search result while retaining selected tags", () => {
    const another = {
      ...model,
      repoId: "org/other",
      inferredTags: [
        { kind: "family" as const, value: "other" },
        { kind: "parameters" as const, value: "4B" },
        { kind: "quantization" as const, value: "Q8" },
        { kind: "compatibility" as const, value: "MLX" },
      ],
    };
    const selected = new Set(["family:model"]);
    expect(availableHfTagValues([model, another], selected, "parameters")).toEqual(["8B", "4B"]);
    expect(availableHfTagValues([model, another], selected, "quantization")).toEqual(["Q8", "Q4"]);
    expect(availableHfTagValues([another], selected, "family")).toEqual(["model", "other"]);
  });

  it("lists and filters repository publishers", () => {
    const another = { ...model, repoId: "mlx-community/other", publisher: "mlx-community" };
    expect(availableHfTagValues([model, another], new Set(), "publisher")).toEqual(["mlx-community", "org"]);
    expect(availableHfTagValues([model, another], new Set(["publisher:mlx-community"]), "publisher")).toEqual(["mlx-community", "org"]);
  });

  it("sorts parameter sizes and quantization bits from largest to smallest", () => {
    expect(["1.5B", "120B", "12B", "1T", "31B"].sort((a, b) => compareHfTagValues("parameters", a, b))).toEqual(["1T", "120B", "31B", "12B", "1.5B"]);
    expect(["4bit", "BF16", "Q8", "6bit", "GPTQ"].sort((a, b) => compareHfTagValues("quantization", a, b))).toEqual(["BF16", "Q8", "6bit", "4bit", "GPTQ"]);
  });
});
