// @vitest-environment jsdom
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import type { HfGgufVariant } from "../../api-llm";
import { BuiltInLlmDialog } from "./BuiltInLlmDialog";
import { mergeModelMetadata, modelMatches, variantMatches, formatCatalogSize } from "./hfGgufCatalog";
import { searchModelTags } from "./huggingFaceModelUi";

vi.mock("../shared/platform", () => ({ isWindows: () => true }));
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});
const variant = (quantization: string, bytes: number): HfGgufVariant => ({ id: quantization, quantization, files: [`${quantization}.gguf`], shardCount: 1, downloadSizeBytes: bytes });
const model = { repoId: "org/model", publisher: "org", revision: "fixed", displayName: "Model", downloads: 1, gated: false, compatibility: "gguf" as const, warning: null, downloadSizeBytes: 6e9, inferredTags: [{ kind: "quantization" as const, value: "Q4" }] };
const catalog = [variant("Q4_0", 6e9), variant("Q4_K_M", 14e9), variant("Q8_0", 20e9)];

it("does not conflate dynamic quantizations with standard variants or other repositories", () => {
  const [dynamic, standard] = mergeModelMetadata(
    [model, { ...model, repoId: "org/standard" }],
    [
      { repoId: model.repoId, downloadSizeBytes: 6e9, ggufVariants: [variant("UD-Q4_K_XL", 6e9), variant("UD-IQ1_M", 2e9)] },
      { repoId: "org/standard", downloadSizeBytes: 6e9, ggufVariants: [variant("Q4_K_M", 6e9)] },
    ],
  );
  expect(dynamic.inferredTags.map((tag) => tag.value)).toEqual(["UD-Q4_K_XL", "UD-IQ1_M"]);
  expect(standard.inferredTags.map((tag) => tag.value)).toEqual(["Q4_K_M"]);
  expect(modelMatches(dynamic, 0, new Set(["quantization:Q4_K"]))).toBe(false);
  expect(modelMatches(dynamic, 0, new Set(["quantization:IQ1_M"]))).toBe(false);
  expect(modelMatches(dynamic, 0, new Set(["quantization:UD-Q4_K_XL"]))).toBe(true);
  expect(modelMatches(standard, 0, new Set(["quantization:UD-Q4_K_XL"]))).toBe(false);
});

it("uses exact catalog tags and the size of that same variant", () => {
  const [merged] = mergeModelMetadata([model], [{ repoId: model.repoId, downloadSizeBytes: 6e9, ggufVariants: catalog }]);
  expect(merged.inferredTags.map((tag) => tag.value)).toEqual(["Q4_0", "Q4_K_M", "Q8_0"]);
  const selected = new Set(["quantization:Q4_K_M"]);
  expect(modelMatches(merged, 12, selected)).toBe(false);
  expect(modelMatches(merged, 16, selected)).toBe(true);
  expect(modelMatches(merged, 0, new Set(["quantization:Q4"]))).toBe(false);
  expect(variantMatches(catalog[0], 0, selected)).toBe(false);
  expect(modelMatches(model, 0, selected)).toBe(false);
  expect(formatCatalogSize(merged, null, selected)).toBe("14.0 GB");
  expect(formatCatalogSize(merged, null, new Set())).toBe("6.0–20.0 GB");
  expect(formatCatalogSize({ ...merged, ggufVariants: [variant("Q4", 0)] }, null, new Set())).toBe("容量不明");
  expect(searchModelTags(merged)).toEqual([]);
  expect(searchModelTags({ ...model, compatibility: "mlx" })).toEqual(model.inferredTags);
  expect(mergeModelMetadata([merged], [{ repoId: model.repoId, downloadSizeBytes: null }])[0]).toEqual(merged);
});

it("offers file-derived tags and restricts the download choices to the selected quantization", async () => {
  vi.useFakeTimers();
  vi.spyOn(api, "huggingFaceTokenStatus").mockResolvedValue({ hasToken: false });
  const search = vi.spyOn(api, "searchHuggingFace").mockResolvedValue({ models: [model] });
  const download = vi.spyOn(api, "downloadHuggingFace").mockResolvedValue({ id: "download", state: "queued" });
  vi.spyOn(api, "huggingFaceDownload").mockResolvedValue({ id: "download", state: "complete", downloadedBytes: 14e9, totalBytes: 14e9 });
  vi.spyOn(api, "huggingFaceMetadata").mockResolvedValue({ models: [{ repoId: model.repoId, downloadSizeBytes: 6e9, ggufVariants: catalog }] });
  vi.spyOn(api, "huggingFaceGgufVariants").mockResolvedValue({ repoId: model.repoId, revision: "fixed", variants: catalog });
  render(<BuiltInLlmDialog onAdded={vi.fn()} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: /Hugging Faceから探す/ }));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "検索" }));
  });
  const tags = within(screen.getByRole("group", { name: "量子化" }));
  const models = within(screen.getByRole("radiogroup", { name: "モデル" }));
  expect(models.getAllByRole("radio")).toHaveLength(1);
  expect(models.getByText("6.0–20.0 GB")).toBeInTheDocument();
  for (const candidate of catalog) expect(models.queryByText(candidate.quantization)).toBeNull();
  expect(screen.queryByRole("radiogroup", { name: "GGUF量子化" })).toBeNull();
  expect(tags.queryByRole("button", { name: "Q4" })).toBeNull();
  fireEvent.click(tags.getByRole("button", { name: "Q4_K_M" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(400);
  });
  expect(search).toHaveBeenLastCalledWith("", ["quantization:Q4_K_M"], "downloads");
  await act(async () => {
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "モデル" })).getByRole("radio"));
  });
  const choices = within(screen.getByRole("radiogroup", { name: "GGUF量子化" }));
  expect(choices.getAllByRole("radio")).toHaveLength(1);
  expect(choices.getByRole("radio", { name: /Q4_K_M/ })).toBeInTheDocument();
  expect(choices.getByText("14.0 GB")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "取得して追加" })).toBeDisabled();
  fireEvent.click(choices.getByRole("radio"));
  expect(screen.getByRole("button", { name: "取得して追加" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "12GB" }));
  expect(within(screen.getByRole("radiogroup", { name: "モデル" })).queryAllByRole("radio")).toHaveLength(0);
  expect(screen.getByRole("button", { name: "取得して追加" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "16GB" }));
  await act(async () => {
    fireEvent.click(models.getByRole("radio"));
  });
  fireEvent.click(within(screen.getByRole("radiogroup", { name: "GGUF量子化" })).getByRole("radio"));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "取得して追加" }));
  });
  expect(download).toHaveBeenCalledExactlyOnceWith(model.repoId, "Q4_K_M");
  fireEvent.click(tags.getByRole("button", { name: "Q4_K_M" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(400);
  });
  expect(tags.getByRole("button", { name: "Q4_K_M" })).toHaveAttribute("aria-pressed", "false");
  expect(models.getAllByRole("radio")).toHaveLength(1);
  expect(within(screen.getByRole("radiogroup", { name: "GGUF量子化" })).getAllByRole("radio")).toHaveLength(2);
});

it("keeps late responses from a previous model out of the selected model's download choices", async () => {
  const other = { ...model, repoId: "org/other", displayName: "Other" };
  vi.spyOn(api, "huggingFaceTokenStatus").mockResolvedValue({ hasToken: false });
  vi.spyOn(api, "searchHuggingFace").mockResolvedValue({ models: [model, other] });
  vi.spyOn(api, "huggingFaceMetadata").mockResolvedValue({ models: [] });
  type Response = Awaited<ReturnType<typeof api.huggingFaceGgufVariants>>;
  let resolveFirst!: (value: Response) => void;
  vi.spyOn(api, "huggingFaceGgufVariants")
    .mockReturnValueOnce(
      new Promise((resolve) => {
        resolveFirst = resolve;
      }),
    )
    .mockResolvedValueOnce({ repoId: other.repoId, revision: "fixed", variants: [variant("UD-Q4_K_XL", 10e9)] });
  const download = vi.spyOn(api, "downloadHuggingFace").mockResolvedValue({ id: "download", state: "queued" });
  vi.spyOn(api, "huggingFaceDownload").mockResolvedValue({ id: "download", state: "complete", downloadedBytes: 10e9, totalBytes: 10e9 });
  render(<BuiltInLlmDialog onAdded={vi.fn()} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: /Hugging Faceから探す/ }));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "検索" }));
  });
  const models = within(screen.getByRole("radiogroup", { name: "モデル" }));
  fireEvent.click(models.getByRole("radio", { name: /Model/ }));
  expect(screen.getByText("量子化を確認しています…")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "取得して追加" })).toBeDisabled();
  await act(async () => {
    fireEvent.click(models.getByRole("radio", { name: /Other/ }));
  });
  await act(async () => {
    resolveFirst({ repoId: model.repoId, revision: "fixed", variants: catalog });
  });
  const choices = within(screen.getByRole("radiogroup", { name: "GGUF量子化" }));
  expect(choices.getAllByRole("radio")).toHaveLength(1);
  expect(choices.getByRole("radio", { name: /UD-Q4_K_XL/ })).toBeChecked();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "取得して追加" }));
  });
  expect(download).toHaveBeenCalledExactlyOnceWith(other.repoId, "UD-Q4_K_XL");
});

it("keeps a model with many quantizations in one concise row and offers those quantizations after selection", async () => {
  // Labels from the reported repository; sizes are synthetic, not live model metadata.
  const labels = "BF16 Q4_0 Q4_1 Q8_0 UD-IQ1_M UD-IQ1_S UD-IQ2_S UD-IQ2_XXS UD-IQ3_S UD-IQ3_XXS UD-IQ4_XS UD-Q2_K_XL UD-Q3_K_XL UD-Q4_K_M UD-Q4_K_S UD-Q4_K_XL UD-Q5_K_M UD-Q5_K_S UD-Q5_K_XL UD-Q6_K UD-Q6_K_L UD-Q6_K_M UD-Q6_K_XL UD-Q8_K_L UD-Q8_K_XL".split(" ");
  const variants = labels.map((label, index) => variant(label, (index + 1) * 1e9));
  const reported = {
    ...model,
    repoId: "unsloth/Qwen3.8-27B-GGUF",
    displayName: "Qwen3.8-27B-GGUF",
    publisher: "unsloth",
    ggufVariants: variants,
    inferredTags: [{ kind: "family" as const, value: "Qwen 3.8" }, { kind: "parameters" as const, value: "27B" }, { kind: "compatibility" as const, value: "GGUF" }, ...labels.map((value) => ({ kind: "quantization" as const, value }))],
  };
  vi.spyOn(api, "huggingFaceTokenStatus").mockResolvedValue({ hasToken: false });
  vi.spyOn(api, "searchHuggingFace").mockResolvedValue({ models: [reported] });
  vi.spyOn(api, "huggingFaceGgufVariants").mockResolvedValue({ repoId: reported.repoId, revision: "fixed", variants });
  render(<BuiltInLlmDialog onAdded={vi.fn()} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: /Hugging Faceから探す/ }));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "検索" }));
  });
  const models = within(screen.getByRole("radiogroup", { name: "モデル" }));
  expect(models.getAllByRole("radio")).toHaveLength(1);
  expect(models.getByText("Qwen 3.8")).toBeInTheDocument();
  expect(models.getByText("27B")).toBeInTheDocument();
  expect(models.getByText("提供元: unsloth")).toBeInTheDocument();
  expect(models.getByText("GGUF")).toBeInTheDocument();
  for (const label of labels) expect(models.queryByText(label)).toBeNull();
  expect(within(screen.getByRole("group", { name: "量子化" })).getAllByRole("button")).toHaveLength(labels.length);
  expect(screen.queryByRole("radiogroup", { name: "GGUF量子化" })).toBeNull();
  await act(async () => {
    fireEvent.click(models.getByRole("radio"));
  });
  expect(within(screen.getByRole("radiogroup", { name: "GGUF量子化" })).getAllByRole("radio")).toHaveLength(labels.length);
  expect(models.getAllByRole("radio")).toHaveLength(1);
});
