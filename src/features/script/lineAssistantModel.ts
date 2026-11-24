import type { LlmConnection, StudioProject } from "../../types";
import { type LineAssistantTarget } from "../studio/types";
import type { DraftPerformanceSettings } from "../studio/types";
import { draftCastSettingsRequest } from "../draft/draftCastSettings";
import { minimumLinesForSimultaneousSpeech, explicitlyRequestsSimultaneousSpeech } from "./scriptAssistantIntent";
import type { TargetKind } from "./ScriptAssistantSettings";
import type { AssistantTargetLine } from "./ScriptAssistantTargetLines";
import { numberedScriptLines } from "./scriptLineNumbers";
import type { LineAssistantForm } from "./useLineAssistantForm";

export function selectedProjectLines(project: StudioProject, target: LineAssistantTarget) {
  const ids = new Set(target.kind === "rewrite" ? target.lineIds : []);
  return project.scenes.flatMap((scene) => scene.lines.filter((line) => ids.has(line.id)));
}

export function selectedTargetLines(project: StudioProject, target: LineAssistantTarget): AssistantTargetLine[] {
  if (target.kind !== "rewrite") return [];
  const selected = new Set(target.lineIds);
  const numbered = numberedScriptLines(project);
  const positions = new Map(numbered.map((item) => [item.lineId, item]));
  return project.scenes.flatMap((scene) =>
    scene.lines.flatMap((line) => {
      if (!selected.has(line.id)) return [];
      const position = positions.get(line.id);
      return [{ line, lineNumber: position?.number ?? null }];
    }),
  );
}

export function selectionIsSparse(project: StudioProject, ids: string[]) {
  const positions = project.scenes.flatMap((scene) => scene.lines.map((line) => line.id));
  const selected = positions.map((id, index) => (ids.includes(id) ? index : -1)).filter((index) => index >= 0);
  return selected.some((index, position) => position > 0 && index !== selected[position - 1] + 1);
}

export function applicableCharacterIds(operation: string, selectedIds: string[], speakerIds: string[]) {
  return operation === "cast-compose" ? selectedIds.filter((id) => speakerIds.includes(id)) : selectedIds;
}

export function initialCharacterIds(participantIds: string[], requiredSpeakerIds: string[]) {
  return participantIds.length ? participantIds : requiredSpeakerIds;
}

export function targetInputError(fixed: boolean, kind: TargetKind, lines: string, minutes: string) {
  if (!fixed && kind === "lines" && (!/^\d+$/.test(lines) || Number(lines) < 1 || Number(lines) > 100)) return "発話行数は1〜100の整数で入力してください。";
  if (!fixed && kind === "minutes" && (!minutes.trim() || !Number.isFinite(Number(minutes)) || Number(minutes) < 0.5 || Number(minutes) > 30)) return "生成時間は0.5〜30分で入力してください。";
  return "";
}

export function supportsSimultaneousCues(operation: string, sparse: boolean) {
  return (operation === "insert" || operation === "rewrite") && !sparse;
}

export function enabledSimultaneousCues(operation: string, sparse: boolean, characterCount: number, enabled: boolean) {
  return supportsSimultaneousCues(operation, sparse) && characterCount > 1 && enabled;
}

export function requiresSimultaneousCues(operation: string, instruction: string) {
  return (operation === "insert" || operation === "rewrite") && explicitlyRequestsSimultaneousSpeech(instruction);
}

function performancePayload(characterCount: number, performance: DraftPerformanceSettings, simultaneousCues: boolean, overlappingSpeech: boolean) {
  const multipleCasts = characterCount > 1;
  return {
    simultaneous_cues: multipleCasts ? simultaneousCues : false,
    overlapping_speech: multipleCasts ? overlappingSpeech : false,
    performance_speech_rate_min: performance.speechRateMin,
    performance_speech_rate_max: performance.speechRateMax,
    performance_gap_min: multipleCasts && overlappingSpeech ? performance.gapMin : 0,
    performance_gap_max: performance.gapMax,
    allowed_emojis: performance.allowedEmojis,
  };
}

export function buildLineAssistantPayload(project: StudioProject, target: LineAssistantTarget, form: LineAssistantForm) {
  const { operation, rewriteMode, characterIds, requiredSpeakerIds, castComposition, castCompositionCharacterIds, effectiveTargetLines, fixedCount, targetKind, simultaneousRequired, instruction, lineCount, minutes, castSettings, performance, simultaneousCuesEnabled, overlappingSpeech } = form;
  return {
    operation,
    scene_id: target.kind === "insert" ? target.sceneId : "",
    before_line_id: target.kind === "insert" ? (target.beforeLineId ?? "") : "",
    line_ids: target.kind === "rewrite" ? effectiveTargetLines.map((line) => line.id) : [],
    character_ids: rewriteMode === "paraphrase" && target.kind === "rewrite" ? Array.from(new Set([...characterIds, ...requiredSpeakerIds])) : castCompositionCharacterIds,
    instruction: castComposition ? "" : instruction,
    target_kind: fixedCount ? "lines" : targetKind,
    target_line_count: fixedCount ? effectiveTargetLines.length : simultaneousRequired && targetKind === "lines" ? Math.max(minimumLinesForSimultaneousSpeech(instruction), Number(lineCount)) : Number(lineCount),
    target_minutes: Number(minutes),
    speech_rate: project.settings.speechRate,
    line_gap: project.settings.lineGap ?? 0.7,
    emoji_expressions: false,
    filler_richness: false,
    cast_settings: castComposition ? {} : draftCastSettingsRequest(castCompositionCharacterIds, castSettings),
    ...performancePayload(characterIds.length, performance, simultaneousCuesEnabled, overlappingSpeech),
  };
}

/** Returns the first reason generation cannot start, or null when the form is valid. */
export function lineAssistantValidationMessage(form: LineAssistantForm, connection: LlmConnection, connectionReady: boolean): string | null {
  const { castComposition, effectiveTargetLines, characterIds, simultaneousRequired, sparse, simultaneousCuesEnabled, fixedCount, targetKind, lineCount, minutes } = form;
  if (!connectionReady) return "接続設定を読み込み中です。完了後にもう一度実行してください。";
  if (!connection.model.trim()) return "設定ページで既定のLLMモデルを選択してください。";
  if (castComposition && !effectiveTargetLines.length) return "選択行に登場する対象キャストを1人以上選択してください。";
  if (!characterIds.length) return "生成対象のキャストを1人以上選択してください。";
  if (simultaneousRequired && sparse) return "飛び飛びの行選択では同時発話を新しく構成できません。連続する範囲を選択してください。";
  if (simultaneousRequired && !simultaneousCuesEnabled) return "「同時発話の提案を許可」をオンにしてください。";
  if (simultaneousRequired && characterIds.length < 2) return "同時発話には生成対象キャストを2人以上選択してください。";
  return targetInputError(fixedCount, targetKind, lineCount, minutes) || null;
}
