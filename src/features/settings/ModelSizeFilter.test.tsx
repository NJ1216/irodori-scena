// @vitest-environment jsdom
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import { BuiltInLlmDialog } from "./BuiltInLlmDialog";
import { MODEL_SIZE_LIMITS, withinModelSize } from "./huggingFaceModelUi";

vi.mock("../shared/platform", () => ({ isWindows: () => true }));
afterEach(() => vi.restoreAllMocks());

it.each(MODEL_SIZE_LIMITS)("includes exactly %s GB and rejects oversized or unknown models", (limit) => {
  expect(withinModelSize(limit * 1e9, limit)).toBe(true);
  expect(withinModelSize(limit * 1e9 + 1, limit)).toBe(false);
  for (const unknown of [null, undefined, 0, NaN]) expect(withinModelSize(unknown, limit)).toBe(false);
  expect(withinModelSize(null, 0)).toBe(true);
});

it("filters search results and quantizations, clearing an oversized selection", async () => {
  vi.spyOn(api, "huggingFaceTokenStatus").mockResolvedValue({ hasToken: false });
  const model = { repoId: "org/small", publisher: "org", revision: "fixed", displayName: "Small", downloads: 1, gated: false, compatibility: "gguf" as const, warning: null, downloadSizeBytes: 7e9, inferredTags: [] };
  vi.spyOn(api, "searchHuggingFace").mockResolvedValue({ models: [model, { ...model, repoId: "org/large", displayName: "Large", downloadSizeBytes: 15e9 }, { ...model, repoId: "org/unknown", displayName: "Unknown", downloadSizeBytes: null }] });
  vi.spyOn(api, "huggingFaceMetadata").mockResolvedValue({ models: [{ repoId: "org/unknown", downloadSizeBytes: null }] });
  vi.spyOn(api, "huggingFaceGgufVariants").mockResolvedValue({
    repoId: model.repoId,
    revision: "fixed",
    variants: [
      { id: "Q4", quantization: "Q4", files: ["Q4.gguf"], shardCount: 1, downloadSizeBytes: 7e9 },
      { id: "Q8", quantization: "Q8", files: ["Q8.gguf"], shardCount: 1, downloadSizeBytes: 20e9 },
    ],
  });
  render(<BuiltInLlmDialog onAdded={vi.fn()} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: /Hugging Faceから探す/ }));
  expect(screen.queryByRole("group", { name: "容量" })).toBeNull();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "検索" }));
  });
  const models = within(screen.getByRole("radiogroup", { name: "モデル" }));
  expect(models.getAllByRole("radio")).toHaveLength(3);
  await act(async () => {
    fireEvent.click(models.getByRole("radio", { name: /Small/ }));
  });
  fireEvent.click(screen.getByRole("radio", { name: /Q8/ }));
  expect(screen.getByRole("button", { name: "取得して追加" })).toBeEnabled();
  const capacityRow = screen.getByRole("group", { name: "容量" });
  expect(capacityRow.previousElementSibling).toHaveAttribute("aria-label", "提供元");
  const capacity = within(capacityRow);
  expect(screen.queryByRole("combobox")).toBeNull();
  fireEvent.click(capacity.getByRole("button", { name: "16GB" }));
  fireEvent.click(capacity.getByRole("button", { name: "8GB" }));
  expect(capacity.getAllByRole("button", { pressed: true })).toHaveLength(1);
  expect(capacity.getByRole("button", { name: "8GB" })).toHaveAttribute("aria-pressed", "true");
  expect(models.getAllByRole("radio")).toHaveLength(1);
  expect(screen.queryByRole("radio", { name: /Q8/ })).toBeNull();
  expect(screen.getByRole("button", { name: "取得して追加" })).toBeDisabled();
  fireEvent.click(screen.getByRole("radio", { name: /Q4/ }));
  expect(screen.getByRole("button", { name: "取得して追加" })).toBeEnabled();
  fireEvent.click(capacity.getByRole("button", { name: "無制限" }));
  expect(models.getAllByRole("radio")).toHaveLength(3);
  fireEvent.click(capacity.getByRole("button", { name: "無制限" }));
  expect(capacity.queryAllByRole("button", { pressed: true })).toHaveLength(0);
  fireEvent.click(capacity.getByRole("button", { name: "8GB" }));
  expect(models.getAllByRole("radio")).toHaveLength(1);
  fireEvent.click(capacity.getByRole("button", { name: "8GB" }));
  expect(capacity.queryAllByRole("button", { pressed: true })).toHaveLength(0);
  expect(models.getAllByRole("radio")).toHaveLength(3);
  fireEvent.click(capacity.getByRole("button", { name: "12GB" }));
  fireEvent.click(screen.getByRole("button", { name: "すべて解除" }));
  expect(capacity.queryAllByRole("button", { pressed: true })).toHaveLength(0);
  expect(models.getAllByRole("radio")).toHaveLength(3);
});
