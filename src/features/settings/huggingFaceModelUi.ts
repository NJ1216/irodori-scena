import { api } from "../../api";

export type HfModel = Awaited<ReturnType<typeof api.searchHuggingFace>>["models"][number];
type ModelTag = HfModel["inferredTags"][number];
export type HfFilterKind = ModelTag["kind"] | "publisher";

export const MODEL_SIZE_LIMITS = [8, 12, 16, 24, 48, 96, 128] as const;
export type HfSearchOrder = "downloads" | "likes" | "name" | null;
export const HF_SEARCH_ORDERS = [
  { value: "downloads", label: "DL順" },
  { value: "likes", label: "人気順" },
  { value: "name", label: "名前順" },
] as const;

export function searchOrderOptions(order: HfSearchOrder, submitted: boolean) {
  const selected = submitted ? "downloads" : order;
  return { selected, request: selected ?? "default" } as const;
}

export function formatSearchModelSize(model: HfModel): string {
  return formatModelBytes(model.downloadSizeBytes, Boolean(model.revision));
}

export function withinModelSize(size: number | null | undefined, maxGb: number): boolean {
  return maxGb === 0 || (typeof size === "number" && Number.isFinite(size) && size > 0 && size <= maxGb * 1_000_000_000);
}

export function visibleModelTags<T extends ModelTag>(tags: T[]): T[] {
  return tags.filter((tag) => !(tag.kind === "compatibility" && tag.value.toLocaleUpperCase() === "MLX"));
}

export function searchModelTags(model: HfModel): ModelTag[] {
  return visibleModelTags(model.inferredTags).filter((tag) => model.compatibility !== "gguf" || tag.kind !== "quantization");
}

export function formatModelBytes(bytes: number | null | undefined, pending = false): string {
  if (bytes == null) return pending ? "計算中…" : "容量不明";
  return `${(bytes / 1_000_000_000).toFixed(1)} GB`;
}

export function formatDownloadSpeed(bytesPerSecond: number): string {
  if (!Number.isFinite(bytesPerSecond) || bytesPerSecond <= 0) return "速度を計測中";
  const units = [
    [1_000_000_000, "GB"],
    [1_000_000, "MB"],
    [1_000, "KB"],
  ] as const;
  for (const [scale, unit] of units) {
    if (bytesPerSecond >= scale) return `${(bytesPerSecond / scale).toFixed(1)} ${unit}/秒`;
  }
  return bytesPerSecond < 1 ? "1 B/秒未満" : `${Math.round(bytesPerSecond)} B/秒`;
}

export function availableHfTagValues(models: HfModel[], selected: Set<string>, kind: HfFilterKind): string[] {
  const selectedValues = [...selected].filter((key) => key.startsWith(`${kind}:`)).map((key) => key.slice(kind.length + 1));
  const values =
    kind === "publisher"
      ? models.map((model) => model.publisher).filter(Boolean)
      : models.flatMap((model) =>
          visibleModelTags(model.inferredTags)
            .filter((tag) => tag.kind === kind)
            .map((tag) => tag.value),
        );
  return [...new Set([...values, ...selectedValues])].sort((a, b) => compareHfTagValues(kind, a, b));
}

function tagMagnitude(kind: HfFilterKind, value: string): number | null {
  if (kind === "parameters") {
    const match = /^(\d+(?:\.\d+)?)([BT])$/i.exec(value);
    return match ? Number(match[1]) * (match[2].toUpperCase() === "T" ? 1000 : 1) : null;
  }
  if (kind === "quantization") {
    const match = /(\d+(?:\.\d+)?)/.exec(value);
    return match ? Number(match[1]) : null;
  }
  return null;
}

export function compareHfTagValues(kind: HfFilterKind, a: string, b: string): number {
  const aMagnitude = tagMagnitude(kind, a);
  const bMagnitude = tagMagnitude(kind, b);
  if (aMagnitude != null || bMagnitude != null) return (bMagnitude ?? -1) - (aMagnitude ?? -1) || a.localeCompare(b, undefined, { numeric: true });
  return a.localeCompare(b, undefined, { numeric: true });
}
