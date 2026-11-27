import type { HfGgufVariant } from "../../api-llm";
import type { HfModel } from "./huggingFaceModelUi";
import { formatGb } from "../shared/formatBytes";
import { withinModelSize, formatSearchModelSize, formatModelBytes } from "./huggingFaceModelUi";

export function formatCatalogSize(model: HfModel, maxGb: number | null, selected: Set<string>): string {
  if (!model.ggufVariants) return formatSearchModelSize(model);
  const sizes = model.ggufVariants.filter((variant) => variantMatches(variant, maxGb ?? 0, selected)).map((variant) => variant.downloadSizeBytes);
  if (!sizes.length || sizes.some((size) => size <= 0)) return formatModelBytes(null);
  const min = Math.min(...sizes),
    max = Math.max(...sizes);
  return min === max ? formatModelBytes(min) : `${formatGb(min).replace(" GB", "")}–${formatModelBytes(max)}`;
}

export function variantMatches(variant: HfGgufVariant, maxGb: number, selected: Set<string>): boolean {
  const quantizations = [...selected].filter((tag) => tag.startsWith("quantization:"));
  return withinModelSize(variant.downloadSizeBytes, maxGb) && (!quantizations.length || quantizations.includes(`quantization:${variant.quantization}`));
}

export function modelMatches(model: HfModel, maxGb: number, selected: Set<string>): boolean {
  if (model.compatibility !== "gguf") return withinModelSize(model.downloadSizeBytes, maxGb);
  if (!model.ggufVariants) return ![...selected].some((tag) => tag.startsWith("quantization:")) && withinModelSize(model.downloadSizeBytes, maxGb);
  const variants = model.ggufVariants.filter((variant) => variantMatches(variant, maxGb, selected));
  const quantizations = [...selected].filter((tag) => tag.startsWith("quantization:"));
  return variants.length > 0 && quantizations.every((tag) => variants.some((variant) => tag === `quantization:${variant.quantization}`));
}

export function needsModelMetadata(model: HfModel): boolean {
  return Boolean(model.revision) && (model.downloadSizeBytes == null || (model.compatibility === "gguf" && !model.ggufVariants));
}

export function mergeModelMetadata(models: HfModel[], updates: Array<{ repoId: string; downloadSizeBytes: number | null; ggufVariants?: HfGgufVariant[] }>): HfModel[] {
  const byId = new Map(updates.map((model) => [model.repoId, model]));
  return models.map((model) => {
    const update = byId.get(model.repoId);
    if (!update) return model;
    const merged = { ...model, ...update, downloadSizeBytes: update.downloadSizeBytes ?? model.downloadSizeBytes };
    if (update.ggufVariants) {
      const values = [...new Set(update.ggufVariants.map((variant) => variant.quantization))].filter((value) => /^(?:UD-)?(?:I?Q\d(?:_[A-Z0-9]+)*|TQ\d_\d+|MXFP4|NVFP4|BF16|FP16|FP32|F16|F32)$/.test(value));
      merged.inferredTags = [...model.inferredTags.filter((tag) => tag.kind !== "quantization"), ...values.map((value) => ({ kind: "quantization" as const, value }))];
    }
    return merged;
  });
}
