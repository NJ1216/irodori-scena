import type { StudioProject } from "../../types";

export type Format = "wav" | "subtitle_txt" | "script_txt" | "srt" | "lab";
export type Naming = "sequence" | "cast" | "text" | "none";
export type Settings = {
  layout: "split" | "joined";
  formats: Format[];
  naming: Naming[];
  scriptDelimiter: string;
  quoteDialogue: boolean;
  subtitleIncludeEmoji: boolean;
};
export const STORAGE_KEY = "scena.export.settings.v1";
const defaults: Settings = {
  layout: "split",
  formats: ["wav"],
  naming: ["sequence", "cast", "text"],
  scriptDelimiter: "\t",
  quoteDialogue: false,
  subtitleIncludeEmoji: false,
};
export const formatLabels: Array<[Format, string]> = [
  ["wav", "WAV"],
  ["subtitle_txt", "字幕TXT"],
  ["script_txt", "台本TXT"],
  ["srt", "字幕SRT"],
  ["lab", "口パクLAB"],
];
export const namingLabels: Array<[Naming, string]> = [
  ["sequence", "連番"],
  ["cast", "キャスト名"],
  ["text", "セリフ"],
  ["none", "なし"],
];
const delimiters = new Set(["\t", ",", " ", "|"]);

function isFormat(value: unknown): value is Format {
  return formatLabels.some(([format]) => format === value);
}

function isNaming(value: unknown): value is Naming {
  return namingLabels.some(([naming]) => naming === value);
}

export function loadSettings(): Settings {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as Partial<Settings>;
    const savedFormats = Array.isArray(saved.formats) ? saved.formats.filter(isFormat) : defaults.formats;
    const savedNaming = Array.isArray(saved.naming) && saved.naming.length === 3 && saved.naming.every(isNaming) ? saved.naming : defaults.naming;
    const formats = savedFormats.length ? savedFormats : defaults.formats;
    const hasLab = formats.includes("lab");
    return {
      layout: hasLab ? "split" : saved.layout === "joined" || saved.layout === "split" ? saved.layout : defaults.layout,
      formats: hasLab ? Array.from(new Set([...formats, "wav"])) : formats,
      naming: savedNaming,
      scriptDelimiter: typeof saved.scriptDelimiter === "string" && delimiters.has(saved.scriptDelimiter) ? saved.scriptDelimiter : defaults.scriptDelimiter,
      quoteDialogue: saved.quoteDialogue === true,
      subtitleIncludeEmoji: import.meta.env.DEV && saved.subtitleIncludeEmoji === true,
    };
  } catch {
    return defaults;
  }
}

function cleanText(value: string) {
  return value.replace(/\p{Extended_Pictographic}(?:\uFE0F|\u200D\p{Extended_Pictographic})*/gu, "");
}

function safeName(value: string, fallback: string) {
  return (
    value
      .replace(/[\x00-\x1f/:]/g, "_")
      .trim()
      .replace(/[. ]+$/g, "") || fallback
  );
}

export function previewNames(project: StudioProject, settings: Settings) {
  const casts = new Map(project.characters.map((item) => [item.id, item.name || "キャスト"]));
  let sequence = 0;
  const bases = project.scenes
    .flatMap((scene) => scene.lines)
    .flatMap((line) => {
      if (line.enabled === false) return [];
      sequence += 1;
      if (!line.text.trim()) return [];
      const cast = (casts.get(line.characterId) ?? "キャスト").replaceAll(" ", "");
      const values: Record<Exclude<Naming, "none">, string> = {
        sequence: String(sequence).padStart(3, "0"),
        cast: safeName(cast, "キャスト"),
        text: safeName(cleanText(line.text), "セリフ"),
      };
      return [
        settings.naming
          .filter((item) => item !== "none")
          .map((item) => values[item as Exclude<Naming, "none">])
          .join("_"),
      ];
    });
  const extensions = settings.formats.filter((format) => format !== "script_txt").map((format) => (format === "subtitle_txt" ? "txt" : format));
  const samples = bases.flatMap((base) => extensions.map((extension) => `${base}.${extension}`));
  if (settings.formats.includes("script_txt")) samples.push(`${safeName(project.title, "irodori SCENA")} 台本.txt`);
  return samples;
}
