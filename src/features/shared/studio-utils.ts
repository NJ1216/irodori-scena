import type { Character, CharacterProfile, DialogueLine, QualityPreset, StudioProject } from "../../types";
import { cueSelectedDuration, effectiveUnitStarts, sceneDialogueCues } from "../script/dialogueCues";

export const qualityLabel: Record<QualityPreset, string> = {
  turbo: "高速 · Sway 8",
  fast: "バランス · Sway 16",
  quality: "高品質 · Linear 40",
};

export const LINE_INSERT_REVEAL_DELAY_MS = 500;
export const NOTEBOOK_RULE_HEIGHT = 28;
export const IRODORI_EMOJI_PALETTE = [
  ["👂", "囁き・耳元の音"],
  ["😮‍💨", "吐息・溜息"],
  ["⏸️", "間・沈黙"],
  ["🤭", "くすくす笑い"],
  ["🥵", "喘ぎ・うめき"],
  ["📢", "エコー・リバーブ"],
  ["😏", "からかう・甘える"],
  ["🥺", "震え声・自信なさげ"],
  ["🌬️", "息切れ・荒い息"],
  ["😮", "息をのむ"],
  ["👅", "舐める・水音"],
  ["💋", "リップノイズ"],
  ["🫶", "優しく・Tenderly"],
  ["😭", "泣き声・嗚咽"],
  ["😱", "悲鳴・絶叫"],
  ["😪", "眠そう・気だるげ"],
  ["😴", "寝言・いびき"],
  ["⏩", "早口・一気に"],
  ["📞", "電話越し"],
  ["🐢", "ゆっくり"],
  ["🥤", "飲み込む・唾を飲む"],
  ["🤧", "咳・鼻すすり"],
  ["😒", "舌打ち"],
  ["😰", "慌てる・どもり"],
  ["😆", "喜び"],
  ["💥", "勢いよく"],
  ["😠", "怒り・不満"],
  ["😲", "驚き"],
  ["🥱", "あくび"],
  ["😖", "苦しげ"],
  ["😟", "心配・不安"],
  ["🫣", "照れ"],
  ["🙄", "呆れ"],
  ["😊", "楽しげ"],
  ["😎", "得意げ"],
  ["👌", "相槌"],
  ["🙏", "懇願"],
  ["🥴", "酔う"],
  ["🎵", "鼻歌"],
  ["🤐", "口を塞ぐ"],
  ["😌", "安堵"],
  ["🤔", "疑問"],
  ["💪", "力強く"],
  ["👃", "嗅ぐ音"],
  ["📖", "朗読"],
] as const;

export function nextId(prefix: string) {
  return `${prefix}_${crypto.randomUUID().slice(0, 12)}`;
}

export function formatDuration(seconds: number) {
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  return hours ? `${hours}時間${minutes}分${remainder}秒` : minutes ? `${minutes}分${remainder}秒` : `${remainder}秒`;
}

export function formatElapsedClock(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60);
  return `${minutes}:${remainder.toString().padStart(2, "0")}`;
}

export function formatTakeSeconds(seconds: number | undefined) {
  if (seconds === undefined || !Number.isFinite(seconds)) return "—";
  return seconds >= 60 ? formatDuration(seconds) : `${seconds.toFixed(1)}秒`;
}

/**
 * Returns the playback duration of all spoken lines, or undefined until every
 * spoken line has a selected take with a known duration.
 */
export function projectPlaybackDurationSeconds(project: Pick<StudioProject, "scenes" | "settings">) {
  const cues = project.scenes.flatMap((scene) => sceneDialogueCues(scene).map((cue) => ({ ...cue, lines: cue.lines.filter((line) => line.enabled !== false && line.text.trim() && line.characterId) }))).filter((cue) => cue.lines.length);
  if (!cues.length) return 0;

  const durations: number[] = [];
  const gaps: number[] = [];
  for (const cue of cues) {
    const duration = cueSelectedDuration(cue);
    if (duration === undefined) return undefined;
    durations.push(duration);
    gaps.push(cue.lines[0].gapSeconds ?? project.settings.lineGap ?? 0.7);
  }
  const { starts } = effectiveUnitStarts(durations, gaps);
  const total = Math.max(...starts.map((start, index) => start + durations[index]));
  return Number.isFinite(total) ? total : undefined;
}

export function formatProjectPlaybackDuration(seconds: number) {
  const roundedSeconds = Math.max(0, Math.round(seconds));
  const hours = Math.floor(roundedSeconds / 3600);
  const minutes = Math.floor((roundedSeconds % 3600) / 60);
  const remainder = roundedSeconds % 60;
  return `${hours ? `${hours}時間` : ""}${minutes}分${remainder}秒`;
}

export const emptyCharacterProfile = (): CharacterProfile => ({});
export const listText = (values: string[] | undefined) => (values ?? []).join("、");
export const listValues = (value: string) =>
  value
    .split(/[、,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 8);

export const applyCharacterProfileSuggestion = (current: CharacterProfile, suggestion: CharacterProfile): CharacterProfile => {
  const next: CharacterProfile = { ...current };
  for (const [key, value] of Object.entries(suggestion) as Array<[keyof CharacterProfile, CharacterProfile[keyof CharacterProfile]]>) {
    if (!value) continue;
    if (key !== "castRelations") {
      (next as Record<string, unknown>)[key] = value;
      continue;
    }
    const relations = { ...(current.castRelations ?? {}) };
    for (const [characterId, proposed] of Object.entries(value as NonNullable<CharacterProfile["castRelations"]>)) {
      const existing = relations[characterId] ?? {};
      relations[characterId] = {
        address: proposed.address?.trim() ? proposed.address : existing.address,
        relationship: proposed.relationship?.trim() ? proposed.relationship : existing.relationship,
      };
    }
    next.castRelations = relations;
  }
  return next;
};

export const displayNameAfterProfileSuggestion = (currentName: string, profile: CharacterProfile): string => {
  if (currentName.trim()) return currentName;
  return profile.aliases?.find((alias) => alias.trim())?.trim() ?? currentName;
};

export const avatarImageUrl = (url: string | undefined, version?: number) => {
  if (!url || url.startsWith("data:") || version === undefined) return url ?? "";
  return `${url}${url.includes("?") ? "&" : "?"}avatar=${version}`;
};

export const sceneLabel = (index: number) => {
  if (index < 26) return String.fromCharCode(65 + index);
  const suffixIndex = index - 26;
  const upperPrefix = (value: number): string => (value < 26 ? String.fromCharCode(65 + value) : upperPrefix(Math.floor(value / 26) - 1) + String.fromCharCode(65 + (value % 26)));
  return `${upperPrefix(Math.floor(suffixIndex / 26))}${String.fromCharCode(97 + (suffixIndex % 26))}`;
};

/** Creates a portable filename for one line's selected WAV take. */
export function lineTakeFileName(lineNumber: number, text: string) {
  const spokenText = text
    .trim()
    .replace(/\s+/g, " ")
    .replace(/[\p{Extended_Pictographic}\u200D\uFE0F]/gu, "")
    .replace(/[\\/:*?"<>|!\u0000-\u001f]+/g, "_")
    .trim();
  const number = String(lineNumber).padStart(3, "0");
  return `${number}_${spokenText || "セリフ"}.wav`;
}

export const characterSettingEntries = (character: Character): Array<[string, string]> => {
  const details = character.profileDetails ?? {};
  const entries: Array<[string, string]> = [];
  const add = (label: string, value: string | string[] | undefined) => {
    const text = Array.isArray(value) ? listText(value) : value?.trim();
    if (text) entries.push([label, text]);
  };
  add("氏名", [details.familyName, details.givenName].filter(Boolean).join(" "));
  add("氏名（ふりがな）", [details.familyNameKana, details.givenNameKana].filter(Boolean).join(" "));
  add("愛称", details.aliases);
  add("年齢", details.age);
  add("血液型", details.bloodType);
  add("誕生日", details.birthDate);
  add("出身地", details.birthplace);
  add("居住地", details.residence);
  add("性別", details.gender);
  add("職業", details.role);
  add("一人称", details.firstPerson);
  add("二人称", details.secondPerson);
  add("通常の呼び方", [details.defaultAddressBasis, details.defaultHonorific].filter(Boolean).join("＋"));
  add("特技", details.skills);
  add("趣味", details.hobbies);
  add("好きなもの", details.likes);
  add("苦手なもの", details.dislikes);
  add("性格", details.personality);
  add("話し方・口調", details.speechStyle);
  add("背景・来歴", details.background);
  add("その他の人間関係", details.otherRelationships);
  add("自由メモ", character.profile);
  return entries.length ? entries : [["設定", "キャラクター設定はまだありません"]];
};

const compactCharacterSettingLabels = new Set(["氏名", "氏名（ふりがな）", "愛称", "年齢", "血液型", "誕生日", "出身地", "居住地", "性別", "職業", "一人称", "二人称", "通常の呼び方", "通常の二人称", "通常の話し方"]);
export const isCompactCharacterSetting = ([label, value]: [string, string]) => compactCharacterSettingLabels.has(label) && Boolean(value);
export const compactCharacterSettingWidthClass = (value: string) => {
  const length = Array.from(value).length;
  if (length >= 22) return "is-extra-wide";
  if (length >= 14) return "is-wide";
  return undefined;
};

const NOTEBOOK_DETAIL_PAGE_LINES = 21;
const NOTEBOOK_CHARS_PER_LINE = 30;
const estimatedNotebookLines = (value: string) => value.split("\n").reduce((total, line) => total + Math.max(1, Math.ceil(line.length / NOTEBOOK_CHARS_PER_LINE)), 0);
export const paginateNotebookDetails = (entries: Array<[string, string]>): Array<Array<[string, string]>> => {
  const pages: Array<Array<[string, string]>> = [];
  let page: Array<[string, string]> = [];
  let usedLines = 0;
  const finishPage = () => {
    if (page.length) pages.push(page);
    page = [];
    usedLines = 0;
  };
  for (const [label, value] of entries) {
    let remainder = value;
    let continuation = false;
    while (remainder) {
      const remainingLines = Math.max(1, NOTEBOOK_DETAIL_PAGE_LINES - usedLines - 1);
      const maxChars = remainingLines * NOTEBOOK_CHARS_PER_LINE;
      const chunk = remainder.slice(0, maxChars);
      const lines = 1 + estimatedNotebookLines(chunk);
      if (page.length && usedLines + lines > NOTEBOOK_DETAIL_PAGE_LINES) {
        finishPage();
        continue;
      }
      page.push([continuation ? `${label}（続き）` : label, chunk]);
      usedLines += lines;
      remainder = remainder.slice(chunk.length);
      continuation = true;
      if (remainder) finishPage();
    }
  }
  finishPage();
  return pages.length ? pages : [[]];
};

export function selectedTake(line: DialogueLine) {
  return line.takes.find((take) => take.id === line.selectedTakeId);
}

export { confirmDestructiveAction } from "./destructiveConfirmation";

export async function downloadWav(url: string, fileName?: string) {
  const resolvedFileName = fileName || "irodori-scena.wav";
  if ((globalThis as { isTauri?: boolean }).isTauri === true) {
    const { downloadApiFile } = await import("../../api");
    return downloadApiFile(url, resolvedFileName);
  }
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = resolvedFileName;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
}
